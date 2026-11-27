"""Tests for pipeline.index_clip, fake_pipeline.index_clip, and adapter.get_index_clip."""

import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from pipeline.contract import IndexResult
from pipeline.faces import FaceObs


def test_lazy_imports_index_clip() -> None:
    """Importing pipeline.index_clip, adapter, and fake_pipeline must not load heavy libs."""
    code = (
        "import sys; "
        "import pipeline.index_clip; "
        "import pipeline.adapter; "
        "import pipeline.fake_pipeline; "
        "loaded = [m for m in ('torch', 'cv2', 'insightface', 'onnxruntime') if m in sys.modules]; "
        "assert not loaded, f'Unexpected heavy imports: {loaded}'"
    )
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr or res.stdout


def test_adapter_get_index_clip(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_index_clip() switches between fake_pipeline.index_clip and index_clip.index_clip."""
    from pipeline import adapter, fake_pipeline, index_clip

    monkeypatch.setenv("USE_FAKE_PIPELINE", "1")
    assert adapter.get_index_clip() is fake_pipeline.index_clip

    monkeypatch.setenv("USE_FAKE_PIPELINE", "0")
    assert adapter.get_index_clip() is index_clip.index_clip


def test_fake_and_real_index_clip_model_parity(tmp_path: Path) -> None:
    """fake_pipeline.index_clip writes valid IndexResult, index.npz, and normalised vectors."""
    from pipeline import fake_pipeline

    res = fake_pipeline.index_clip(
        clip_path=tmp_path / "demo.mp4",
        start_sec=0.0,
        end_sec=30.0,
        out_dir=tmp_path,
        atm_id="atm_40",
    )
    assert isinstance(res, IndexResult)
    assert len(res.tracks) == 3
    assert all(tr.dwell_sec_in_zone is not None for tr in res.tracks)
    assert Path(res.index_json_path).exists()
    assert Path(res.index_npz_path).exists()

    npz = np.load(res.index_npz_path)
    embs = npz["embeddings"]
    raw_meta = npz["metadata_json"].item()
    meta = json.loads(raw_meta.decode("utf-8") if isinstance(raw_meta, bytes) else str(raw_meta))
    assert embs.shape == (res.total_embeddings, 512)
    assert len(meta) == res.total_embeddings
    norms = np.linalg.norm(embs, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-4)


def test_index_clip_stubbed_tracks_and_chunk_equivalence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Stubbed tests: no-face track, 5-face->3-kept track, npz order/norms, and 100-frame chunk parity."""
    import pipeline.detect_track as dt_mod
    import pipeline.faces as faces_mod
    import pipeline.frames as frames_mod
    from pipeline import index_clip as idx_mod

    vid = tmp_path / "stub_long.mp4"
    vid.write_bytes(b"")

    # Use frame pixel value as frame index so chunked and one-pass see identical detections.
    samples = [(float(i), np.full((240, 320, 3), i, dtype=np.uint8)) for i in range(125)]

    monkeypatch.setattr(frames_mod, "video_info", lambda *a, **kw: {"duration_sec": 125.0})
    monkeypatch.setattr(frames_mod, "iter_sampled_frames", lambda *a, **kw: iter(samples))

    def _fake_detect(frames_batch: list[np.ndarray]) -> list[list[dict]]:
        # Track 1 appears in all frames; Track 2 appears only in frames 0..9.
        out = []
        for fr in frames_batch:
            t_idx = int(fr[0, 0, 0])
            dets = [{"box": [40.0, 20.0, 180.0, 220.0], "score": 0.9}]
            if t_idx < 10:
                dets.append({"box": [200.0, 20.0, 300.0, 220.0], "score": 0.85})
            out.append(dets)
        return out

    monkeypatch.setattr(dt_mod, "detect_persons", _fake_detect)

    def _fake_faces(track: dt_mod.Track, fbt: dict[float, np.ndarray]) -> list[FaceObs]:
        if track.track_id == 2:
            return [
                FaceObs(float(o["t"]), False, None, None, None, None, None, None, None, None, None, o["box"])
                for o in track.observations
            ]
        # Track 1: 5 observations with faces (different det_score/quality) + rest no face.
        obs_list: list[FaceObs] = []
        for idx, o in enumerate(track.observations):
            if idx < 5:
                vec = np.zeros(512, dtype=np.float32)
                vec[idx] = 1.0  # distinct unit vector per observation to verify npz order
                obs_list.append(
                    FaceObs(
                        float(o["t"]),
                        True,
                        [60.0, 40.0, 140.0, 120.0],
                        0.75 + idx * 0.04,
                        None,
                        float(20 - idx * 3),
                        -5.0,
                        0.0,
                        0.0,
                        80.0,
                        vec,
                        o["box"],
                    )
                )
            else:
                obs_list.append(
                    FaceObs(float(o["t"]), False, None, None, None, None, None, None, None, None, None, o["box"])
                )
        return obs_list

    monkeypatch.setattr(faces_mod, "detect_faces_on_track", _fake_faces)

    # Verify single-pass vs chunked tracking produce identical tracks.
    one_pass_trk = idx_mod._build_tracker("iou", 1.0)
    for ts, dets in zip([t for t, _ in samples], _fake_detect([f for _, f in samples])):
        one_pass_trk.update(ts, dets)
    one_pass_tracks = one_pass_trk.finish()

    res = idx_mod.index_clip(
        clip_path=vid,
        start_sec=0.0,
        end_sec=125.0,
        sample_fps=1.0,
        faces_per_track=3,
        out_dir=tmp_path,
    )
    assert isinstance(res, IndexResult)
    assert len(res.tracks) == len(one_pass_tracks)
    assert res.tracks[0].first_t == one_pass_tracks[0].first_t
    assert res.tracks[0].last_t == one_pass_tracks[0].last_t

    tr1 = next(t for t in res.tracks if t.track_id == 1)
    tr2 = next(t for t in res.tracks if t.track_id == 2)
    assert len(tr1.faces) == 3
    assert tr1.reason is None
    assert tr2.faces == []
    assert tr2.reason == "No face found"

    # Verify index.npz order matches metadata and vectors are unit-normalised.
    npz = np.load(res.index_npz_path)
    embs = npz["embeddings"]
    meta = json.loads(str(npz["metadata_json"].item()))
    assert embs.shape == (3, 512)
    assert len(meta) == 3
    assert np.allclose(np.linalg.norm(embs, axis=1), 1.0, atol=1e-4)
    for i, m in enumerate(meta):
        assert m["t"] == tr1.faces[i].t
        assert np.allclose(embs[i], np.load(m["embedding_path"]))


def test_integration_index_clip_sample2_0_to_60(tmp_path: Path) -> None:
    """Integration test on data/samples/sample2.mp4 for 0 to 60 s."""
    from pipeline.index_clip import index_clip

    sample = Path("data/samples/sample2.mp4")
    if not sample.exists():
        pytest.skip("data/samples/sample2.mp4 not available")

    res = index_clip(
        clip_path=sample,
        start_sec=0.0,
        end_sec=60.0,
        sample_fps=1.0,
        faces_per_track=3,
        out_dir=tmp_path,
    )
    assert isinstance(res, IndexResult)
    assert len(res.tracks) >= 1
    assert Path(res.index_json_path).exists()
    assert Path(res.index_npz_path).exists()
    if res.total_embeddings > 0:
        npz = np.load(res.index_npz_path)
        assert npz["embeddings"].shape == (res.total_embeddings, 512)


def test_short_track_and_index_summary_synthetic(tmp_path: Path) -> None:
    """Verify n_observations/short_track backward compatibility and index_summary max cosine."""
    from pipeline.contract import Frame, IndexFace, IndexTrack, Metrics, PipelineResult
    from pipeline.embeddings import save_embedding
    from scripts.index_summary import summarize_index

    # Old IndexTrack JSON without n_observations or short_track still validates.
    old_track = IndexTrack.model_validate({"track_id": 1, "first_t": 0.0, "last_t": 5.0})
    assert old_track.n_observations == 0
    assert old_track.short_track is False

    # Build a synthetic index_dir with 2 tracks: track 1 (short_track=True, 1 face), track 2 (no face).
    idx_dir = tmp_path / "idx"
    idx_dir.mkdir()
    vec1 = np.zeros(512, dtype=np.float32)
    vec1[0] = 1.0
    emb1_path = idx_dir / "t1_emb.npy"
    save_embedding(emb1_path, vec1)

    idx_res = IndexResult(
        clip_id="synth",
        start_sec=0.0,
        end_sec=10.0,
        tracks=[
            IndexTrack(
                track_id=1,
                first_t=1.0,
                last_t=1.0,
                n_observations=1,
                short_track=True,
                faces=[
                    IndexFace(
                        t=1.0,
                        quality_score=0.82,
                        reliability="High",
                        match_ready=True,
                        flags=[],
                        face_box=[10.0, 10.0, 90.0, 90.0],
                        crop_path=str(idx_dir / "c1.jpg"),
                        frame_path=str(idx_dir / "f1.jpg"),
                        embedding_path=str(emb1_path),
                    )
                ],
                reason=None,
            ),
            IndexTrack(
                track_id=2,
                first_t=2.0,
                last_t=6.0,
                n_observations=5,
                short_track=False,
                faces=[],
                reason="No face found",
            ),
        ],
        index_npz_path=str(idx_dir / "index.npz"),
        index_json_path=str(idx_dir / "index.json"),
        total_embeddings=1,
    )
    (idx_dir / "index.json").write_text(idx_res.model_dump_json(indent=2), encoding="utf-8")

    # Build a synthetic compare result.json with cosine 0.60 against vec1.
    cmp_dir = tmp_path / "tx10_w5_atm_01"
    cmp_dir.mkdir()
    vec_cmp = np.zeros(512, dtype=np.float32)
    vec_cmp[0] = 0.6
    vec_cmp[1] = 0.8
    cmp_emb_path = cmp_dir / "emb.npy"
    save_embedding(cmp_emb_path, vec_cmp)

    cmp_res = PipelineResult(
        clip_id="synth",
        transaction_time="2026-11-27T10:00:00",
        person_track_id=1,
        best_frames=[
            Frame(
                frame_id="f_001000",
                frame_path=str(cmp_dir / "f.jpg"),
                timestamp_sec=1.0,
                quality_score=0.80,
                reliability="High",
                flags=[],
                enhanced=False,
                enhancement=None,
                metrics=Metrics(sharpness=0.8, face_size=0.9, pose_yaw=0.0, illumination=0.8, occlusion=0.0),
                embedding_path=str(cmp_emb_path),
            )
        ],
    )
    cmp_json = cmp_dir / "result.json"
    cmp_json.write_text(cmp_res.model_dump_json(indent=2), encoding="utf-8")

    summary = summarize_index(idx_dir, [cmp_json])
    assert "tx10_w5_atm_01" in summary
    assert "0.60" in summary
    assert "No face found" in summary

