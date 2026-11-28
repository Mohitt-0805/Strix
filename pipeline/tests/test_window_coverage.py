"""Tests for Phase 8h: adaptive sampling, coverage verification, and non-silent truncation."""

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from pipeline.contract import IndexResult, PipelineResult
from pipeline.errors import InvalidArgumentError
from pipeline.link_transaction import LinkResult


def _stub_run_env(monkeypatch: pytest.MonkeyPatch, duration_sec: float = 300.0) -> list[float]:
    """Stub frames, detector, tracker, linker, and zone so run() executes fast in memory."""
    import pipeline.detect_track as dt_mod
    import pipeline.frames as frames_mod
    import pipeline.link_transaction as link_mod

    seen_fps: list[float] = []
    frame = np.full((64, 64, 3), 120, dtype=np.uint8)

    def _fake_iter(path: Any, start_sec: float, end_sec: float, sample_fps: float, max_frames: int = 200):
        seen_fps.append(float(sample_fps))
        step = 1.0 / float(sample_fps)
        t = float(start_sec)
        count = 0
        while t <= float(end_sec) + 1e-9 and (max_frames is None or count < max_frames):
            yield (round(t, 4), frame)
            t += step
            count += 1

    monkeypatch.setattr(frames_mod, "video_info", lambda *a, **kw: {"duration_sec": duration_sec})
    monkeypatch.setattr(frames_mod, "iter_sampled_frames", _fake_iter)
    monkeypatch.setattr(dt_mod, "detect_persons", lambda batch: [[] for _ in batch])
    monkeypatch.setattr(
        link_mod,
        "load_zone",
        lambda atm_id: {"polygon": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]},
    )
    monkeypatch.setattr(
        link_mod,
        "link_transaction",
        lambda *a, **kw: LinkResult(
            chosen_track_id=None,
            confidence="Low",
            reason="No track in zone",
            track_count_in_window=0,
            ranking=[],
        ),
    )
    return seen_fps


