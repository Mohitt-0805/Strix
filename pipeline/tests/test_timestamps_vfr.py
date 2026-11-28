"""Tests for Phase 13b: true ffprobe PTS reader, cache, and drift tie-breaking."""

from bisect import bisect_left
from pathlib import Path
import statistics
import subprocess

import pytest

from pipeline.frames import _load_frame_pts, _pts_cache_path, iter_sampled_frames
from scripts.check_timestamps import measure_drift
from scripts.pts_truth import read_true_pts


def _ffmpeg(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, f"ffmpeg failed: {' '.join(cmd)}\n{proc.stderr}"


def _assert_matches_truth(video_path: Path, start_sec: float, end_sec: float, sample_fps: float) -> None:
    truth = read_true_pts(video_path)
    pts = truth["pts"]
    med_gap = float(truth["median_gap"])
    assert pts and med_gap > 0.0

    samples = list(iter_sampled_frames(video_path, start_sec, end_sec, sample_fps=sample_fps))
    assert len(samples) >= 4
    tol = 0.5 * med_gap + 1e-6

    for ts, _ in samples:
        idx = bisect_left(pts, ts)
        candidates = []
        if idx > 0:
            candidates.append(pts[idx - 1])
        if idx < len(pts):
            candidates.append(pts[idx])
        err = min(abs(ts - c) for c in candidates)
        assert err <= tol, f"ts={ts:.4f} differs from nearest PTS {candidates} by {err:.4f}s > {tol:.4f}s"


def test_reader_matches_ffprobe_truth_cfr_vfr_offset_and_4fps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reader timestamps match ffprobe PTS within 0.5 * median_gap across CFR, VFR, offset, and 4fps."""
    import pipeline.frames as frames_mod

    cache_dir = tmp_path / "pts_cache"
    monkeypatch.setattr(frames_mod, "_PTS_CACHE_DIR", cache_dir)

    # 1. Constant 10 fps clip.
    cfr = tmp_path / "cfr.mp4"
    _ffmpeg([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=10:duration=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(cfr),
    ])
    _assert_matches_truth(cfr, 0.0, 2.0, 2.0)

    # Second read uses cached JSON without calling ffprobe for PTS again.
    expected_cache = _pts_cache_path(cfr)
    assert expected_cache.exists()
    orig_run = subprocess.run
    monkeypatch.setattr(
        frames_mod.subprocess,
        "run",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("unexpected ffprobe"))
        if any("-show_frames" in str(x) or "-show_packets" in str(x) for x in (a[0] if a else []))
        else orig_run(*a, **kw),
    )
    assert _load_frame_pts(cfr) is not None
    monkeypatch.undo()
    monkeypatch.setattr(frames_mod, "_PTS_CACHE_DIR", cache_dir)

    # 2. VFR clip with dropped frames.
    vfr = tmp_path / "vfr_drop.mp4"
    _ffmpeg([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=10:duration=2",
        "-vf", r"select=not(eq(n\,5)+eq(n\,6)+eq(n\,10)+eq(n\,11))", "-fps_mode", "vfr",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(vfr),
    ])
    _assert_matches_truth(vfr, 0.0, 2.0, 2.0)

    # 3. Nonzero start_time via -output_ts_offset 10.
    offset = tmp_path / "offset.mp4"
    _ffmpeg([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=10:duration=2",
        "-output_ts_offset", "10", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(offset),
    ])
    offset_truth = read_true_pts(offset)
    assert float(offset_truth["first_pts"]) >= 9.9
    _assert_matches_truth(offset, 10.0, 12.0, 2.0)

    # 4. Low-fps 4 fps clip.
    low4 = tmp_path / "low_4fps.mp4"
    _ffmpeg([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=4:duration=3",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(low4),
    ])
    _assert_matches_truth(low4, 0.0, 3.0, 2.0)


def test_measure_drift_prefers_zero_offset_on_static_frames(tmp_path: Path) -> None:
    """Static identical frames must tie-break to 0.00s offset instead of negative offsets."""
    static_vid = tmp_path / "static_4fps.mp4"
    _ffmpeg([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=gray:s=160x120:r=4:d=5",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(static_vid),
    ])

    rows = measure_drift(static_vid, [2.5], search_sec=1.5)
    assert len(rows) == 1
    assert rows[0]["best_offset"] == 0.0
    assert rows[0]["drifted"] is False


def test_pts_loader_fallback_when_ffprobe_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_load_frame_pts returns None cleanly if ffprobe raises, allowing fallback."""
    import pipeline.frames as frames_mod

    dummy = tmp_path / "dummy.mp4"
    dummy.write_bytes(b"not a video")
    monkeypatch.setattr(frames_mod, "_PTS_CACHE_DIR", tmp_path / "pts_cache")
    assert _load_frame_pts(dummy) is None
