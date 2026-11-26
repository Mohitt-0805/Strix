"""Tests for pipeline/frames.py using a synthetic 10 s 25 fps testsrc2 video."""

from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from pipeline.frames import iter_sampled_frames, video_info
from scripts.make_test_video import make_test_video


def test_import_frames_does_not_import_cv2() -> None:
    """Importing pipeline.frames must not eagerly import cv2 at module load time."""
    proc = subprocess.run(
        [sys.executable, "-c", "import sys, pipeline.frames; assert 'cv2' not in sys.modules"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not installed on PATH",
)
def test_extract_2_to_6s_at_2fps(tmp_path: Path) -> None:
    """Extract 2 to 6 s at 2 fps and verify timestamps and frame alignment."""
    video_path = make_test_video(tmp_path / "testsrc2_10s_25fps.mp4")
    info = video_info(video_path)

    assert info["fps"] == pytest.approx(25.0, abs=0.1)
    assert info["width"] == 640
    assert info["height"] == 360
    assert info["display_width"] == 640
    assert info["display_height"] == 360
    assert info["duration_sec"] == pytest.approx(10.0, abs=0.2)

    samples = list(iter_sampled_frames(video_path, start_sec=2.0, end_sec=6.0, sample_fps=2.0))
    expected_times = [2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0]
    one_source_frame = 1.0 / info["fps"]

    assert len(samples) == len(expected_times)
    for (ts, frame), exp_ts in zip(samples, expected_times):
        assert abs(ts - exp_ts) <= one_source_frame + 1e-6
        assert frame.shape == (360, 640, 3)
        # Verify the sampled frame number is within one source frame of exp_ts * 25.
        frame_num = round(ts * 25)
        assert abs(frame_num - exp_ts * 25) <= 1.0
