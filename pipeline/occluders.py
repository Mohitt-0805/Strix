"""CLIP zero-shot occluder detection (cap, mask, helmet).

Heavy ML libraries (torch, open_clip, cv2, PIL) are imported inside functions
only so lightweight modules can import pipeline.occluders without them.
"""

import json
import math
import os
from pathlib import Path
from typing import Any


_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "occluders.json"
_CLIP_BUNDLE: dict[str, Any] | None = None
_CLIP_LOAD_FAILED = False


def load_occluders_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load CLIP prompts, thresholds, batch_size, and enabled flag from JSON."""
    path = config_path or _CONFIG_PATH
    return json.loads(path.read_text(encoding="utf-8"))


def head_crop(
    frame_bgr: Any,
    face_box: list[float] | tuple[float, float, float, float],
    up: float = 0.8,
    side: float = 0.4,
    down: float = 0.25,
) -> Any | None:
    """Expand face_box [x1, y1, x2, y2] to include head/hat/helmet region and clip to frame."""
    if frame_bgr is None or getattr(frame_bgr, "size", 0) == 0:
        return None
    fh, fw = frame_bgr.shape[:2]
    x1, y1, x2, y2 = [float(v) for v in face_box]
    bw = max(1.0, x2 - x1)
    bh = max(1.0, y2 - y1)

    cx1 = max(0, int(math.floor(x1 - side * bw)))
    cy1 = max(0, int(math.floor(y1 - up * bh)))
    cx2 = min(fw, int(math.ceil(x2 + side * bw)))
    cy2 = min(fh, int(math.ceil(y2 + down * bh)))
    if cx2 <= cx1 or cy2 <= cy1:
        return None
    return frame_bgr[cy1:cy2, cx1:cx2]


def prompt_pair_probs(sim_present: float, sim_absent: float, logit_scale: float) -> tuple[float, float]:
    """Compute (p_present, margin) via softmax over logit_scale * [sim_present, sim_absent]."""
    lp = float(logit_scale) * float(sim_present)
    la = float(logit_scale) * float(sim_absent)
    m = max(lp, la)
    ep = math.exp(lp - m)
    ea = math.exp(la - m)
    p = ep / (ep + ea)
    return float(p), float(sim_present - sim_absent)


def _encode_prompt_groups(
    model: Any,
    tokenizer: Any,
    prompts_cfg: dict[str, dict[str, list[str]]],
    device: str,
    torch_mod: Any,
) -> dict[str, tuple[Any, Any]]:
    """Precompute unit-normalised mean text embeddings for each flag's present/absent prompts."""
    encoded: dict[str, tuple[Any, Any]] = {}
    with torch_mod.no_grad():
        for flag, groups in prompts_cfg.items():
            vecs: list[Any] = []
            for key in ("present", "absent"):
                texts = groups[key]
                tokens = tokenizer(texts).to(device)
                tf = model.encode_text(tokens)
                tf = tf / tf.norm(dim=-1, keepdim=True)
                mean_tf = tf.mean(dim=0)
                mean_tf = mean_tf / mean_tf.norm()
                vecs.append(mean_tf)
            encoded[flag] = (vecs[0], vecs[1])
    return encoded


