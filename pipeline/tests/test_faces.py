"""Tests for pipeline.faces and pipeline.embeddings."""

import subprocess
import sys

import numpy as np
import pytest

from pipeline.detect_track import Track


def test_lazy_imports_do_not_load_heavy_libraries() -> None:
    """Importing pipeline.faces and pipeline.embeddings must not load heavy libs."""
    code = (
        "import sys; "
        "import pipeline.faces; "
        "import pipeline.embeddings; "
        "loaded = [m for m in ('insightface', 'onnxruntime', 'cv2') if m in sys.modules]; "
        "assert not loaded, f'Unexpected heavy imports: {loaded}'"
    )
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr or res.stdout


def test_detect_faces_on_track_blank_image_no_crash() -> None:
    """detect_faces_on_track returns face_found=False without crashing on a blank image."""
    from pipeline.faces import detect_faces_on_track

    blank = np.zeros((240, 320, 3), dtype=np.uint8)
    track = Track(
        track_id=1,
        observations=[
            {"t": 0.0, "box": [50.0, 40.0, 150.0, 200.0], "score": 0.9},
            {"t": 0.5, "box": [0.0, 0.0, 1.0, 1.0], "score": 0.8},  # tiny edge crop
            {"t": 1.0, "box": [10.0, 10.0, 100.0, 100.0], "score": 0.7},  # missing frame
        ],
    )
    results = detect_faces_on_track(track, {0.0: blank, 0.5: blank})
    assert len(results) == 3
    for obs, expected_box in zip(results, [o["box"] for o in track.observations]):
        assert obs.face_found is False
        assert obs.person_box == expected_box
        assert obs.embedding is None


def test_embed_crop_smoke_sample_image() -> None:
    """Smoke test on insightface sample image: embedding shape (512,) and norm ~1."""
    import insightface.data
    from pipeline.embeddings import cosine, embed_crop, load_embedding, save_embedding

    try:
        img = insightface.data.get_image("t1")
    except Exception:
        img = None

    if img is None:
        pytest.skip("No sample face image available in insightface.data")

    emb = embed_crop(img)
    assert emb is not None
    assert emb.shape == (512,)
    assert np.isclose(np.linalg.norm(emb), 1.0, atol=1e-3)
    assert np.isclose(cosine(emb, emb), 1.0, atol=1e-4)

    # Verify save/load round-trip.
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "test_emb.npy"
        save_embedding(out_path, emb)
        loaded = load_embedding(out_path)
        assert loaded.shape == (512,)
        assert np.allclose(loaded, emb)


def test_estimate_yaw_from_landmarks_synthetic() -> None:
    """Frontal 5-point landmarks give yaw_lm ~0; shifted nose gives non-zero with right sign."""
    from pipeline.faces import estimate_yaw_from_landmarks

    # Eyes at x=100 and x=200 (midpoint 150).
    frontal = [
        [100.0, 100.0],  # left eye
        [200.0, 100.0],  # right eye
        [150.0, 130.0],  # nose centered
        [120.0, 160.0],  # left mouth
        [180.0, 160.0],  # right mouth
    ]
    yaw_frontal = estimate_yaw_from_landmarks(frontal)
    assert yaw_frontal is not None
    assert abs(yaw_frontal) < 1e-6

    # Nose shifted toward right eye (+x) -> positive yaw_lm.
    right_shifted = [list(pt) for pt in frontal]
    right_shifted[2][0] = 175.0
    yaw_right = estimate_yaw_from_landmarks(right_shifted)
    assert yaw_right is not None
    assert yaw_right > 20.0

    # Nose shifted toward left eye (-x) -> negative yaw_lm.
    left_shifted = [list(pt) for pt in frontal]
    left_shifted[2][0] = 125.0
    yaw_left = estimate_yaw_from_landmarks(left_shifted)
    assert yaw_left is not None
    assert yaw_left < -20.0
    assert np.isclose(yaw_right, -yaw_left)


