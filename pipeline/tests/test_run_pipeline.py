"""Tests for pipeline.run_pipeline, pipeline.adapter, and contract integration."""

from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from pipeline.contract import PipelineResult, load_result
from pipeline.detect_track import Track
from pipeline.faces import FaceObs
from pipeline.link_transaction import LinkResult


def test_lazy_imports_run_pipeline_and_adapter() -> None:
    """Importing run_pipeline, adapter, errors, and fake_pipeline must not load heavy libs."""
    code = (
        "import sys; "
        "import pipeline.run_pipeline; "
        "import pipeline.adapter; "
        "import pipeline.errors; "
        "import pipeline.fake_pipeline; "
        "loaded = [m for m in ('torch', 'cv2', 'insightface', 'onnxruntime') if m in sys.modules]; "
        "assert not loaded, f'Unexpected heavy imports: {loaded}'"
    )
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr or res.stdout


def test_adapter_selects_fake_or_real(monkeypatch: pytest.MonkeyPatch) -> None:
    """adapter.get_run() switches between fake_pipeline.run and run_pipeline.run."""
    from pipeline import adapter, fake_pipeline, run_pipeline

    monkeypatch.setenv("USE_FAKE_PIPELINE", "1")
    assert adapter.get_run() is fake_pipeline.run

    monkeypatch.setenv("USE_FAKE_PIPELINE", "0")
    assert adapter.get_run() is run_pipeline.run


