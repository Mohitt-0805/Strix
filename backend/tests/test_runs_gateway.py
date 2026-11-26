"""Phase 4 acceptance tests: pipeline gateway, jobs, runs, results, fake assets."""

import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app.config import HUMAN_VERIFICATION_NOTICE, Settings
from backend.app.db import create_db_engine, create_session_factory, init_db
from backend.app.main import create_app
from backend.app.models import AuditLog, Clip, FrameRecord, Run, User
from backend.app.security import hash_password
from backend.app.services.fake_assets import generate_person_embedding, person_key_from_filename
from backend.tests.conftest import TEST_JWT_SECRET
from pipeline.contract import Frame, Metrics, PipelineResult


def _make_clip_bytes(
    tmp_path: Path, name: str = "A_clip1.mp4", creation_time_utc: str = "2026-11-26T10:00:00Z"
) -> bytes:
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
            "testsrc=duration=5:size=320x240:rate=10",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-metadata",
            f"creation_time={creation_time_utc}",
            str(dest),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        pytest.skip(f"ffmpeg failed: {proc.stderr}")
    return dest.read_bytes()


def _create_auth_headers(client: TestClient, username: str = "inv_run") -> dict[str, str]:
    password = "RunUserPass123!"
    with client.app.state.session_factory() as db:
        db.add(
            User(
                username=username,
                password_hash=hash_password(password),
                role="investigator",
                full_name="Run Tester",
                active=True,
            )
        )
        db.commit()
    resp = client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _upload_sample(
    client: TestClient, headers: dict[str, str], filename: str, raw_bytes: bytes
) -> dict:
    resp = client.post(
        "/clips",
        headers=headers,
        data={"atm_id": "ATM-101"},
        files={"file": (filename, raw_bytes, "video/mp4")},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _poll_run(
    client: TestClient, headers: dict[str, str], run_id: int, timeout_sec: float = 10.0
) -> dict:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        resp = client.get(f"/runs/{run_id}", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        if body["status"] in {"done", "failed"}:
            return body
        time.sleep(0.05)
    raise AssertionError(f"Run {run_id} did not complete within {timeout_sec}s")


def test_process_202_status_flow_fake_assets_and_signed_media(
    client: TestClient, tmp_path: Path
) -> None:
    """POST /clips/{id}/process returns 202 -> queued -> done with real files & URLs."""
    raw = _make_clip_bytes(tmp_path, "A_clip1.mp4")
    headers = _create_auth_headers(client)
    clip = _upload_sample(client, headers, "A_clip1.mp4", raw)
    clip_id = clip["id"]

    proc_resp = client.post(
        f"/clips/{clip_id}/process",
        headers=headers,
        json={
            "transaction_time": "2026-11-26T15:30:02",
            "window_sec": 2,
            "sample_fps": 2.0,
            "tracker": "iou",
        },
    )
    assert proc_resp.status_code == 202
    accepted = proc_resp.json()
    run_id = accepted["run_id"]
    assert accepted["status"] in {"queued", "running", "done"}

    final = _poll_run(client, headers, run_id)
    assert final["status"] == "done"
    assert final["result"] is not None

    # GET /clips/{id}/runs and GET /runs/{id}/result
    runs_list = client.get(f"/clips/{clip_id}/runs", headers=headers)
    assert runs_list.status_code == 200
    assert any(r["run_id"] == run_id for r in runs_list.json())

    result_resp = client.get(f"/runs/{run_id}/result", headers=headers)
    assert result_resp.status_code == 200
    res = result_resp.json()
    assert res["pipeline_mode"] == "fake"
    assert res["notice"] == HUMAN_VERIFICATION_NOTICE
    assert res["video_url"].startswith("/files?")
    assert len(res["best_frames"]) == 3

    data_root = client.app.state.settings.resolved_data_dir
    for frame in res["best_frames"]:
        # Paths are normalized relative to DATA_DIR with forward slashes, and files exist.
        assert not Path(frame["frame_path"]).is_absolute()
        assert frame["frame_path"].startswith(f"outputs/{clip_id}/run_{run_id}/")
        assert (data_root / frame["frame_path"]).is_file()
        assert (data_root / frame["crop_path"]).is_file()
        emb_file = data_root / frame["embedding_path"]
        assert emb_file.is_file()
        vec = np.load(emb_file)
        assert vec.shape == (512,)
        assert vec.dtype == np.float32
        assert np.linalg.norm(vec) == pytest.approx(1.0, abs=1e-4)

    # Signed image_url and crop_url work without Authorization header.
    img_resp = client.get(res["best_frames"][0]["image_url"])
    assert img_resp.status_code == 200
    assert img_resp.headers["content-type"] == "image/jpeg"
    assert img_resp.content[:2] == b"\xff\xd8"

    crop_resp = client.get(res["best_frames"][0]["crop_url"])
    assert crop_resp.status_code == 200
    assert crop_resp.content[:2] == b"\xff\xd8"

    # Audit events recorded.
    with client.app.state.session_factory() as db:
        actions = [a.action for a in db.query(AuditLog).all()]
        assert "process_started" in actions
        assert "process_finished" in actions


def test_tx_offset_validation_and_window_cap_422(
    client: TestClient, tmp_path: Path
) -> None:
    """Out-of-range transaction time, missing start time, and >200 frame cap return 422."""
    raw = _make_clip_bytes(tmp_path, "A_clip2.mp4")
    headers = _create_auth_headers(client, username="inv_val")
    clip = _upload_sample(client, headers, "A_clip2.mp4", raw)
    clip_id = clip["id"]

    # Outside duration (15:30:00 + 30s > 5s duration) -> 422 TX_OUT_OF_RANGE with details.
    out_of_range = client.post(
        f"/clips/{clip_id}/process",
        headers=headers,
        json={"transaction_time": "2026-11-26T15:30:30", "window_sec": 2, "sample_fps": 2.0},
    )
    assert out_of_range.status_code == 422
    assert out_of_range.json()["code"] == "TX_OUT_OF_RANGE"
    assert "2026-11-26T15:30:00" in out_of_range.json()["detail"]
    assert "2026-11-26T15:30:30" in out_of_range.json()["detail"]
    assert "duration_sec" in out_of_range.json()["detail"]

    # Window cap exceeded with 1s margin each side:
    # (2 * 49 + 2) * 2.0 = 200.0 (allowed); (2 * 50 + 2) * 2.0 = 204.0 > 200 -> 422.
    margin_cap = client.post(
        f"/clips/{clip_id}/process",
        headers=headers,
        json={"transaction_time": "2026-11-26T15:30:02", "window_sec": 50, "sample_fps": 2.0},
    )
    assert margin_cap.status_code == 422
    assert margin_cap.json()["code"] == "WINDOW_CAP_EXCEEDED"

    allowed_edge = client.post(
        f"/clips/{clip_id}/process",
        headers=headers,
        json={"transaction_time": "2026-11-26T15:30:02", "window_sec": 49, "sample_fps": 2.0},
    )
    assert allowed_edge.status_code == 202
    assert _poll_run(client, headers, allowed_edge.json()["run_id"])["status"] == "done"

    # Clear clip_start_time -> 422 asking for it.
    client.patch(f"/clips/{clip_id}", headers=headers, json={"clip_start_time": None})
    missing_start = client.post(
        f"/clips/{clip_id}/process",
        headers=headers,
        json={"transaction_time": "2026-11-26T15:30:02"},
    )
    assert missing_start.status_code == 422
    assert missing_start.json()["code"] == "CLIP_START_TIME_REQUIRED"


def test_int_and_string_frame_id_and_optional_pipeline_kwargs(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both int and str frame_id are stored as TEXT; optional kwargs work when accepted."""
    raw = _make_clip_bytes(tmp_path, "A_clip3.mp4")
    headers = _create_auth_headers(client, username="inv_str")
    clip = _upload_sample(client, headers, "A_clip3.mp4", raw)
    clip_id = clip["id"]
    client.patch(
        f"/clips/{clip_id}",
        headers=headers,
        json={"zone_polygon_norm": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]]},
    )

    observed_kwargs: dict = {}

    def _custom_run(
        clip_path,
        tx_offset_sec,
        window_sec=10,
        zone_polygon_norm=None,
        progress_cb=None,
    ) -> PipelineResult:
        observed_kwargs["zone_polygon_norm"] = zone_polygon_norm
        if progress_cb:
            progress_cb("detecting", 0.5)
        return PipelineResult(
            clip_id=clip_id,
            transaction_time="2026-11-26T15:30:02",
            person_track_id=None,
            best_frames=[
                Frame(
                    frame_id="f_0010",
                    frame_path="data/outputs/x/f1.jpg",
                    timestamp_sec=1.0,
                    quality_score=0.35,
                    reliability="Low",
                    flags=["blur"],
                    enhanced=False,
                    metrics=Metrics(
                        sharpness=0.3,
                        face_size=40.0,
                        pose_yaw=12.0,
                        illumination=0.4,
                        occlusion=0.2,
                    ),
                    embedding_path="data/outputs/x/e1.npy",
                ),
                Frame(
                    frame_id=42,
                    frame_path="data/outputs/x/f2.jpg",
                    timestamp_sec=2.0,
                    quality_score=0.31,
                    reliability="Low",
                    flags=["low light"],
                    enhanced=False,
                    metrics=Metrics(
                        sharpness=0.25,
                        face_size=36.0,
                        pose_yaw=18.0,
                        illumination=0.3,
                        occlusion=0.3,
                    ),
                    embedding_path="data/outputs/x/e2.npy",
                ),
            ],
            link_confidence="Low",
            link_reason="Only low-quality frames available",
            selection_reason="All candidate frames are Low reliability",
            timings_ms={"total": 12.5},
        )

    import pipeline.adapter as adapter

    monkeypatch.setattr(adapter, "get_run", lambda: _custom_run)

    proc_resp = client.post(
        f"/clips/{clip_id}/process",
        headers=headers,
        json={"transaction_time": "2026-11-26T15:30:02", "window_sec": 2},
    )
    assert proc_resp.status_code == 202
    run_id = proc_resp.json()["run_id"]
    done = _poll_run(client, headers, run_id)
    assert done["status"] == "done"
    assert observed_kwargs["zone_polygon_norm"] == [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]]
    assert done["result"]["show_selection_reason"] is True
    assert done["result"]["selection_reason"] == "All candidate frames are Low reliability"

    with client.app.state.session_factory() as db:
        frame_ids = [
            f.frame_id
            for f in db.query(FrameRecord).filter(FrameRecord.run_id == run_id).all()
        ]
        assert set(frame_ids) == {"f_0010", "42"}


def test_failed_pipeline_stores_error_code(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pipeline exceptions store getattr(exc, 'code', 'PIPELINE_FAILED') without tracebacks."""
    raw = _make_clip_bytes(tmp_path, "A_fail.mp4")
    headers = _create_auth_headers(client, username="inv_fail")
    clip = _upload_sample(client, headers, "A_fail.mp4", raw)
    clip_id = clip["id"]

    class FakePipelineError(RuntimeError):
        code = "ZoneNotFound"

    def _failing_run(clip_path, tx_offset_sec, window_sec=10):
        raise FakePipelineError("ATM zone configuration missing.")

    import pipeline.adapter as adapter

    monkeypatch.setattr(adapter, "get_run", lambda: _failing_run)

    proc = client.post(
        f"/clips/{clip_id}/process",
        headers=headers,
        json={"transaction_time": "2026-11-26T15:30:02", "window_sec": 2},
    )
    run_id = proc.json()["run_id"]
    failed = _poll_run(client, headers, run_id)
    assert failed["status"] == "failed"
    assert failed["error_code"] == "ZoneNotFound"
    assert "ATM zone configuration missing." in failed["error_message"]
    assert "Traceback" not in failed["error_message"]

    res_err = client.get(f"/runs/{run_id}/result", headers=headers)
    assert res_err.status_code == 422
    assert res_err.json()["code"] == "ZoneNotFound"


def test_startup_marks_stale_runs_as_failed(tmp_path: Path) -> None:
    """On startup, queued/running runs from an earlier process become failed/SERVER_RESTARTED."""
    settings = Settings(
        _env_file=None,
        USE_FAKE_PIPELINE=True,
        DATA_DIR=tmp_path / "restart_data",
        JWT_SECRET=TEST_JWT_SECRET,
    )
    engine = create_db_engine(settings.db_path)
    init_db(engine)
    sf = create_session_factory(engine)
    with sf() as db:
        u = User(
            username="u_restart",
            password_hash=hash_password("Pass12345!"),
            role="investigator",
            full_name="Restart User",
            active=True,
        )
        db.add(u)
        db.commit()
        db.refresh(u)

        c = Clip(
            id="clip-restart-1",
            original_filename="a.mp4",
            stored_path="uploads/clip-restart-1/a.mp4",
            sha256="0" * 64,
            size_bytes=100,
            duration_sec=5.0,
            width=320,
            height=240,
            clip_start_time=datetime(2026, 11, 26, 15, 30, 0),
            clip_start_source="user",
            uploaded_by=u.id,
        )
        db.add(c)
        db.commit()

        db.add_all(
            [
                Run(
                    clip_id=c.id,
                    status="queued",
                    stage="queued",
                    transaction_time=datetime(2026, 11, 26, 15, 30, 2),
                    tx_offset_sec=2.0,
                    window_sec=2.0,
                    sample_fps=2.0,
                    tracker="iou",
                    pipeline_mode="fake",
                    created_by=u.id,
                ),
                Run(
                    clip_id=c.id,
                    status="running",
                    stage="processing",
                    transaction_time=datetime(2026, 11, 26, 15, 30, 3),
                    tx_offset_sec=3.0,
                    window_sec=2.0,
                    sample_fps=2.0,
                    tracker="iou",
                    pipeline_mode="fake",
                    created_by=u.id,
                ),
            ]
        )
        db.commit()
    engine.dispose()

    with TestClient(create_app(settings)) as restarted_client:
        with restarted_client.app.state.session_factory() as db:
            runs = db.query(Run).order_by(Run.id.asc()).all()
            assert len(runs) == 2
            for r in runs:
                assert r.status == "failed"
                assert r.error_code == "SERVER_RESTARTED"


def test_two_jobs_run_sequentially(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """max_workers=1 guarantees two queued runs execute one after another, never overlapping."""
    raw = _make_clip_bytes(tmp_path, "A_seq.mp4")
    headers = _create_auth_headers(client, username="inv_seq")
    clip = _upload_sample(client, headers, "A_seq.mp4", raw)
    clip_id = clip["id"]

    intervals: list[tuple[float, float]] = []

    def _slow_run(clip_path, tx_offset_sec, window_sec=10):
        start = time.monotonic()
        time.sleep(0.15)
        end = time.monotonic()
        intervals.append((start, end))
        return PipelineResult(
            clip_id=clip_id,
            transaction_time="2026-11-26T15:30:02",
            person_track_id=1,
            best_frames=[],
            selection_reason="No face detected",
        )

    import pipeline.adapter as adapter

    monkeypatch.setattr(adapter, "get_run", lambda: _slow_run)

    r1 = client.post(
        f"/clips/{clip_id}/process",
        headers=headers,
        json={"transaction_time": "2026-11-26T15:30:02", "window_sec": 2},
    ).json()["run_id"]
    r2 = client.post(
        f"/clips/{clip_id}/process",
        headers=headers,
        json={"transaction_time": "2026-11-26T15:30:03", "window_sec": 2},
    ).json()["run_id"]

    assert _poll_run(client, headers, r1)["status"] == "done"
    assert _poll_run(client, headers, r2)["status"] == "done"
    assert len(intervals) == 2
    assert intervals[0][1] <= intervals[1][0]


def test_unique_absolute_out_dir_per_run_and_duplicate_filename(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gateway passes unique absolute DATA_DIR/outputs/<clip_uuid>/run_<run_id> per run."""
    raw = _make_clip_bytes(tmp_path, "dup_clip.mp4")
    headers = _create_auth_headers(client, username="inv_outdir")
    clip1 = _upload_sample(client, headers, "dup_clip.mp4", raw)
    clip2 = _upload_sample(client, headers, "dup_clip.mp4", raw)

    seen_out_dirs: list[tuple[str, str]] = []

    def _spy_run(clip_path, tx_offset_sec, window_sec=10, out_dir="data/outputs"):
        seen_out_dirs.append((Path(clip_path).parent.name, out_dir))
        return PipelineResult(
            clip_id=Path(clip_path).parent.name,
            transaction_time="2026-11-26T15:30:02",
            person_track_id=1,
            best_frames=[],
            selection_reason="No face detected",
        )

    import pipeline.adapter as adapter

    monkeypatch.setattr(adapter, "get_run", lambda: _spy_run)

    r1a = client.post(
        f"/clips/{clip1['id']}/process",
        headers=headers,
        json={"transaction_time": "2026-11-26T15:30:02", "window_sec": 2},
    ).json()["run_id"]
    r1b = client.post(
        f"/clips/{clip1['id']}/process",
        headers=headers,
        json={"transaction_time": "2026-11-26T15:30:02", "window_sec": 2},
    ).json()["run_id"]
    r2a = client.post(
        f"/clips/{clip2['id']}/process",
        headers=headers,
        json={"transaction_time": "2026-11-26T15:30:02", "window_sec": 2},
    ).json()["run_id"]

    assert _poll_run(client, headers, r1a)["status"] == "done"
    assert _poll_run(client, headers, r1b)["status"] == "done"
    assert _poll_run(client, headers, r2a)["status"] == "done"

    data_root = client.app.state.settings.resolved_data_dir
    expected = [
        str((data_root / "outputs" / clip1["id"] / f"run_{r1a}").resolve()),
        str((data_root / "outputs" / clip1["id"] / f"run_{r1b}").resolve()),
        str((data_root / "outputs" / clip2["id"] / f"run_{r2a}").resolve()),
    ]
    actual = [od for _, od in seen_out_dirs]
    assert actual == expected
    assert all(Path(od).is_absolute() for od in actual)
    assert len(set(actual)) == 3


def test_fake_person_key_embeddings_and_no_heavy_ml_imports() -> None:
    """Same person key yields high cosine similarity; backend imports no heavy ML libs."""
    assert person_key_from_filename("A_clip1.mp4") == "A"
    assert person_key_from_filename("B_clip1.mp4") == "B"

    a1 = generate_person_embedding("A", "run1:f1")
    a2 = generate_person_embedding("A", "run2:f1")
    b1 = generate_person_embedding("B", "run3:f1")
    assert float(a1 @ a2) > 0.9
    assert float(a1 @ b1) < 0.3

    backend_app_dir = Path(__file__).resolve().parents[1] / "app"
    forbidden = ("torch", "cv2", "insightface", "onnxruntime")
    for py_file in backend_app_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        for mod in forbidden:
            assert f"import {mod}" not in content, f"{mod} imported in {py_file}"
            assert f"from {mod}" not in content, f"{mod} imported in {py_file}"
