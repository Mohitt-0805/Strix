"""Tests for demo_pack caching, relative paths, and lazy imports."""

import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from pipeline.contract import Frame, IndexFace, IndexResult, IndexTrack, Metrics, PipelineResult


def test_adapter_lazy_imports_with_demo_pack_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Importing pipeline.adapter must not load torch or cv2."""
    code = (
        "import sys; "
        "import pipeline.adapter; "
        "loaded = [m for m in ('torch', 'cv2', 'insightface', 'onnxruntime') if m in sys.modules]; "
        "assert not loaded, f'Unexpected heavy imports: {loaded}'"
    )
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr or res.stdout


def test_demo_pack_off_by_default_and_cached_hit_miss(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Cached mode is off by default, serves matching entries when DEMO_PACK_DIR is set, and falls back on miss."""
    from pipeline import adapter, run_pipeline

    monkeypatch.delenv("DEMO_PACK_DIR", raising=False)
    monkeypatch.delenv("USE_FAKE_PIPELINE", raising=False)
    assert adapter.get_run() is run_pipeline.run

    # Build a minimal portable demo_pack with relative paths.
    pack = tmp_path / "demo_pack"
    case_dir = pack / "c1"
    idx_dir = pack / "clip1" / "index"
    case_dir.mkdir(parents=True)
    idx_dir.mkdir(parents=True)
    (case_dir / "f.jpg").write_bytes(b"jpg")
    (case_dir / "e.npy").write_bytes(b"npy")
    (idx_dir / "f.jpg").write_bytes(b"jpg")
    (idx_dir / "c.jpg").write_bytes(b"jpg")
    (idx_dir / "e.npy").write_bytes(b"npy")
    np.savez(idx_dir / "index.npz", embeddings=np.zeros((0, 512), dtype=np.float32), metadata_json=np.array("[]"))

    res_obj = PipelineResult(
        clip_id="clip1",
        transaction_time="2026-11-27T12:00:00",
        person_track_id=1,
        best_frames=[
            Frame(
                frame_id="f_010000",
                frame_path="c1/f.jpg",
                timestamp_sec=10.0,
                quality_score=0.8,
                reliability="High",
                flags=[],
                enhanced=False,
                enhancement=None,
                metrics=Metrics(sharpness=0.8, face_size=0.9, pose_yaw=0.0, illumination=0.8, occlusion=0.0),
                embedding_path="c1/e.npy",
            )
        ],
    )
    (case_dir / "result.json").write_text(res_obj.model_dump_json(indent=2), encoding="utf-8")

    idx_obj = IndexResult(
        clip_id="clip1",
        start_sec=0.0,
        end_sec=10.0,
        tracks=[
            IndexTrack(
                track_id=1,
                first_t=1.0,
                last_t=2.0,
                faces=[
                    IndexFace(
                        t=1.0,
                        quality_score=0.8,
                        reliability="High",
                        match_ready=True,
                        flags=[],
                        face_box=[0, 0, 10, 10],
                        crop_path="clip1/index/c.jpg",
                        frame_path="clip1/index/f.jpg",
                        embedding_path="clip1/index/e.npy",
                    )
                ],
            )
        ],
        index_npz_path="clip1/index/index.npz",
        index_json_path="clip1/index/index.json",
        total_embeddings=1,
    )
    (idx_dir / "index.json").write_text(idx_obj.model_dump_json(indent=2), encoding="utf-8")

    manifest_data = {
        "cases": [
            {
                "case_id": "c1",
                "clip_name": "clip1.mp4",
                "clip_stem": "clip1",
                "atm_id": "atm_01",
                "tx_sec": 10.0,
                "window_sec": 5.0,
                "result_json": "c1/result.json",
            }
        ],
        "indexes": [
            {
                "clip_name": "clip1.mp4",
                "clip_stem": "clip1",
                "start_sec": 0.0,
                "end_sec": 10.0,
                "index_json": "clip1/index/index.json",
                "index_npz": "clip1/index/index.npz",
            }
        ],
    }
    (pack / "manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")

    # Verify manifest paths are relative.
    assert not Path(manifest_data["cases"][0]["result_json"]).is_absolute()
    assert not Path(res_obj.best_frames[0].frame_path).is_absolute()

    # Verify default is False on models, old JSON, and fake_pipeline.
    assert res_obj.served_from_demo_pack is False
    assert idx_obj.served_from_demo_pack is False
    from pipeline.contract import SearchResult, load_result
    from pipeline import fake_pipeline

    assert SearchResult().served_from_demo_pack is False
    old_sample = load_result(Path("docs/sample_result.json"))
    assert old_sample.served_from_demo_pack is False
    assert fake_pipeline.run("c.mp4", 10.0).served_from_demo_pack is False
    assert fake_pipeline.index_clip("c.mp4", out_dir=tmp_path / "fidx").served_from_demo_pack is False
    assert fake_pipeline.search_with_enhancement(tmp_path, "orig.jpg").served_from_demo_pack is False

    monkeypatch.setenv("DEMO_PACK_DIR", str(pack))
    run_fn = adapter.get_run()
    hit_res = run_fn("any_dir/clip1.mp4", tx_offset_sec=10.0, window_sec=5.0, atm_id="atm_01")
    out_txt = capsys.readouterr().out
    assert "[demo] served from demo_pack" in out_txt
    assert hit_res.served_from_demo_pack is True
    assert hit_res.best_frames[0].frame_path == str(pack / "c1" / "f.jpg")

    idx_fn = adapter.get_index_clip()
    hit_idx = idx_fn("any_dir/clip1.mp4")
    assert "[demo] served from demo_pack" in capsys.readouterr().out
    assert hit_idx.served_from_demo_pack is True
    assert hit_idx.tracks[0].faces[0].crop_path == str(pack / "clip1" / "index" / "c.jpg")

    # Cache miss falls back to real pipeline.run (which raises VideoNotFoundError for missing clip).
    from pipeline.errors import VideoNotFoundError

    with pytest.raises(VideoNotFoundError):
        run_fn(tmp_path / "other.mp4", tx_offset_sec=10.0, window_sec=5.0, atm_id="atm_01")