def test_run_with_stubbed_stages_valid_and_edge_cases(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Stubbed stages validate contract, no-person case, and no-face case."""
    import pipeline.detect_track as dt_mod
    import pipeline.faces as faces_mod
    import pipeline.frames as frames_mod
    import pipeline.link_transaction as link_mod
    from pipeline import run_pipeline

    frame = np.full((240, 320, 3), 130, dtype=np.uint8)
    samples = [(10.0, frame), (10.5, frame)]

    monkeypatch.setattr(frames_mod, "iter_sampled_frames", lambda *a, **kw: iter(samples))
    monkeypatch.setattr(frames_mod, "video_info", lambda *a, **kw: {"duration_sec": 30.0})
    monkeypatch.setattr(dt_mod, "detect_persons", lambda frames: [[{"box": [50, 20, 200, 220], "score": 0.9}] for _ in frames])
    monkeypatch.setattr(
        run_pipeline,
        "_run_tracking",
        lambda *a, **kw: [
            Track(
                track_id=3,
                observations=[
                    {"t": 10.0, "box": [50.0, 20.0, 200.0, 220.0], "score": 0.9},
                    {"t": 10.5, "box": [50.0, 20.0, 200.0, 220.0], "score": 0.9},
                ],
            )
        ],
    )
    monkeypatch.setattr(link_mod, "load_zone", lambda atm_id: {"polygon": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]})

    # 1. Valid case with one detected face.
    monkeypatch.setattr(
        link_mod,
        "link_transaction",
        lambda *a, **kw: LinkResult(
            chosen_track_id=3,
            confidence="High",
            reason="linked",
            track_count_in_window=1,
            ranking=[],
        ),
    )
    emb = np.ones(512, dtype=np.float32) / np.sqrt(512.0)
    monkeypatch.setattr(
        faces_mod,
        "detect_faces_on_track",
        lambda tr, fbt: [
            FaceObs(10.0, True, [80.0, 40.0, 160.0, 120.0], 0.9, None, 5.0, -5.0, 0.0, 0.0, 80.0, emb, [50.0, 20.0, 200.0, 220.0]),
            FaceObs(10.5, False, None, None, None, None, None, None, None, None, None, [50.0, 20.0, 200.0, 220.0]),
        ],
    )

    demo_vid = tmp_path / "demo_clip.mp4"
    demo_vid.write_bytes(b"")
    res = run_pipeline.run(
        clip_path=demo_vid,
        tx_offset_sec=10.0,
        window_sec=5.0,
        atm_id="atm_01",
        transaction_time="2026-11-26T12:00:00",
        out_dir=tmp_path,
    )
    assert isinstance(res, PipelineResult)
    assert res.person_track_id == 3
    assert len(res.best_frames) == 1
    assert res.best_frames[0].frame_id == "f_010000"
    assert Path(res.best_frames[0].frame_path).exists()
    assert Path(res.best_frames[0].crop_path or "").exists()
    assert Path(res.best_frames[0].embedding_path).exists()
    loaded = load_result(tmp_path / "demo_clip" / "tx10_w5_atm_01" / "result.json")
    assert loaded.clip_id == "demo_clip"

    # 2. No-person case.
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
    no_person_vid = tmp_path / "no_person.mp4"
    no_person_vid.write_bytes(b"")
    res_no_person = run_pipeline.run(
        clip_path=no_person_vid,
        tx_offset_sec=10.0,
        transaction_time="2026-11-26T12:00:00",
        out_dir=tmp_path,
    )
    assert res_no_person.person_track_id is None
    assert res_no_person.best_frames == []
    assert res_no_person.link_reason == "No track in zone"

    # 3. No-face case.
    monkeypatch.setattr(
        link_mod,
        "link_transaction",
        lambda *a, **kw: LinkResult(
            chosen_track_id=3,
            confidence="High",
            reason="linked",
            track_count_in_window=1,
            ranking=[],
        ),
    )
    monkeypatch.setattr(
        faces_mod,
        "detect_faces_on_track",
        lambda tr, fbt: [
            FaceObs(10.0, False, None, None, None, None, None, None, None, None, None, [50.0, 20.0, 200.0, 220.0]),
        ],
    )
    no_face_vid = tmp_path / "no_face.mp4"
    no_face_vid.write_bytes(b"")
    res_no_face = run_pipeline.run(
        clip_path=no_face_vid,
        tx_offset_sec=10.0,
        transaction_time="2026-11-26T12:00:00",
        out_dir=tmp_path,
    )
    assert res_no_face.person_track_id is None
    assert res_no_face.best_frames == []
    assert res_no_face.selection_reason == "Face not visible"


def test_integration_sample2_atm_155(tmp_path: Path) -> None:
    """Integration test on data/samples/sample2.mp4 for atm_155 tx 155 window 6."""
    from pipeline import run_pipeline

    sample = Path("data/samples/sample2.mp4")
    if not sample.exists():
        pytest.skip("data/samples/sample2.mp4 not available")

    res = run_pipeline.run(
        clip_path=sample,
        tx_offset_sec=155.0,
        window_sec=6.0,
        atm_id="atm_155",
        transaction_time="2026-11-26T12:00:00",
        sample_fps=2.0,
        tracker="iou",
        out_dir=tmp_path,
    )
    assert res.best_frames
    assert res.best_frames[0].match_ready is True

    result_json = tmp_path / "sample2" / "tx155_w6_atm_155" / "result.json"
    assert result_json.exists()
    roundtrip = load_result(result_json)
    assert roundtrip.clip_id == "sample2"

    for fr in roundtrip.best_frames:
        assert fr.timestamp_sec == round(fr.timestamp_sec, 3)
        assert Path(fr.frame_path).exists()
        assert Path(fr.embedding_path).exists()
        if fr.crop_path is not None:
            assert Path(fr.crop_path).exists()


def test_window_margin_exclusion_and_no_folder_collision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Margin frames (tx +/- (w+1)) are excluded, separate tx folders do not collide, and timestamps round to 3 decimals."""
    import pipeline.detect_track as dt_mod
    import pipeline.faces as faces_mod
    import pipeline.frames as frames_mod
    import pipeline.link_transaction as link_mod
    from pipeline import run_pipeline

    frame = np.full((240, 320, 3), 130, dtype=np.uint8)
    tx, win = 20.0, 5.0
    ts_list = [tx - win - 1.0, tx - win, tx + win, tx + win + 1.0]
    samples = [(t, frame) for t in ts_list]

    monkeypatch.setattr(frames_mod, "iter_sampled_frames", lambda *a, **kw: iter(samples))
    monkeypatch.setattr(frames_mod, "video_info", lambda *a, **kw: {"duration_sec": 60.0})
    monkeypatch.setattr(dt_mod, "detect_persons", lambda frames: [[{"box": [50, 20, 200, 220], "score": 0.9}] for _ in frames])
    monkeypatch.setattr(
        run_pipeline,
        "_run_tracking",
        lambda *a, **kw: [
            Track(
                track_id=1,
                observations=[{"t": t, "box": [50.0, 20.0, 200.0, 220.0], "score": 0.9} for t in ts_list],
            )
        ],
    )
    monkeypatch.setattr(link_mod, "load_zone", lambda atm_id: {"polygon": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]})
    monkeypatch.setattr(
        link_mod,
        "link_transaction",
        lambda *a, **kw: LinkResult(chosen_track_id=1, confidence="High", reason="linked", track_count_in_window=1, ranking=[]),
    )
    emb = np.ones(512, dtype=np.float32) / np.sqrt(512.0)

    def _fake_faces(track: Track, fbt: dict[float, np.ndarray]) -> list[FaceObs]:
        return [
            FaceObs(
                float(o["t"]),
                True,
                [80.0, 40.0, 160.0, 120.0],
                0.95,
                None,
                5.0,
                -5.0,
                0.0,
                0.0,
                80.0,
                emb,
                [50.0, 20.0, 200.0, 220.0],
            )
            for o in track.observations
        ]

    monkeypatch.setattr(faces_mod, "detect_faces_on_track", _fake_faces)

    multi_vid = tmp_path / "multi.mp4"
    multi_vid.write_bytes(b"")
    res1 = run_pipeline.run(
        clip_path=multi_vid,
        tx_offset_sec=tx,
        window_sec=win,
        atm_id="atm_01",
        transaction_time="2026-11-26T12:00:00",
        out_dir=tmp_path,
    )
    picked_ts = sorted(fr.timestamp_sec for fr in res1.best_frames)
    assert picked_ts == [tx - win, tx + win]
    for fr in res1.best_frames:
        assert fr.timestamp_sec == round(fr.timestamp_sec, 3)

    # Second run with different tx -> separate folder, first result.json untouched.
    res2 = run_pipeline.run(
        clip_path=multi_vid,
        tx_offset_sec=21.1234,
        window_sec=win,
        atm_id="",
        transaction_time="2026-11-26T12:00:00",
        out_dir=tmp_path,
    )
    dir1 = tmp_path / "multi" / "tx20_w5_atm_01"
    dir2 = tmp_path / "multi" / "tx21p1234_w5_nozone"
    assert (dir1 / "result.json").exists()
    assert (dir2 / "result.json").exists()
    assert res1.clip_id == "multi"
    assert res2.clip_id == "multi"