def test_long_window_lowers_fps_and_covers_end(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """window=60 at 2 fps lowers effective_sample_fps < 2.0, warns, and reaches window end."""
    from pipeline import run_pipeline

    seen_fps = _stub_run_env(monkeypatch, duration_sec=300.0)
    vid = tmp_path / "long_clip.mp4"
    vid.write_bytes(b"")

    events: list[dict[str, Any]] = []
    res = run_pipeline.run(
        clip_path=vid,
        tx_offset_sec=155.0,
        window_sec=60.0,
        sample_fps=2.0,
        atm_id="atm_155",
        transaction_time="2026-11-28T12:00:00",
        out_dir=tmp_path,
        progress_cb=events.append,
    )

    assert isinstance(res, PipelineResult)
    assert res.requested_sample_fps == 2.0
    assert res.effective_sample_fps is not None
    assert 0.5 <= res.effective_sample_fps < 2.0
    assert seen_fps == [res.effective_sample_fps]
    assert len(res.warnings) == 1
    assert "sampled at" in res.warnings[0].lower()
    assert res.coverage_start_sec is not None and res.coverage_start_sec <= 95.0
    assert res.coverage_end_sec is not None and res.coverage_end_sec >= 215.0

    frame_msgs = [e["message"] for e in events if e["stage"] == "frames"]
    assert any("sampled at" in msg.lower() for msg in frame_msgs)
    fracs = [float(e["fraction"]) for e in events]
    assert fracs == sorted(fracs)


def test_short_window_keeps_fps_and_has_no_warning(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Short window=6 at 2 fps leaves effective_sample_fps unchanged with empty warnings."""
    from pipeline import run_pipeline

    seen_fps = _stub_run_env(monkeypatch, duration_sec=300.0)
    vid = tmp_path / "short_clip.mp4"
    vid.write_bytes(b"")

    res = run_pipeline.run(
        clip_path=vid,
        tx_offset_sec=155.0,
        window_sec=6.0,
        sample_fps=2.0,
        atm_id="atm_155",
        transaction_time="2026-11-28T12:00:00",
        out_dir=tmp_path,
    )

    assert res.requested_sample_fps == 2.0
    assert res.effective_sample_fps == 2.0
    assert seen_fps == [2.0]
    assert res.warnings == []
    assert res.coverage_start_sec is not None and res.coverage_start_sec <= 149.0
    assert res.coverage_end_sec is not None and res.coverage_end_sec >= 161.0


def test_window_below_min_fps_raises_with_max_windows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A window requiring effective_fps < 0.5 raises InvalidArgumentError naming both limits."""
    from pipeline import run_pipeline

    _stub_run_env(monkeypatch, duration_sec=600.0)
    vid = tmp_path / "huge_clip.mp4"
    vid.write_bytes(b"")

    with pytest.raises(InvalidArgumentError) as exc_info:
        run_pipeline.run(
            clip_path=vid,
            tx_offset_sec=250.0,
            window_sec=210.0,
            sample_fps=2.0,
            transaction_time="2026-11-28T12:00:00",
            out_dir=tmp_path,
        )

    msg = str(exc_info.value)
    assert "48.75" in msg
    assert "198.5" in msg


def test_incomplete_coverage_adds_warning(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """If sampled timestamps stop early before window end, a coverage warning is added."""
    import pipeline.frames as frames_mod
    from pipeline import run_pipeline

    _stub_run_env(monkeypatch, duration_sec=300.0)
    frame = np.full((64, 64, 3), 120, dtype=np.uint8)
    monkeypatch.setattr(
        frames_mod,
        "iter_sampled_frames",
        lambda *a, **kw: iter([(149.0, frame), (150.0, frame), (151.0, frame)]),
    )

    vid = tmp_path / "truncated_clip.mp4"
    vid.write_bytes(b"")
    res = run_pipeline.run(
        clip_path=vid,
        tx_offset_sec=155.0,
        window_sec=6.0,
        sample_fps=2.0,
        transaction_time="2026-11-28T12:00:00",
        out_dir=tmp_path,
    )

    assert res.coverage_start_sec == 149.0
    assert res.coverage_end_sec == 151.0
    assert any("before window end" in w.lower() for w in res.warnings)


def test_fake_pipeline_populates_coverage_and_limits(tmp_path: Path) -> None:
    """fake_pipeline.run() and index_clip() fill new fields and enforce limits."""
    from pipeline import fake_pipeline

    events: list[dict[str, Any]] = []
    long_res = fake_pipeline.run(
        clip_path="demo.mp4",
        tx_offset_sec=155.0,
        window_sec=60.0,
        sample_fps=2.0,
        progress_cb=events.append,
    )
    assert long_res.requested_sample_fps == 2.0
    assert long_res.effective_sample_fps is not None and long_res.effective_sample_fps < 2.0
    assert len(long_res.warnings) == 1
    assert long_res.coverage_start_sec == 95.0
    assert long_res.coverage_end_sec == 215.0
    assert any(e["stage"] == "frames" and "sampled at" in e["message"].lower() for e in events)

    short_res = fake_pipeline.run(
        clip_path="demo.mp4",
        tx_offset_sec=155.0,
        window_sec=6.0,
        sample_fps=2.0,
    )
    assert short_res.effective_sample_fps == 2.0
    assert short_res.warnings == []

    with pytest.raises(InvalidArgumentError):
        fake_pipeline.run(clip_path="demo.mp4", tx_offset_sec=250.0, window_sec=210.0, sample_fps=2.0)

    with pytest.raises(InvalidArgumentError):
        fake_pipeline.index_clip(
            clip_path=tmp_path / "demo.mp4",
            start_sec=0.0,
            end_sec=100.0,
            max_seconds=40.0,
            out_dir=tmp_path,
        )

    trunc_res = fake_pipeline.index_clip(
        clip_path=tmp_path / "demo.mp4",
        start_sec=10.0,
        end_sec=100.0,
        max_seconds=40.0,
        allow_truncate=True,
        out_dir=tmp_path,
    )
    assert isinstance(trunc_res, IndexResult)
    assert trunc_res.end_sec == 50.0
    assert trunc_res.requested_sample_fps == 1.0
    assert trunc_res.effective_sample_fps == 1.0
    assert trunc_res.coverage_start_sec == 10.0
    assert trunc_res.coverage_end_sec == 50.0
    assert any("50.0" in w and "truncated" in w.lower() for w in trunc_res.warnings)


def test_real_index_clip_max_seconds_raise_and_allow_truncate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Real index_clip raises past max_seconds by default, or truncates with warning when allowed."""
    import pipeline.detect_track as dt_mod
    import pipeline.frames as frames_mod
    from pipeline import index_clip as idx_mod

    vid = tmp_path / "long_idx.mp4"
    vid.write_bytes(b"")
    frame = np.full((64, 64, 3), 100, dtype=np.uint8)

    monkeypatch.setattr(frames_mod, "video_info", lambda *a, **kw: {"duration_sec": 1000.0})
    monkeypatch.setattr(
        frames_mod,
        "iter_sampled_frames",
        lambda p, s, e, fps, max_frames=None: iter([(float(s), frame), (float(e), frame)]),
    )
    monkeypatch.setattr(dt_mod, "detect_persons", lambda batch: [[] for _ in batch])

    with pytest.raises(InvalidArgumentError):
        idx_mod.index_clip(
            clip_path=vid,
            start_sec=10.0,
            end_sec=90.0,
            max_seconds=30.0,
            out_dir=tmp_path,
        )

    res = idx_mod.index_clip(
        clip_path=vid,
        start_sec=10.0,
        end_sec=90.0,
        max_seconds=30.0,
        allow_truncate=True,
        out_dir=tmp_path,
    )
    assert res.end_sec == 40.0
    assert res.coverage_start_sec == 10.0
    assert res.coverage_end_sec == 40.0
    assert res.requested_sample_fps == 1.0
    assert res.effective_sample_fps == 1.0
    assert any("40.0" in w and "truncated" in w.lower() for w in res.warnings)
