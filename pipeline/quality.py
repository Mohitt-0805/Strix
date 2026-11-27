"""Face quality scoring, match-readiness, reliability, and frame selection.

Heavy libraries (cv2, numpy) are imported inside functions only so lightweight
modules can import pipeline.quality without them.
"""

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Literal

from pipeline.contract import Metrics
from pipeline.flags import compute_flags, is_partial_face


_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "quality.json"


@dataclass
class ScoredFace:
    """Quality-scored face observation."""

    t: float
    face_obs: Any
    metrics: Metrics
    quality_score: float
    reliability: Literal["High", "Medium", "Low"]
    flags: list[str]
    is_match_ready: bool
    match_ready_reasons: list[str]
    rank_reason: str = ""
    flag_scores: dict[str, float] | None = None


def load_quality_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load quality weights and thresholds from quality.json."""
    path = config_path or _CONFIG_PATH
    return json.loads(path.read_text(encoding="utf-8"))


def _compute_frontalness(yaw: float | None, pitch: float | None, cfg: dict[str, Any]) -> float:
    """Compute frontalness in [0, 1]: 1.0 at (0, 0), 0.0 at 45 deg yaw or -30 deg pitch."""
    if yaw is None or pitch is None:
        return 0.0
    f_cfg = cfg["frontalness"]
    max_yaw = float(f_cfg["max_yaw_deg"])
    max_pitch_down = float(f_cfg["max_pitch_down_deg"])

    yaw_score = max(0.0, 1.0 - abs(float(yaw)) / max_yaw)
    if float(pitch) < 0.0:
        pitch_score = max(0.0, 1.0 - abs(float(pitch)) / max_pitch_down)
    else:
        pitch_score = max(0.0, 1.0 - float(pitch) / max_yaw)
    return float(max(0.0, min(1.0, yaw_score * pitch_score)))


def _compute_illumination(gray_crop: Any, np_mod: Any, cfg: dict[str, Any]) -> float:
    """Score illumination in [0, 1], peaking in [ideal_low, ideal_high] with good contrast."""
    i_cfg = cfg["illumination"]
    ideal_low = float(i_cfg["ideal_low"])
    ideal_high = float(i_cfg["ideal_high"])
    min_std = float(i_cfg["min_contrast_std"])

    mean_lum = float(np_mod.mean(gray_crop))
    std_lum = float(np_mod.std(gray_crop))

    if ideal_low <= mean_lum <= ideal_high:
        mean_score = 1.0
    elif mean_lum < ideal_low:
        mean_score = max(0.0, mean_lum / ideal_low)
    else:
        mean_score = max(0.0, (255.0 - mean_lum) / max(1.0, 255.0 - ideal_high))

    contrast_factor = min(1.0, std_lum / max(1.0, min_std))
    return float(max(0.0, min(1.0, mean_score * (0.5 + 0.5 * contrast_factor))))


def score_face(
    face_obs: Any,
    frame_bgr: Any,
    cfg: dict[str, Any] | None = None,
) -> tuple[Metrics, float]:
    """Score a single FaceObs on frame_bgr and return (Metrics, quality_score in [0, 1])."""
    config = cfg or load_quality_config()

    if not getattr(face_obs, "face_found", False) or face_obs.face_box is None or frame_bgr is None:
        empty = Metrics(sharpness=0.0, face_size=0.0, pose_yaw=0.0, illumination=0.0, occlusion=1.0)
        return empty, 0.0

    import cv2
    import numpy as np

    h, w = frame_bgr.shape[:2]
    fx1, fy1, fx2, fy2 = face_obs.face_box
    cx1 = max(0, int(round(fx1)))
    cy1 = max(0, int(round(fy1)))
    cx2 = min(w, int(round(fx2)))
    cy2 = min(h, int(round(fy2)))
    if cx2 <= cx1 or cy2 <= cy1:
        empty = Metrics(sharpness=0.0, face_size=0.0, pose_yaw=0.0, illumination=0.0, occlusion=1.0)
        return empty, 0.0

    crop = frame_bgr[cy1:cy2, cx1:cx2]
    resized = cv2.resize(crop, (112, 112), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)

    # Stretch contrast (2nd-98th percentile -> [0, 255]) so Laplacian variance
    # measures edge sharpness independently of overall brightness/exposure.
    p2, p98 = np.percentile(gray, [2, 98])
    if p98 > p2:
        stretched = np.clip((gray.astype(np.float32) - p2) * (255.0 / (p98 - p2)), 0.0, 255.0).astype(np.uint8)
    else:
        stretched = np.zeros_like(gray)

    lap_var = float(cv2.Laplacian(stretched, cv2.CV_64F).var())
    lap_ref = float(config["sharpness"]["lap_var_ref"])
    sharpness = float(max(0.0, min(1.0, lap_var / (lap_var + lap_ref))))

    target_px = float(config["face_size"]["target_px"])
    width_px = float(face_obs.face_width_px or (cx2 - cx1))
    face_size = float(max(0.0, min(1.0, width_px / target_px)))

    pose_yaw = float(face_obs.yaw) if face_obs.yaw is not None else 0.0
    frontalness = _compute_frontalness(face_obs.yaw, face_obs.pitch, config)
    illumination = _compute_illumination(gray, np, config)

    occ_cfg = config["occlusion"]
    occlusion_penalty = 0.0
    if is_partial_face(face_obs, frame_bgr.shape, float(occ_cfg["edge_margin_px"])):
        occlusion_penalty += float(occ_cfg["partial_penalty"])
    det_ref = float(occ_cfg["det_score_ref"])
    det_score = float(face_obs.det_score or 0.0)
    if det_score < det_ref:
        occlusion_penalty += ((det_ref - det_score) / max(1e-6, det_ref)) * 0.5
    occlusion = float(max(0.0, min(1.0, occlusion_penalty)))

    weights = config["weights"]
    quality_score = (
        float(weights["frontalness"]) * frontalness
        + float(weights["sharpness"]) * sharpness
        + float(weights["face_size"]) * face_size
        + float(weights["illumination"]) * illumination
        + float(weights["occlusion_free"]) * (1.0 - occlusion)
    )
    quality_score = float(max(0.0, min(1.0, quality_score)))

    metrics = Metrics(
        sharpness=sharpness,
        face_size=face_size,
        pose_yaw=pose_yaw,
        illumination=illumination,
        occlusion=occlusion,
    )
    return metrics, quality_score


def match_ready(
    face_obs: Any,
    cfg: dict[str, Any] | None = None,
    flags: list[str] | None = None,
) -> tuple[bool, list[str]]:
    """Return (True, []) if face_obs meets frontal/clarity thresholds, else (False, reasons)."""
    config = cfg or load_quality_config()
    mr_cfg = config["match_ready"]
    reasons: list[str] = []

    if not getattr(face_obs, "face_found", False):
        return False, ["no face detected"]

    blocking = set(config.get("reliability", {}).get("match_ready_blocking_flags", ["mask", "helmet"]))
    for fl in flags or []:
        if fl in blocking:
            reasons.append(f"occluded by {fl}")

    det_score = float(face_obs.det_score or 0.0)
    min_det = float(mr_cfg["min_det_score"])
    if det_score < min_det:
        reasons.append(f"det_score {det_score:.2f} < {min_det:.2f}")

    max_yaw = float(mr_cfg["max_abs_yaw"])
    if face_obs.yaw is None or abs(float(face_obs.yaw)) > max_yaw:
        yaw_str = "None" if face_obs.yaw is None else f"{abs(float(face_obs.yaw)):.1f}"
        reasons.append(f"abs(yaw) {yaw_str} > {max_yaw:.1f}")

    min_pitch = float(mr_cfg["min_pitch"])
    if face_obs.pitch is None or float(face_obs.pitch) < min_pitch:
        pitch_str = "None" if face_obs.pitch is None else f"{float(face_obs.pitch):.1f}"
        reasons.append(f"pitch {pitch_str} < {min_pitch:.1f}")

    min_width = float(mr_cfg["min_face_width_px"])
    width_px = float(face_obs.face_width_px or 0.0)
    if width_px < min_width:
        reasons.append(f"face_width_px {width_px:.1f} < {min_width:.1f}")

    return len(reasons) == 0, reasons


def compute_reliability(
    quality_score: float,
    is_match_ready: bool,
    flags: list[str],
    cfg: dict[str, Any] | None = None,
    face_width_px: float | None = None,
) -> Literal["High", "Medium", "Low"]:
    """Assign High / Medium / Low reliability using config-driven flag caps."""
    config = cfg or load_quality_config()
    r_cfg = config["reliability"]
    low_only = set(r_cfg.get("low_only_flags", ["profile view", "looking down", "mask", "helmet"]))
    no_high = set(r_cfg.get("no_high_flags", ["partial face", "small face", "cap"]))

    if any(f in low_only for f in flags):
        return "Low"
    if face_width_px is not None and float(face_width_px) < 50.0:
        return "Low"
    high_blocked = any(f in no_high for f in flags) or (
        face_width_px is not None and float(face_width_px) < 60.0
    )
    if not high_blocked and quality_score >= float(r_cfg["high_min_score"]) and is_match_ready:
        return "High"
    if quality_score >= float(r_cfg["medium_min_score"]):
        return "Medium"
    return "Low"


def score_track_faces(
    face_obs_list: list[Any],
    frames_by_time: dict[float, Any],
    cfg: dict[str, Any] | None = None,
    other_person_boxes_by_time: dict[float, list[list[float]]] | None = None,
    timings_out: dict[str, float] | None = None,
) -> list[ScoredFace]:
    """Score every FaceObs in a track against its corresponding frame."""
    import time
    from pipeline.occluders import head_crop, score_occluders_batch

    config = cfg or load_quality_config()
    scored: list[ScoredFace] = []

    # Batch CLIP occluder detection across all valid face observations in this track.
    t_occ = time.perf_counter()
    valid_indices: list[int] = []
    head_crops: list[Any] = []
    for i, obs in enumerate(face_obs_list):
        frame = frames_by_time.get(float(obs.t))
        if getattr(obs, "face_found", False) and obs.face_box is not None and frame is not None:
            hc = head_crop(frame, obs.face_box)
            if hc is not None:
                valid_indices.append(i)
                head_crops.append(hc)

    occ_flags_by_idx: dict[int, list[str]] = {}
    occ_scores_by_idx: dict[int, dict[str, float]] = {}
    if head_crops:
        flagged_list, scores_list = score_occluders_batch(head_crops)
        for idx, hits, sc in zip(valid_indices, flagged_list, scores_list):
            occ_flags_by_idx[idx] = [h["flag"] for h in hits]
            occ_scores_by_idx[idx] = sc
    if timings_out is not None:
        timings_out["occluders"] = timings_out.get("occluders", 0.0) + (time.perf_counter() - t_occ) * 1000.0

    for i, obs in enumerate(face_obs_list):
        t = float(obs.t)
        frame = frames_by_time.get(t)
        if not getattr(obs, "face_found", False) or frame is None:
            empty = Metrics(sharpness=0.0, face_size=0.0, pose_yaw=0.0, illumination=0.0, occlusion=1.0)
            scored.append(
                ScoredFace(
                    t=t,
                    face_obs=obs,
                    metrics=empty,
                    quality_score=0.0,
                    reliability="Low",
                    flags=[],
                    is_match_ready=False,
                    match_ready_reasons=["no face detected"],
                )
            )
            continue

        metrics, q_score = score_face(obs, frame, config)
        other_boxes = (other_person_boxes_by_time or {}).get(t)
        occ_flags = occ_flags_by_idx.get(i, [])
        occ_scores = occ_scores_by_idx.get(i) or None
        flags = compute_flags(obs, frame, metrics, config, other_person_boxes=other_boxes, occluder_flags=occ_flags)
        ready, reasons = match_ready(obs, config, flags=flags)
        rel = compute_reliability(q_score, ready, flags, config, face_width_px=obs.face_width_px)
        scored.append(
            ScoredFace(
                t=t,
                face_obs=obs,
                metrics=metrics,
                quality_score=q_score,
                reliability=rel,
                flags=flags,
                is_match_ready=ready,
                match_ready_reasons=reasons,
                flag_scores=occ_scores,
            )
        )

    return scored


_RELIABILITY_RANK: dict[str, int] = {"High": 2, "Medium": 1, "Low": 0}


def select_best_frames(
    scored: list[ScoredFace],
    k: int = 5,
    min_gap_sec: float = 0.4,
) -> tuple[list[ScoredFace], str | None]:
    """Pick up to k best faces ordered by (match_ready, reliability, quality_score)."""
    with_faces = [s for s in scored if getattr(s.face_obs, "face_found", False)]
    if not with_faces:
        return [], "Face not visible"

    ranked = sorted(
        with_faces,
        key=lambda s: (
            bool(s.is_match_ready),
            _RELIABILITY_RANK.get(s.reliability, 0),
            float(s.quality_score),
        ),
        reverse=True,
    )
    picked: list[ScoredFace] = []
    for candidate in ranked:
        if all(abs(candidate.t - p.t) >= min_gap_sec for p in picked):
            ready_label = "match-ready" if candidate.is_match_ready else "not match-ready"
            candidate.rank_reason = f"{ready_label}, {candidate.reliability}, score {candidate.quality_score:.2f}"
            picked.append(candidate)
            if len(picked) >= k:
                break

    if not any(s.is_match_ready for s in with_faces):
        return picked, "No frontal face in this window, results are low reliability"
    return picked, None
