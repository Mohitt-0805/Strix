"""Phase 6B acceptance tests: clip_indexes, priority queue, auto-index, dual search."""

import logging
import shutil
import subprocess
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app.config import HUMAN_VERIFICATION_NOTICE, Settings
from backend.app.db import create_db_engine, create_session_factory, init_db
from backend.app.main import create_app
from backend.app.models import Clip, ClipIndex, IndexFaceRecord, User
from backend.app.routes.search import SCORE_NOTE, SEARCH_SCOPE
from backend.app.security import hash_password
from backend.tests.conftest import TEST_JWT_SECRET
from pipeline.contract import IndexFace, IndexResult, IndexTrack, PipelineResult
from pipeline.errors import ZoneNotFoundError


def _make_clip_bytes(tmp_path: Path, name: str = "A_idx.mp4") -> bytes:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg not installed on PATH")
    dest = tmp_path / name
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=4:size=320x240:rate=10",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-metadata",
            "creation_time=2026-11-26T10:00:00Z",
            str(dest),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        pytest.skip(f"ffmpeg failed: {proc.stderr}")
    return dest.read_bytes()


def _auth_headers(client: TestClient, username: str = "inv_p6b") -> dict[str, str]:
    pw = "Phase6BPass123!"
    with client.app.state.session_factory() as db:
        existing = db.query(User).filter(User.username == username).first()
        if existing is None:
            db.add(
                User(
                    username=username,
                    password_hash=hash_password(pw),
                    role="investigator",
                    full_name="Phase 6B Tester",
                    active=True,
                )
            )
            db.commit()
    resp = client.post("/auth/login", json={"username": username, "password": pw})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _upload(
    client: TestClient, headers: dict[str, str], filename: str, raw: bytes, *, atm_id: str | None = "atm_demo"
) -> str:
    data = {"atm_id": atm_id} if atm_id is not None else {}
    resp = client.post(
        "/clips",
        headers=headers,
        data=data,
        files={"file": (filename, raw, "video/mp4")},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _poll_index(client: TestClient, headers: dict[str, str], index_id: int) -> dict:
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        body = client.get(f"/indexes/{index_id}", headers=headers).json()
        if body["status"] in {"done", "failed"}:
            return body
        time.sleep(0.05)
    raise AssertionError(f"Index {index_id} did not finish")


def _poll_run(client: TestClient, headers: dict[str, str], run_id: int) -> dict:
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        body = client.get(f"/runs/{run_id}", headers=headers).json()
        if body["status"] in {"done", "failed"}:
            return body
        time.sleep(0.05)
    raise AssertionError(f"Run {run_id} did not finish")


def test_clip_index_flow_range_validation_and_missing_image(
    client: TestClient, tmp_path: Path
) -> None:
    """POST /clips/{id}/index queues 202, populates tracks/faces, enforces 600s, handles missing image."""
    raw = _make_clip_bytes(tmp_path)
    headers = _auth_headers(client, username="inv_idx_flow")
    clip_id = _upload(client, headers, "A_idx_flow.mp4", raw)

    # >600s range returns 422 INDEX_RANGE_TOO_LONG.
    too_long = client.post(
        f"/clips/{clip_id}/index",
        headers=headers,
        json={"start_sec": 0, "end_sec": 601},
    )
    assert too_long.status_code == 422
    assert too_long.json()["code"] == "INDEX_RANGE_TOO_LONG"

    # Unknown atm_id returns 422 ZONE_NOT_FOUND.
    bad_zone = client.post(
        f"/clips/{clip_id}/index",
        headers=headers,
        json={"atm_id": "atm_invalid"},
    )
    assert bad_zone.status_code == 422
    assert bad_zone.json()["code"] == "ZONE_NOT_FOUND"

    # Default empty body starts indexing with end_sec=min(duration, 600).
    accepted = client.post(f"/clips/{clip_id}/index", headers=headers)
    assert accepted.status_code == 202
    index_id = accepted.json()["index_id"]

    detail = _poll_index(client, headers, index_id)
    assert detail["status"] == "done"
    assert detail["progress"] == 1.0
    assert detail["total_embeddings"] == 5
    assert len(detail["tracks"]) == 3
    first_face = detail["tracks"][0]["faces"][0]
    assert first_face["crop_url"].startswith("/files?")
    assert first_face["frame_url"].startswith("/files?")

    listed = client.get(f"/clips/{clip_id}/indexes", headers=headers)
    assert listed.status_code == 200
    assert any(item["index_id"] == index_id for item in listed.json())

    # Delete a crop file on disk -> crop_url becomes null cleanly, no crash.
    data_root = client.app.state.settings.resolved_data_dir
    with client.app.state.session_factory() as db:
        face_row = (
            db.query(IndexFaceRecord)
            .filter(IndexFaceRecord.index_id == index_id)
            .first()
        )
        assert face_row is not None and face_row.crop_rel is not None
        (data_root / face_row.crop_rel).unlink()

    after_unlink = client.get(f"/indexes/{index_id}", headers=headers).json()
    assert after_unlink["tracks"][0]["faces"][0]["crop_url"] is None
    assert after_unlink["tracks"][0]["faces"][0]["frame_url"].startswith("/files?")


def test_auto_index_on_upload(tmp_path: Path) -> None:
    """When AUTO_INDEX_ON_UPLOAD=1, uploading a clip automatically queues and runs an index job."""
    raw = _make_clip_bytes(tmp_path)
    settings = Settings(
        _env_file=None,
        USE_FAKE_PIPELINE=True,
        AUTO_INDEX_ON_UPLOAD=True,
        DATA_DIR=tmp_path / "auto_data",
        JWT_SECRET=TEST_JWT_SECRET,
    )
    with TestClient(create_app(settings)) as auto_client:
        headers = _auth_headers(auto_client, username="inv_auto")
        clip_id = _upload(auto_client, headers, "A_auto.mp4", raw)

        deadline = time.monotonic() + 10.0
        indexes: list[dict] = []
        while time.monotonic() < deadline:
            indexes = auto_client.get(f"/clips/{clip_id}/indexes", headers=headers).json()
            if indexes and indexes[0]["status"] == "done":
                break
            time.sleep(0.05)

        assert len(indexes) == 1
        assert indexes[0]["status"] == "done"
        assert indexes[0]["total_embeddings"] == 5


def test_priority_queue_runs_process_before_waiting_index_jobs(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Process run (priority 0) submitted after waiting index jobs executes ahead of them."""
    raw = _make_clip_bytes(tmp_path)
    headers = _auth_headers(client, username="inv_prio")
    clip_id = _upload(client, headers, "A_prio.mp4", raw)

    started_first = threading.Event()
    release_first = threading.Event()
    execution_order: list[str] = []

    def _mock_index_clip(clip_path, start_sec=0.0, end_sec=None, out_dir="data/outputs", **_kw):
        job_name = Path(out_dir).name
        execution_order.append(f"index:{job_name}")
        if len(execution_order) == 1:
            started_first.set()
            release_first.wait(timeout=5.0)
        from pipeline.fake_pipeline import index_clip as fake_idx

        return fake_idx(clip_path=clip_path, start_sec=start_sec, end_sec=end_sec, out_dir=out_dir)

    def _mock_run(clip_path, tx_offset_sec, window_sec=10, **_kw):
        execution_order.append("run")
        return PipelineResult(
            clip_id=clip_id,
            transaction_time="2026-11-26T15:30:02",
            person_track_id=1,
            best_frames=[],
            selection_reason="No face",
        )

    import pipeline.adapter as adapter

    monkeypatch.setattr(adapter, "get_index_clip", lambda: _mock_index_clip)
    monkeypatch.setattr(adapter, "get_run", lambda: _mock_run)

    # Queue index 1 (starts immediately and blocks on release_first).
    idx1 = client.post(f"/clips/{clip_id}/index", headers=headers).json()["index_id"]
    assert started_first.wait(timeout=5.0)

    # While index 1 is running, queue index 2 (priority 1) and then run 1 (priority 0).
    idx2 = client.post(f"/clips/{clip_id}/index", headers=headers).json()["index_id"]
    run1 = client.post(
        f"/clips/{clip_id}/process",
        headers=headers,
        json={"transaction_time": "2026-11-26T15:30:02", "window_sec": 1},
    ).json()["run_id"]

    # Release index 1 -> priority queue must run 'run' before index 2.
    release_first.set()
    assert _poll_index(client, headers, idx1)["status"] == "done"
    assert _poll_run(client, headers, run1)["status"] == "done"
    assert _poll_index(client, headers, idx2)["status"] == "done"

    assert execution_order == [f"index:index_{idx1}", "run", f"index:index_{idx2}"]


def test_search_across_run_and_index_filters_short_tracks_and_skips_bad_vectors(
    test_settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Search combines runs + indexes, hides short_track by default, respects best_per_clip, and rebuilds."""
    caplog.set_level(logging.WARNING)
    raw = _make_clip_bytes(tmp_path)

    with TestClient(create_app(test_settings)) as client:
        headers = _auth_headers(client, username="inv_dual")
        clip_q = _upload(client, headers, "A_query.mp4", raw)
        clip_other = _upload(client, headers, "B_indexed.mp4", raw)

        # Process clip_q so we have a query frame embedding (142).
        run_q = client.post(
            f"/clips/{clip_q}/process",
            headers=headers,
            json={"transaction_time": "2026-11-26T15:30:02", "window_sec": 1},
        ).json()["run_id"]
        done_q = _poll_run(client, headers, run_q)
        assert done_q["status"] == "done"

        data_root = client.app.state.settings.resolved_data_dir
        q_emb_rel = done_q["result"]["best_frames"][0]["embedding_path"]
        q_vec = np.load(data_root / q_emb_rel)

        # Custom index_clip returning:
        # - Track 1 (normal, 2 faces: one aligned with q_vec, one orthogonal)
        # - Track 2 (short_track=True, 1 face strongly aligned with q_vec)
        # - Track 3 (faceless, reason="No face found")
        def _custom_index(clip_path, out_dir="data/outputs", **_kw):
            out = Path(out_dir)
            out.mkdir(parents=True, exist_ok=True)
            fr1 = out / "f1.jpg"
            cr1 = out / "c1.jpg"
            fr1.write_bytes(b"\xff\xd8\xff\xd9")
            cr1.write_bytes(b"\xff\xd8\xff\xd9")

            emb1 = out / "e1.npy"
            emb2 = out / "e2.npy"
            emb_short = out / "e_short.npy"
            emb_bad_dim = out / "e_bad.npy"

            np.save(emb1, q_vec)
            orth = np.roll(q_vec, 1)
            np.save(emb2, orth)
            np.save(emb_short, q_vec)
            np.save(emb_bad_dim, np.ones(64, dtype=np.float32))

            return IndexResult(
                clip_id=Path(clip_path).stem,
                start_sec=0.0,
                end_sec=4.0,
                total_embeddings=3,
                tracks=[
                    IndexTrack(
                        track_id=1,
                        first_t=0.5,
                        last_t=3.0,
                        n_observations=6,
                        short_track=False,
                        faces=[
                            IndexFace(
                                t=1.0,
                                quality_score=0.9,
                                reliability="High",
                                match_ready=True,
                                flags=["cap"],
                                face_box=[10.0, 10.0, 50.0, 50.0],
                                crop_path=str(cr1),
                                frame_path=str(fr1),
                                embedding_path=str(emb1),
                            ),
                            IndexFace(
                                t=2.5,
                                quality_score=0.7,
                                reliability="Medium",
                                match_ready=True,
                                flags=[],
                                face_box=[12.0, 12.0, 52.0, 52.0],
                                crop_path=str(cr1),
                                frame_path=str(fr1),
                                embedding_path=str(emb2),
                            ),
                        ],
                    ),
                    IndexTrack(
                        track_id=2,
                        first_t=3.2,
                        last_t=3.2,
                        n_observations=1,
                        short_track=True,
                        faces=[
                            IndexFace(
                                t=3.2,
                                quality_score=0.85,
                                reliability="Medium",
                                match_ready=False,
                                flags=["blur"],
                                face_box=[5.0, 5.0, 40.0, 40.0],
                                crop_path=str(cr1),
                                frame_path=str(fr1),
                                embedding_path=str(emb_short),
                            ),
                            # Wrong-dimension vector must be skipped with warning.
                            IndexFace(
                                t=3.4,
                                quality_score=0.5,
                                reliability="Low",
                                match_ready=False,
                                flags=[],
                                face_box=[5.0, 5.0, 40.0, 40.0],
                                crop_path=str(cr1),
                                frame_path=str(fr1),
                                embedding_path=str(emb_bad_dim),
                            ),
                        ],
                    ),
                    IndexTrack(
                        track_id=3,
                        first_t=0.0,
                        last_t=1.0,
                        n_observations=3,
                        short_track=False,
                        faces=[],
                        reason="No face found",
                    ),
                ],
                index_npz_path=str(out / "index.npz"),
                index_json_path=str(out / "index.json"),
            )

        import pipeline.adapter as adapter

        monkeypatch.setattr(adapter, "get_index_clip", lambda: _custom_index)

        # Also index clip_q itself so we verify self-exclusion works for indexed clips too!
        idx_q = client.post(f"/clips/{clip_q}/index", headers=headers).json()["index_id"]
        idx_other = client.post(f"/clips/{clip_other}/index", headers=headers).json()["index_id"]
        assert _poll_index(client, headers, idx_q)["status"] == "done"
        other_detail = _poll_index(client, headers, idx_other)
        assert other_detail["status"] == "done"
        assert "Skipping" in caplog.text

        # Check faceless track and short_track confidence_note in GET /indexes/{id}.
        tracks_by_id = {t["track_id"]: t for t in other_detail["tracks"]}
        assert tracks_by_id[2]["short_track"] is True
        assert "low confidence" in tracks_by_id[2]["confidence_note"]
        assert tracks_by_id[3]["face_count"] == 0
        assert tracks_by_id[3]["reason"] == "No face found"

        # Default search: best_per_clip=True, include_short_tracks=False.
        s1 = client.post(
            "/search",
            headers=headers,
            json={"run_id": run_q, "frame_id": "142", "top_k": 10},
        ).json()
        assert s1["notice"] == HUMAN_VERIFICATION_NOTICE
        assert s1["score_note"] == SCORE_NOTE
        assert s1["scope"] == SEARCH_SCOPE
        assert len(s1["matches"]) == 1
        m0 = s1["matches"][0]
        assert m0["source"] == "index"
        assert m0["clip_id"] == clip_other
        assert m0["track_id"] == 1
        assert m0["short_track"] is False
        assert m0["index_id"] == idx_other
        assert m0["t"] == 1.0

        # best_per_clip=False, include_short_tracks=False -> 2 faces from track 1, none from track 2.
        s2 = client.post(
            "/search",
            headers=headers,
            json={"run_id": run_q, "frame_id": "142", "top_k": 10, "best_per_clip": False},
        ).json()
        assert len(s2["matches"]) == 2
        assert all(not m["short_track"] for m in s2["matches"])

        # include_short_tracks=True -> includes track 2's valid face too (3 faces total from clip_other).
        s3 = client.post(
            "/search",
            headers=headers,
            json={
                "run_id": run_q,
                "frame_id": "142",
                "top_k": 10,
                "best_per_clip": False,
                "include_short_tracks": True,
            },
        ).json()
        assert len(s3["matches"]) == 3
        assert any(m["short_track"] and m["track_id"] == 2 for m in s3["matches"])

    # Restart rebuilds both run and index embeddings from SQLite.
    with TestClient(create_app(test_settings)) as restarted:
        assert restarted.app.state.search_index.count() == 9  # 3 run_q + 3 idx_q + 3 idx_other


def test_index_error_advice_and_startup_marks_stale_index_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Index failure stores typed error_advice; startup marks queued/running ClipIndex SERVER_RESTARTED."""
    settings = Settings(
        _env_file=None,
        USE_FAKE_PIPELINE=True,
        AUTO_INDEX_ON_UPLOAD=False,
        DATA_DIR=tmp_path / "stale_idx_data",
        JWT_SECRET=TEST_JWT_SECRET,
    )
    engine = create_db_engine(settings.db_path)
    init_db(engine)
    sf = create_session_factory(engine)
    with sf() as db:
        u = User(
            username="u_idx_stale",
            password_hash=hash_password("Pass12345!"),
            role="investigator",
            full_name="Stale Tester",
            active=True,
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        c = Clip(
            id="clip-idx-stale",
            original_filename="a.mp4",
            stored_path="uploads/clip-idx-stale/a.mp4",
            sha256="0" * 64,
            size_bytes=100,
            duration_sec=5.0,
            width=320,
            height=240,
            clip_start_source="unknown",
            uploaded_by=u.id,
        )
        db.add(c)
        db.commit()
        db.add(
            ClipIndex(
                clip_id=c.id,
                status="running",
                stage="faces",
                start_sec=0.0,
                end_sec=5.0,
                sample_fps=1.0,
                tracker="iou",
                faces_per_track=3,
                pipeline_mode="fake",
                created_by=u.id,
            )
        )
        db.commit()
    engine.dispose()

    with TestClient(create_app(settings)) as client:
        with client.app.state.session_factory() as db:
            row = db.query(ClipIndex).one()
            assert row.status == "failed"
            assert row.error_code == "SERVER_RESTARTED"

        # Also verify typed error advice on a failing index job.
        raw = _make_clip_bytes(tmp_path)
        headers = _auth_headers(client, username="inv_idx_err")
        clip_id = _upload(client, headers, "A_err.mp4", raw)

        def _failing_idx(**_kw):
            raise ZoneNotFoundError("zone missing")

        import pipeline.adapter as adapter

        monkeypatch.setattr(adapter, "get_index_clip", lambda: _failing_idx)
        idx_id = client.post(f"/clips/{clip_id}/index", headers=headers).json()["index_id"]
        failed = _poll_index(client, headers, idx_id)
        assert failed["status"] == "failed"
        assert failed["error_code"] == "ZONE_NOT_FOUND"
        assert (
            failed["error_advice"]
            == "No ATM zone is stored for this clip, pick a known zone or draw one"
        )
