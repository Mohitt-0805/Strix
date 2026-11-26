"""Tests for pipeline.quality and pipeline.flags."""

import subprocess
import sys

import numpy as np
import pytest

from pipeline.faces import FaceObs
from pipeline.flags import compute_flags, detect_occluders
from pipeline.quality import (
    ScoredFace,
    compute_reliability,
    load_quality_config,
    match_ready,
    score_face,
    select_best_frames,
)


def test_lazy_imports_quality_and_flags() -> None:
    """Importing pipeline.quality and pipeline.flags must not load cv2."""
    code = (
        "import sys; "
        "import pipeline.quality; "
        "import pipeline.flags; "
        "assert 'cv2' not in sys.modules, 'cv2 imported at module top level'"
    )
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr or res.stdout


def _load_sample_face_and_frame() -> tuple[np.ndarray, FaceObs]:
    """Load a real face image and detect a single FaceObs for degradation tests."""
    import insightface.data
    from pipeline.faces import get_face_app

    try:
        img = insightface.data.get_image("t1")
    except Exception:
        img = None

    if img is None:
        pytest.skip("No sample face image available")

    app = get_face_app()
    faces = app.get(img)
    if not faces:
        pytest.skip("No face detected in sample image")

    best = max(faces, key=lambda f: float(f.det_score))
    h, w = img.shape[:2]
    bx1, by1, bx2, by2 = [float(v) for v in best.bbox]
    obs = FaceObs(
        t=1.0,
        face_found=True,
        face_box=[bx1, by1, bx2, by2],
        det_score=float(best.det_score),
        landmarks=None,
        yaw=0.0,
        pitch=0.0,
        roll=0.0,
        yaw_lm=0.0,
        face_width_px=float(bx2 - bx1),
        embedding=None,
        person_box=[0.0, 0.0, float(w), float(h)],
    )
    return img, obs


def test_degraded_copies_affect_metrics_and_flags() -> None:
    """Degraded copies (blur, dark, bright, 40px, off-center) behave as expected."""
    import cv2

    cfg = load_quality_config()
    img, obs = _load_sample_face_and_frame()
    orig_metrics, orig_q = score_face(obs, img, cfg)

    # 1. Gaussian blur -> sharpness clearly below original and 'blur' flag appears.
    blurred = cv2.GaussianBlur(img, (21, 21), 6.0)
    blur_metrics, _ = score_face(obs, blurred, cfg)
    blur_flags = compute_flags(obs, blurred, blur_metrics, cfg)
    assert blur_metrics.sharpness < orig_metrics.sharpness * 0.5
    assert "blur" in blur_flags

    # 2. Darker -> illumination drops, 'low light' flag appears, NO false 'blur' flag.
    darker = np.clip(img.astype(np.float32) * 0.15, 0, 255).astype(np.uint8)
    dark_metrics, _ = score_face(obs, darker, cfg)
    dark_flags = compute_flags(obs, darker, dark_metrics, cfg)
    assert dark_metrics.illumination < orig_metrics.illumination
    assert "low light" in dark_flags
    assert "blur" not in dark_flags

    # 3. Brighter -> illumination drops, sharpness stays within 0.1 of original.
    brighter = np.clip(img.astype(np.float32) * 1.4 + 45.0, 0, 255).astype(np.uint8)
    bright_metrics, _ = score_face(obs, brighter, cfg)
    assert bright_metrics.illumination < orig_metrics.illumination
    assert abs(bright_metrics.sharpness - orig_metrics.sharpness) < 0.1

    # 4. Shrunk to 40 px -> face_size drops, 'small face' flag appears, loses >= 0.12 quality_score.
    shrunk_obs = FaceObs(
        t=1.0,
        face_found=True,
        face_box=[10.0, 10.0, 50.0, 50.0],
        det_score=obs.det_score,
        landmarks=None,
        yaw=0.0,
        pitch=0.0,
        roll=0.0,
        yaw_lm=0.0,
        face_width_px=40.0,
        embedding=None,
        person_box=[0.0, 0.0, 100.0, 100.0],
    )
    shrunk_metrics, shrunk_q = score_face(shrunk_obs, img, cfg)
    shrunk_flags = compute_flags(shrunk_obs, img, shrunk_metrics, cfg)
    assert shrunk_metrics.face_size < orig_metrics.face_size
    assert "small face" in shrunk_flags
    assert (orig_q - shrunk_q) >= 0.12

    # 5. Cropped off-center (touching frame edge) -> 'partial face' flag appears, loses >= 0.12 quality_score.
    edge_obs = FaceObs(
        t=1.0,
        face_found=True,
        face_box=[0.0, 10.0, 80.0, 90.0],
        det_score=obs.det_score,
        landmarks=None,
        yaw=0.0,
        pitch=0.0,
        roll=0.0,
        yaw_lm=0.0,
        face_width_px=80.0,
        embedding=None,
        person_box=[0.0, 0.0, 200.0, 200.0],
    )
    edge_metrics, edge_q = score_face(edge_obs, img, cfg)
    edge_flags = compute_flags(edge_obs, img, edge_metrics, cfg)
    assert "partial face" in edge_flags
    assert (orig_q - edge_q) >= 0.12

    assert detect_occluders(img) == []


