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
    """Importing pipeline.run_pipeline and pipeline.adapter must not load heavy libs."""
    code = (
        "import sys; "
        "import pipeline.run_pipeline; "
        "import pipeline.adapter; "
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

    res = run_pipeline.run(
        clip_path="demo_clip.mp4",
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
    res_no_person = run_pipeline.run(
        clip_path="no_person.mp4",
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
    res_no_face = run_pipeline.run(
        clip_path="no_face.mp4",
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

    res1 = run_pipeline.run(
        clip_path="multi.mp4",
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
        clip_path="multi.mp4",
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