def test_errors_parity_between_real_and_fake(tmp_path: Path) -> None:
    """run() and fake_pipeline.run() raise the same typed errors for bad arguments."""
    from pipeline import fake_pipeline, run_pipeline
    from pipeline.errors import (
        InvalidArgumentError,
        VideoNotFoundError,
        VideoUnreadableError,
        ZoneNotFoundError,
    )

    missing = tmp_path / "does_not_exist.mp4"
    with pytest.raises(VideoNotFoundError):
        run_pipeline.run(missing, tx_offset_sec=5.0)

    bad_vid = tmp_path / "corrupt.mp4"
    bad_vid.write_bytes(b"not a real mp4")
    with pytest.raises(VideoUnreadableError):
        run_pipeline.run(bad_vid, tx_offset_sec=5.0)

    for fn in (run_pipeline.run, fake_pipeline.run):
        with pytest.raises(InvalidArgumentError):
            fn(bad_vid, tx_offset_sec=5.0, window_sec=0.0)
        with pytest.raises(InvalidArgumentError):
            fn(bad_vid, tx_offset_sec=5.0, sample_fps=-1.0)
        with pytest.raises(InvalidArgumentError):
            fn(bad_vid, tx_offset_sec=-1.0)
        with pytest.raises(InvalidArgumentError):
            fn(bad_vid, tx_offset_sec=5.0, zone_polygon_norm=[[0.1, 0.1], [0.9, 0.9]])
        with pytest.raises(InvalidArgumentError):
            fn(bad_vid, tx_offset_sec=5.0, zone_polygon_norm=[[0.1, 0.1], [1.5, 0.1], [0.5, 0.9]])
        with pytest.raises(ZoneNotFoundError):
            fn(bad_vid, tx_offset_sec=5.0, atm_id="unknown_atm_999")