def test_profile_and_looking_down_never_high_or_medium() -> None:
    """Profile/looking-down are Low; partial/small faces can never be High."""
    assert compute_reliability(0.95, True, ["profile view"]) == "Low"
    assert compute_reliability(0.95, True, ["looking down"]) == "Low"
    assert compute_reliability(0.95, True, ["partial face"]) == "Medium"
    assert compute_reliability(0.95, True, ["small face"]) == "Medium"
    assert compute_reliability(0.45, True, ["partial face"]) == "Low"
    assert compute_reliability(0.80, True, []) == "High"
    assert compute_reliability(0.60, False, []) == "Medium"
    assert compute_reliability(0.40, False, []) == "Low"


def test_match_ready_thresholds_and_reasons() -> None:
    """match_ready checks det_score, yaw, pitch, and face_width_px."""
    good = FaceObs(
        t=0.0,
        face_found=True,
        face_box=[10, 10, 90, 90],
        det_score=0.85,
        landmarks=None,
        yaw=10.0,
        pitch=-10.0,
        roll=0.0,
        yaw_lm=5.0,
        face_width_px=80.0,
        embedding=None,
        person_box=[0, 0, 100, 100],
    )
    ok, reasons = match_ready(good)
    assert ok is True
    assert reasons == []

    bad = FaceObs(
        t=0.0,
        face_found=True,
        face_box=[10, 10, 50, 50],
        det_score=0.5,
        landmarks=None,
        yaw=50.0,
        pitch=-35.0,
        roll=0.0,
        yaw_lm=50.0,
        face_width_px=40.0,
        embedding=None,
        person_box=[0, 0, 100, 100],
    )
    ok_bad, reasons_bad = match_ready(bad)
    assert ok_bad is False
    assert len(reasons_bad) == 4


def test_select_best_frames_spacing_and_reasons() -> None:
    """select_best_frames enforces min_gap_sec and returns required reason messages."""
    from pipeline.contract import Metrics

    empty_obs = FaceObs(0.0, False, None, None, None, None, None, None, None, None, None, [0, 0, 10, 10])
    m = Metrics(sharpness=0.5, face_size=0.5, pose_yaw=0.0, illumination=0.5, occlusion=0.0)
    no_faces = [ScoredFace(0.0, empty_obs, m, 0.0, "Low", [], False, ["no face detected"])]
    picked_empty, reason_empty = select_best_frames(no_faces)
    assert picked_empty == []
    assert reason_empty == "Face not visible"

    def _sf(t: float, q: float, ready: bool) -> ScoredFace:
        obs = FaceObs(t, True, [10, 10, 90, 90], 0.8, None, 10.0, -5.0, 0.0, 0.0, 80.0, None, [0, 0, 100, 100])
        return ScoredFace(t, obs, m, q, "Low", [], ready, [] if ready else ["not frontal"])

    # Non-ready candidates with close timestamps (0.1s apart).
    candidates = [_sf(1.0, 0.9, False), _sf(1.1, 0.85, False), _sf(1.6, 0.8, False)]
    picked, reason = select_best_frames(candidates, k=5, min_gap_sec=0.4)
    assert [round(p.t, 2) for p in picked] == [1.0, 1.6]
    assert reason == "No frontal face in this window, results are low reliability"


