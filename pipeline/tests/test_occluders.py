"""Tests for pipeline.occluders, reliability caps, and lazy imports."""

from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest


def test_lazy_imports_occluders() -> None:
    """Importing pipeline.occluders must not import torch, open_clip, or cv2."""
    code = (
        "import sys; "
        "import pipeline.occluders; "
        "loaded = [m for m in ('torch', 'open_clip', 'cv2') if m in sys.modules]; "
        "assert not loaded, f'Unexpected heavy imports: {loaded}'"
    )
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr or res.stdout


def test_head_crop_expansion_and_clipping() -> None:
    """head_crop expands more above the face and clips cleanly to frame bounds."""
    from pipeline.occluders import head_crop

    frame = np.zeros((200, 300, 3), dtype=np.uint8)
    # Face box [100, 80, 150, 130] -> w=50, h=50.
    # up=0.8*50=40 -> y1=40; down=0.25*50=12.5 -> y2=143; side=0.4*50=20 -> x1=80, x2=170.
    crop = head_crop(frame, [100.0, 80.0, 150.0, 130.0])
    assert crop is not None
    assert crop.shape == (103, 90, 3)

    # Near top-left edge -> clipped at 0 without crashing.
    edge_crop = head_crop(frame, [5.0, 5.0, 45.0, 45.0])
    assert edge_crop is not None
    assert edge_crop.shape[0] > 40 and edge_crop.shape[1] > 40


def test_prompt_pair_softmax_math_and_threshold_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify prompt_pair_probs softmax math and threshold boundary with a stubbed model."""
    from pipeline import occluders
    from pipeline.occluders import prompt_pair_probs, score_occluders_batch

    # Equal similarities -> p = 0.5, margin = 0.0.
    p_eq, m_eq = prompt_pair_probs(0.25, 0.25, logit_scale=100.0)
    assert p_eq == pytest.approx(0.5, abs=1e-6)
    assert m_eq == pytest.approx(0.0, abs=1e-6)

    # Present higher by 0.02 with logit_scale=100 -> exp(2) / (exp(2) + 1) ≈ 0.8808.
    p_hi, m_hi = prompt_pair_probs(0.30, 0.28, logit_scale=100.0)
    assert p_hi == pytest.approx(0.880797, abs=1e-4)
    assert m_hi == pytest.approx(0.02, abs=1e-6)

    # Stubbed CLIP model testing threshold boundaries (cap=0.80):
    # diff = +0.013 -> p ≈ 0.7858 (< 0.80, not flagged)
    # diff = +0.015 -> p ≈ 0.8176 (>= 0.80, flagged)
    import torch

    class _FakeModel:
        def encode_image(self, x: torch.Tensor) -> torch.Tensor:
            out = torch.zeros((x.shape[0], 4), dtype=torch.float32)
            out[:, 0] = 1.0
            return out

    fake_bundle = {
        "model": _FakeModel(),
        "preprocess": lambda im: torch.zeros((3, 224, 224), dtype=torch.float32),
        "tokenizer": None,
        "device": "cpu",
        "precision": "fp32",
        "logit_scale": 100.0,
        "text_groups": {
            "cap": (torch.tensor([0.313, 0.0, 0.0, 0.0]), torch.tensor([0.300, 0.0, 0.0, 0.0])),
            "mask": (torch.tensor([0.315, 0.0, 0.0, 0.0]), torch.tensor([0.300, 0.0, 0.0, 0.0])),
            "helmet": (torch.tensor([0.200, 0.0, 0.0, 0.0]), torch.tensor([0.300, 0.0, 0.0, 0.0])),
        },
    }
    monkeypatch.setattr(occluders, "get_model", lambda cfg=None: fake_bundle)

    crop = np.full((64, 64, 3), 128, dtype=np.uint8)
    flagged, scores = score_occluders_batch([crop])
    flag_names = [h["flag"] for h in flagged[0]]
    assert "cap" not in flag_names  # p=0.7858 < 0.80
    assert "mask" in flag_names     # p=0.8176 >= 0.80
    assert "helmet" not in flag_names
    assert scores[0]["cap"] < 0.80
    assert scores[0]["mask"] >= 0.80


def test_model_none_returns_empty_and_no_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """When get_model() returns None, detect_occluders returns [] without crashing."""
    from pipeline import occluders
    from pipeline.faces import FaceObs
    from pipeline.flags import detect_occluders

    monkeypatch.setattr(occluders, "get_model", lambda cfg=None: None)
    obs = FaceObs(0.0, True, [10, 10, 50, 50], 0.9, None, 0.0, 0.0, 0.0, 0.0, 40.0, None, [0, 0, 60, 60])
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    assert detect_occluders(obs, frame) == []


def test_occluder_reliability_and_match_ready_caps() -> None:
    """mask/helmet cap to Low + match_ready=False; cap caps at Medium."""
    from pipeline.faces import FaceObs
    from pipeline.quality import compute_reliability, match_ready

    obs = FaceObs(0.0, True, [10, 10, 90, 90], 0.9, None, 5.0, -5.0, 0.0, 0.0, 80.0, None, [0, 0, 100, 100])
    assert compute_reliability(0.95, True, ["mask"], face_width_px=80.0) == "Low"
    assert compute_reliability(0.95, True, ["helmet"], face_width_px=80.0) == "Low"
    assert compute_reliability(0.95, True, ["cap"], face_width_px=80.0) == "Medium"

    ok_mask, reasons_mask = match_ready(obs, flags=["mask"])
    assert ok_mask is False
    assert any("mask" in r for r in reasons_mask)

    ok_helmet, reasons_helmet = match_ready(obs, flags=["helmet"])
    assert ok_helmet is False
    assert any("helmet" in r for r in reasons_helmet)


def test_clip_occluder_integration_if_cached() -> None:
    """Integration test: skips cleanly if CLIP weights are not cached locally."""
    import os
    from pipeline.occluders import get_model, score_occluders_batch

    os.environ["HF_HUB_OFFLINE"] = "1"
    bundle = get_model()
    if bundle is None:
        pytest.skip("OpenCLIP ViT-B-32 weights not cached locally")

    img = np.full((128, 128, 3), 120, dtype=np.uint8)
    _, scores = score_occluders_batch([img])
    assert set(scores[0].keys()) == {"cap", "mask", "helmet"}
    for p in scores[0].values():
        assert 0.0 <= p <= 1.0