def test_embed_tight_crop_padded_and_from_landmarks_and_blank() -> None:
    """Tight crop succeeds via padded retry, embed_from_landmarks matches, blank returns None."""
    import insightface.data
    from pipeline.embeddings import cosine, embed_crop, embed_from_landmarks
    from pipeline.faces import get_face_app

    # Blank image returns None without crashing.
    blank = np.zeros((100, 100, 3), dtype=np.uint8)
    vec_blank, meta_blank = embed_crop(blank, info=True)
    assert vec_blank is None
    assert meta_blank["attempt"] is None

    try:
        img = insightface.data.get_image("t1")
    except Exception:
        img = None
    if img is None:
        pytest.skip("No sample face image available in insightface.data")

    app = get_face_app()
    faces = app.get(img)
    if not faces:
        pytest.skip("No face detected in sample image")

    best = max(faces, key=lambda f: float(f.det_score))
    full_vec = np.asarray(best.normed_embedding, dtype=np.float32)

    h, w = img.shape[:2]
    x1, y1, x2, y2 = [int(round(v)) for v in best.bbox]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    tight_crop = img[y1:y2, x1:x2]

    crop_vec, meta = embed_crop(tight_crop, info=True)
    assert crop_vec is not None
    assert crop_vec.shape == (512,)
    assert meta["attempt"] == "padded"
    assert cosine(crop_vec, full_vec) > 0.8

    # embed_from_landmarks on the tight crop with landmarks shifted to crop coordinates.
    shifted_kps = np.asarray(best.kps, dtype=np.float32) - np.array([[x1, y1]], dtype=np.float32)
    lm_vec = embed_from_landmarks(tight_crop, shifted_kps)
    assert lm_vec is not None
    assert lm_vec.shape == (512,)
    assert np.isclose(np.linalg.norm(lm_vec), 1.0, atol=1e-3)
    assert cosine(lm_vec, full_vec) > 0.8


def test_head_region_selection_and_shared_face_assignment_no_models() -> None:
    """Model-free tests for head-region filtering, one-face-per-track, and overlapping person flag."""
    from pipeline.contract import Metrics
    from pipeline.faces import FaceObs, assign_faces_to_tracks, select_face_for_person_box
    from pipeline.flags import compute_flags
    from pipeline.quality import load_quality_config

    # (a) Two overlapping person boxes with two candidate faces -> each gets its own face.
    pbox_a = [0.0, 0.0, 120.0, 200.0]
    pbox_b = [80.0, 0.0, 200.0, 200.0]
    face_a = [30.0, 10.0, 70.0, 50.0]   # centred at (50, 30) -> inside A's head region
    face_b = [130.0, 10.0, 170.0, 50.0]  # centred at (150, 30) -> inside B's head region
    cands = [("fa", face_a, 0.85), ("fb", face_b, 0.90)]
    pick_a, reason_a = select_face_for_person_box(cands, pbox_a)
    pick_b, reason_b = select_face_for_person_box(cands, pbox_b)
    assert pick_a == "fa" and reason_a is None
    assert pick_b == "fb" and reason_b is None

    # (c) Face in lower half of person box -> rejected with "no face in head region".
    lower_face = [30.0, 120.0, 70.0, 160.0]  # y_centre = 140 > 0.45 * 200 = 90
    pick_low, reason_low = select_face_for_person_box([("flow", lower_face, 0.99)], pbox_a)
    assert pick_low is None
    assert reason_low == "no face in head region"

    # (b) Both tracks claiming the same face -> higher head-region containment keeps it.
    shared_face = [50.0, 15.0, 90.0, 55.0]  # fully inside pbox_a, only partially in pbox_b (x>=80)
    obs_a = FaceObs(1.0, True, shared_face, 0.9, None, 0.0, 0.0, 0.0, 0.0, 40.0, None, pbox_a)
    obs_b = FaceObs(1.0, True, shared_face, 0.9, None, 0.0, 0.0, 0.0, 0.0, 40.0, None, pbox_b)
    assigned = assign_faces_to_tracks({1: obs_a, 2: obs_b}, iou_thresh=0.5)
    assert assigned[1].face_found is True
    assert assigned[2].face_found is False
    assert assigned[2].reason == "face shared with another person"

    # (d) "overlapping person" flag appears only above IoU 0.2.
    cfg = load_quality_config()
    frame = np.full((240, 320, 3), 130, dtype=np.uint8)
    metrics = Metrics(sharpness=0.8, face_size=0.8, pose_yaw=0.0, illumination=0.8, occlusion=0.0)
    # pbox_a area = 120*200 = 24000; pbox_b overlaps [80..120]x[0..200] = 8000; IoU = 8000/(48000-8000) = 0.20 (not > 0.2).
    flags_at_02 = compute_flags(obs_a, frame, metrics, cfg, other_person_boxes=[pbox_b])
    assert "overlapping person" not in flags_at_02

    pbox_close = [60.0, 0.0, 180.0, 200.0]  # IoU = 12000 / 36000 = 0.333 > 0.2
    flags_above = compute_flags(obs_a, frame, metrics, cfg, other_person_boxes=[pbox_close])
    assert "overlapping person" in flags_above