def test_select_best_frames_ordering_tiers() -> None:
    """select_best_frames ranks match_ready > reliability tier > quality_score."""
    from pipeline.contract import Metrics

    m = Metrics(sharpness=0.5, face_size=0.5, pose_yaw=0.0, illumination=0.5, occlusion=0.0)

    def _item(t: float, q: float, rel: str, ready: bool) -> ScoredFace:
        obs = FaceObs(t, True, [10, 10, 90, 90], 0.8, None, 10.0, -5.0, 0.0, 0.0, 80.0, None, [0, 0, 100, 100])
        return ScoredFace(t, obs, m, q, rel, [], ready, [])  # type: ignore[arg-type]

    # (a) atm_155 case: match-ready Medium (0.519) beats non-ready Low (0.551).
    atm_155_low = _item(158.52, 0.551, "Low", False)
    atm_155_med = _item(152.51, 0.519, "Medium", True)
    picked_155, reason_155 = select_best_frames([atm_155_low, atm_155_med], k=5, min_gap_sec=0.4)
    assert [p.t for p in picked_155] == [152.51, 158.52]
    assert picked_155[0].rank_reason == "match-ready, Medium, score 0.52"
    assert reason_155 is None

    # (b) High beats Medium, and (c) equal tiers break ties by quality_score.
    med_hi_q = _item(2.0, 0.85, "Medium", True)
    high_lo_q = _item(4.0, 0.72, "High", True)
    med_lo_q = _item(6.0, 0.60, "Medium", True)
    picked_tiers, _ = select_best_frames([med_lo_q, med_hi_q, high_lo_q], k=5, min_gap_sec=0.4)
    assert [p.t for p in picked_tiers] == [4.0, 2.0, 6.0]


def test_reliability_width_caps_under_50_and_60() -> None:
    """Faces < 50 px are capped at Low; faces < 60 px cannot be High."""
    assert compute_reliability(0.95, True, [], face_width_px=49.0) == "Low"
    assert compute_reliability(0.95, True, ["small face"], face_width_px=55.0) == "Medium"
    assert compute_reliability(0.95, True, [], face_width_px=55.0) == "Medium"
    assert compute_reliability(0.95, True, [], face_width_px=65.0) == "High"


def test_low_light_uses_landmark_inner_region() -> None:
    """low light is measured on the 5-landmark eye-to-mouth region when available."""
    from pipeline.contract import Metrics

    cfg = load_quality_config()
    metrics = Metrics(sharpness=0.8, face_size=0.9, pose_yaw=0.0, illumination=0.8, occlusion=0.0)
    landmarks = [
        [45.0, 45.0],
        [75.0, 45.0],
        [60.0, 60.0],
        [48.0, 75.0],
        [72.0, 75.0],
    ]
    obs = FaceObs(
        t=0.0,
        face_found=True,
        face_box=[20.0, 20.0, 100.0, 100.0],
        det_score=0.9,
        landmarks=landmarks,
        yaw=0.0,
        pitch=0.0,
        roll=0.0,
        yaw_lm=0.0,
        face_width_px=80.0,
        embedding=None,
        person_box=[0.0, 0.0, 120.0, 120.0],
    )

    # Dark outer crop (10), bright inner landmark region (150) -> NOT low light.
    frame_bright_inner = np.full((120, 120, 3), 10, dtype=np.uint8)
    frame_bright_inner[40:80, 40:80] = 150
    flags_bright = compute_flags(obs, frame_bright_inner, metrics, cfg)
    assert "low light" not in flags_bright

    # Bright outer crop (180), dark inner landmark region (20) -> low light.
    frame_dark_inner = np.full((120, 120, 3), 180, dtype=np.uint8)
    frame_dark_inner[40:80, 40:80] = 20
    flags_dark = compute_flags(obs, frame_dark_inner, metrics, cfg)
    assert "low light" in flags_dark


