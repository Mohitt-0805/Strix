"""Tests for pipeline/detect_track.py person detection."""

from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request

import pytest

from pipeline.detect_track import detect_persons, get_device, load_person_detector


TEST_IMAGE_URL = (
    "https://raw.githubusercontent.com/pytorch/vision/main/gallery/assets/person1.jpg"
)


def test_import_detect_track_does_not_import_heavy_libs() -> None:
    """Importing pipeline.detect_track must not eagerly import torch, torchvision, or cv2."""
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys, pipeline.detect_track; "
                "assert not {'torch', 'torchvision', 'cv2'}.intersection(sys.modules)"
            ),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_detect_persons_on_still_image(tmp_path: Path) -> None:
    """Download a public-domain person image and verify at least one person is detected."""
    import cv2

    img_path = tmp_path / "person1.jpg"
    try:
        with urllib.request.urlopen(TEST_IMAGE_URL, timeout=10) as resp:
            img_path.write_bytes(resp.read())
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        pytest.skip(f"No internet or failed to download test image: {exc}")

    frame = cv2.imread(str(img_path))
    assert frame is not None

    model = load_person_detector(device=get_device())
    detections = detect_persons([frame], score_thresh=0.5, model=model)

    assert len(detections) == 1
    assert len(detections[0]) >= 1
    first = detections[0][0]
    assert len(first["box"]) == 4
    assert first["score"] >= 0.5