def test_progress_callback_zone_priority_and_low_margin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """progress_cb is monotonic & resilient; zone_polygon_norm overrides atm_id; link_low_margin is set."""
    import pipeline.detect_track as dt_mod
    import pipeline.faces as faces_mod
    import pipeline.frames as frames_mod
    import pipeline.link_transaction as link_mod
    from pipeline import fake_pipeline, run_pipeline

    vid = tmp_path / "prog.mp4"
    vid.write_bytes(b"")
    frame = np.full((240, 320, 3), 130, dtype=np.uint8)
    samples = [(10.0 + i * 0.5, frame) for i in range(12)]

    monkeypatch.setattr(frames_mod, "iter_sampled_frames", lambda *a, **kw: iter(samples))
    monkeypatch.setattr(frames_mod, "video_info", lambda *a, **kw: {"duration_sec": 30.0})
    monkeypatch.setattr(dt_mod, "detect_persons", lambda frames: [[{"box": [50, 20, 200, 220], "score": 0.9}] for _ in frames])
    monkeypatch.setattr(
        run_pipeline,
        "_run_tracking",
        lambda *a, **kw: [
            Track(
                track_id=2,
                observations=[{"t": t, "box": [50.0, 20.0, 200.0, 220.0], "score": 0.9} for t, _ in samples],
            )
        ],
    )
    monkeypatch.setattr(
        link_mod,
        "link_transaction",
        lambda *a, **kw: LinkResult(
            chosen_track_id=2,
            confidence="Medium",
            reason="tight margin",
            low_margin=True,
            track_count_in_window=2,
            ranking=[],
        ),
    )
    emb = np.ones(512, dtype=np.float32) / np.sqrt(512.0)
    monkeypatch.setattr(
        faces_mod,
        "detect_faces_on_track",
        lambda tr, fbt: [
            FaceObs(float(o["t"]), True, [80.0, 40.0, 160.0, 120.0], 0.9, None, 5.0, -5.0, 0.0, 0.0, 80.0, emb, [50.0, 20.0, 200.0, 220.0])
            for o in tr.observations
        ],
    )

    events: list[dict] = []
    # zone_polygon_norm takes priority over unknown atm_id.
    res = run_pipeline.run(
        clip_path=vid,
        tx_offset_sec=12.0,
        window_sec=5.0,
        atm_id="nonexistent_atm",
        zone_polygon_norm=[[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
        transaction_time="2026-11-26T12:00:00",
        out_dir=tmp_path,
        progress_cb=events.append,
    )
    assert res.link_low_margin is True
    assert events
    fractions = [e["fraction"] for e in events]
    assert fractions == sorted(fractions)
    assert fractions[-1] == 1.0
    stages = {e["stage"] for e in events}
    assert {"frames", "detect_persons", "track", "link", "faces", "quality", "select", "save", "done"}.issubset(stages)

    # Callback exception must be ignored.
    def _boom(_ev: dict) -> None:
        raise RuntimeError("callback failure")

    run_pipeline.run(
        clip_path=vid,
        tx_offset_sec=12.0,
        window_sec=5.0,
        zone_polygon_norm=[[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
        transaction_time="2026-11-26T12:00:00",
        out_dir=tmp_path,
        progress_cb=_boom,
    )

    # fake_pipeline.run also emits progress events.
    fake_events: list[dict] = []
    fake_res = fake_pipeline.run(
        clip_path=vid,
        tx_offset_sec=12.0,
        zone_polygon_norm=[[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
        progress_cb=fake_events.append,
    )
    assert fake_events
    assert fake_events[-1]["stage"] == "done"
    assert fake_res.link_low_margin is False


def test_model_dir_resolution_and_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """_resolve_insightface_root uses MODEL_DIR when populated, else falls back."""
    from pipeline.faces import _resolve_insightface_root

    empty_dir = tmp_path / "empty_models"
    empty_dir.mkdir()
    monkeypatch.setenv("MODEL_DIR", str(empty_dir))
    resolved = _resolve_insightface_root()
    # Falls back to ~/.insightface if buffalo_l is cached there, else empty_dir.
    assert resolved in {"~/.insightface", str(empty_dir)}

    populated = tmp_path / "populated_models"
    (populated / "models" / "buffalo_l").mkdir(parents=True)
    (populated / "models" / "buffalo_l" / "det_10g.onnx").write_bytes(b"stub")
    monkeypatch.setenv("MODEL_DIR", str(populated))
    assert _resolve_insightface_root() == str(populated)