def get_model(cfg: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Load and cache OpenCLIP ViT-B-32 (openai) under MODEL_DIR; return None on failure."""
    global _CLIP_BUNDLE, _CLIP_LOAD_FAILED
    if _CLIP_BUNDLE is not None:
        return _CLIP_BUNDLE
    if _CLIP_LOAD_FAILED:
        return None

    config = cfg or load_occluders_config()
    if not config.get("enabled", True):
        return None

    import open_clip
    import torch

    model_name = str(config.get("model_name", "ViT-B-32"))
    pretrained = str(config.get("pretrained", "openai"))
    model_dir = Path(os.environ.get("MODEL_DIR", "data/models")) / "clip"
    model_dir.mkdir(parents=True, exist_ok=True)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    precisions = ["fp16", "fp32"] if device == "cuda" else ["fp32"]

    last_exc: Exception | None = None
    for prec in precisions:
        try:
            model, _, preprocess = open_clip.create_model_and_transforms(
                model_name,
                pretrained=pretrained,
                precision=prec,
                device=device,
                force_quick_gelu=(pretrained == "openai"),
                cache_dir=str(model_dir),
            )
            model.eval()
            tokenizer = open_clip.get_tokenizer(model_name)
            text_groups = _encode_prompt_groups(model, tokenizer, config["prompts"], device, torch)
            logit_scale = float(model.logit_scale.exp().item())
            _CLIP_BUNDLE = {
                "model": model,
                "preprocess": preprocess,
                "tokenizer": tokenizer,
                "device": device,
                "precision": prec,
                "text_groups": text_groups,
                "logit_scale": logit_scale,
            }
            return _CLIP_BUNDLE
        except Exception as exc:
            last_exc = exc

    _CLIP_LOAD_FAILED = True
    print(f"[occluders] Warning: CLIP model unavailable ({last_exc}); occluder flags disabled")
    return None


def score_occluders_batch(
    crops_bgr: list[Any],
    cfg: dict[str, Any] | None = None,
) -> tuple[list[list[dict[str, Any]]], list[dict[str, float]]]:
    """Run batched CLIP zero-shot scoring on BGR head crops.

    Returns (flagged_dicts_per_crop, all_flag_p_per_crop).
    """
    config = cfg or load_occluders_config()
    if not crops_bgr or not config.get("enabled", True):
        return [[] for _ in crops_bgr], [{} for _ in crops_bgr]

    bundle = get_model(config)
    if bundle is None:
        return [[] for _ in crops_bgr], [{} for _ in crops_bgr]

    import cv2
    from PIL import Image
    import torch

    model = bundle["model"]
    preprocess = bundle["preprocess"]
    device = bundle["device"]
    text_groups: dict[str, tuple[Any, Any]] = bundle["text_groups"]
    logit_scale = float(bundle["logit_scale"])
    thresholds: dict[str, float] = {k: float(v) for k, v in config["thresholds"].items()}
    batch_size = max(1, int(config.get("batch_size", 16)))

    flagged_all: list[list[dict[str, Any]]] = []
    scores_all: list[dict[str, float]] = []

    valid_indices = [i for i, c in enumerate(crops_bgr) if c is not None and getattr(c, "size", 0) > 0]
    results_flagged: list[list[dict[str, Any]]] = [[] for _ in crops_bgr]
    results_scores: list[dict[str, float]] = [{} for _ in crops_bgr]

    with torch.no_grad():
        for start in range(0, len(valid_indices), batch_size):
            batch_idx = valid_indices[start : start + batch_size]
            tensors = []
            for idx in batch_idx:
                rgb = cv2.cvtColor(crops_bgr[idx], cv2.COLOR_BGR2RGB)
                tensors.append(preprocess(Image.fromarray(rgb)))
            batch_tensor = torch.stack(tensors).to(device)
            if bundle["precision"] == "fp16":
                batch_tensor = batch_tensor.half()

            img_feats = model.encode_image(batch_tensor)
            img_feats = img_feats / img_feats.norm(dim=-1, keepdim=True)

            for row_i, orig_i in enumerate(batch_idx):
                feat = img_feats[row_i].float()
                crop_flags: list[dict[str, Any]] = []
                crop_scores: dict[str, float] = {}
                for flag, (pres_vec, abs_vec) in text_groups.items():
                    sim_p = float(torch.dot(feat, pres_vec.float()).item())
                    sim_a = float(torch.dot(feat, abs_vec.float()).item())
                    p, margin = prompt_pair_probs(sim_p, sim_a, logit_scale)
                    crop_scores[flag] = round(p, 4)
                    if p >= thresholds.get(flag, 1.0):
                        crop_flags.append({"flag": flag, "p": round(p, 4), "margin": round(margin, 4)})
                results_flagged[orig_i] = crop_flags
                results_scores[orig_i] = crop_scores

    flagged_all.extend(results_flagged)
    scores_all.extend(results_scores)
    return flagged_all, scores_all


def detect_occluders_batch(
    crops_bgr: list[Any],
    cfg: dict[str, Any] | None = None,
) -> list[list[dict[str, Any]]]:
    """Return per-crop list of triggered {flag, p, margin} dicts."""
    flagged, _ = score_occluders_batch(crops_bgr, cfg=cfg)
    return flagged
