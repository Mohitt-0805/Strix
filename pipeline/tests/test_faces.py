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

