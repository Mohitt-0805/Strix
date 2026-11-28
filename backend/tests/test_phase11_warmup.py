"""Phase 11 acceptance tests: startup model warmup, /health & /config/public readiness, job gating."""

import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.models import User
from backend.app.security import hash_password
from backend.app.services.jobs import _ERROR_ADVICE_MAP
from backend.tests.conftest import TEST_JWT_SECRET
from pipeline.contract import WarmupResult


def _make_clip_bytes(tmp_path: Path, name: str = "A_p11.mp4") -> bytes:
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


def _auth_headers(client: TestClient, username: str = "inv_p11") -> dict[str, str]:
    pw = "Phase11Pass123!"
    with client.app.state.session_factory() as db:
        db.add(
            User(
                username=username,
                password_hash=hash_password(pw),
                role="investigator",
                full_name="Phase 11 Tester",
                active=True,
            )
        )
        db.commit()
    resp = client.post("/auth/login", json={"username": username, "password": pw})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _wait_warmup_settled(client: TestClient, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get("/health").json()
        if body["warmup"]["state"] != "running":
            return body
        time.sleep(0.02)
    raise AssertionError("Warmup did not settle in time")


def _poll_run(client: TestClient, headers: dict[str, str], run_id: int) -> dict:
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        body = client.get(f"/runs/{run_id}", headers=headers).json()
        if body["status"] in {"done", "failed"}:
            return body
        time.sleep(0.03)
    raise AssertionError(f"Run {run_id} did not finish")


def _poll_index(client: TestClient, headers: dict[str, str], index_id: int) -> dict:
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        body = client.get(f"/indexes/{index_id}", headers=headers).json()
        if body["status"] in {"done", "failed"}:
            return body
        time.sleep(0.03)
    raise AssertionError(f"Index {index_id} did not finish")


def test_fake_warmup_reports_pipeline_ready_true(client: TestClient) -> None:
    """Instant fake warmup completes cleanly and sets pipeline_ready=True on /health & /config/public."""
    health = _wait_warmup_settled(client)
    assert health["pipeline_ready"] is True
    assert health["warmup"]["state"] == "ok"
    assert health["warmup"]["progress"] == 1.0
    assert health["warmup"]["warnings"] == ["fake pipeline"]

    cfg = client.get("/config/public").json()
    assert cfg["pipeline_ready"] is True
    assert cfg["warmup_state"] == "ok"
    assert cfg["warmup"]["state"] == "ok"


def test_blocking_warmup_does_not_block_health_and_gates_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """While warmup blocks on an Event, /health returns immediately with pipeline_ready=False and jobs wait queued."""
    raw = _make_clip_bytes(tmp_path, "A_p11_block.mp4")
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def _blocking_warmup(progress_cb=None):
        nonlocal calls
        calls += 1
        if progress_cb:
            progress_cb({"stage": "warmup", "fraction": 0.4, "message": "Loading person detector"})
        started.set()
        release.wait(timeout=10.0)
        if progress_cb:
            progress_cb({"stage": "warmup", "fraction": 1.0, "message": "Warmup complete"})
        return WarmupResult(
            ok=True,
            loaded={"person_detector": True, "face_model": True, "clip": True},
            providers={"faces": "CPUExecutionProvider", "torch_device": "cpu"},
            timings_ms={"person_detector": 5.0, "face_model": 5.0, "clip": 5.0},
            warnings=[],
            total_ms=15.0,
        )

    import pipeline.adapter as adapter

    monkeypatch.setattr(adapter, "get_warmup", lambda: _blocking_warmup)

    settings = Settings(
        _env_file=None,
        USE_FAKE_PIPELINE=True,
        AUTO_INDEX_ON_UPLOAD=False,
        WARMUP_ON_START=True,
        DATA_DIR=tmp_path / "block_data",
        JWT_SECRET=TEST_JWT_SECRET,
    )
    try:
        with TestClient(create_app(settings)) as c:
            assert started.wait(timeout=2.0)

            # /health and /config/public answer immediately with pipeline_ready=False.
            t0 = time.monotonic()
            h = c.get("/health").json()
            assert (time.monotonic() - t0) < 0.5
            assert h["pipeline_ready"] is False
            assert h["warmup"]["state"] == "running"
            assert h["warmup"]["progress"] == pytest.approx(0.4)
            assert h["warmup"]["message"] == "Loading person detector"

            pub = c.get("/config/public").json()
            assert pub["pipeline_ready"] is False
            assert pub["warmup_state"] == "running"

            headers = _auth_headers(c, username="inv_p11_block")
            up = c.post(
                "/clips",
                headers=headers,
                data={"atm_id": "atm_demo"},
                files={"file": ("A_p11_block.mp4", raw, "video/mp4")},
            )
            assert up.status_code == 201
            clip_id = up.json()["id"]

            proc = c.post(
                f"/clips/{clip_id}/process",
                headers=headers,
                json={"transaction_time": "2026-11-26T15:30:02", "window_sec": 1},
            )
            assert proc.status_code == 202
            run_id = proc.json()["run_id"]

            # Give worker loop a moment; run must stay queued waiting for models.
            time.sleep(0.15)
            waiting = c.get(f"/runs/{run_id}", headers=headers).json()
            assert waiting["status"] == "queued"
            assert waiting["stage"] == "waiting for models"

            # Release warmup and confirm readiness flips True and run finishes.
            release.set()
            settled = _wait_warmup_settled(c)
            assert settled["pipeline_ready"] is True
            assert settled["warmup"]["state"] == "ok"
            assert settled["warmup"]["providers"]["faces"] == "CPUExecutionProvider"
            assert settled["warmup"]["loaded"]["person_detector"] is True

            done = _poll_run(c, headers, run_id)
            assert done["status"] == "done"
            assert calls == 1
    finally:
        release.set()


def test_warmup_ok_false_fails_queued_and_new_jobs_with_model_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Warmup returning ok=False sets pipeline_ready=False and fails runs/indexes with MODEL_LOAD."""
    raw = _make_clip_bytes(tmp_path, "A_p11_fail_ok.mp4")

    def _bad_warmup(progress_cb=None):
        if progress_cb:
            progress_cb({"stage": "warmup", "fraction": 0.5, "message": "Loading face model"})
        return WarmupResult(
            ok=False,
            loaded={"person_detector": True, "face_model": False, "clip": None},
            providers={"faces": None, "torch_device": "cpu"},
            timings_ms={"person_detector": 2.0, "face_model": 1.0, "clip": None},
            warnings=["Face model weights not found"],
            total_ms=3.0,
        )

    import pipeline.adapter as adapter

    monkeypatch.setattr(adapter, "get_warmup", lambda: _bad_warmup)

    settings = Settings(
        _env_file=None,
        USE_FAKE_PIPELINE=True,
        AUTO_INDEX_ON_UPLOAD=False,
        DATA_DIR=tmp_path / "bad_ok_data",
        JWT_SECRET=TEST_JWT_SECRET,
    )
    with TestClient(create_app(settings)) as c:
        health = _wait_warmup_settled(c)
        assert health["pipeline_ready"] is False
        assert health["warmup"]["state"] == "failed"
        assert health["warmup"]["warnings"] == ["Face model weights not found"]

        headers = _auth_headers(c, username="inv_p11_badok")
        clip_id = c.post(
            "/clips",
            headers=headers,
            data={"atm_id": "atm_demo"},
            files={"file": ("A_p11_fail_ok.mp4", raw, "video/mp4")},
        ).json()["id"]

        run_id = c.post(
            f"/clips/{clip_id}/process",
            headers=headers,
            json={"transaction_time": "2026-11-26T15:30:02", "window_sec": 1},
        ).json()["run_id"]
        failed_run = _poll_run(c, headers, run_id)
        assert failed_run["status"] == "failed"
        assert failed_run["error_code"] == "MODEL_LOAD"
        assert failed_run["error_advice"] == _ERROR_ADVICE_MAP["MODEL_LOAD"]
        assert "Face model weights not found" in failed_run["error_message"]

        idx_id = c.post(f"/clips/{clip_id}/index", headers=headers, json={}).json()["index_id"]
        failed_idx = _poll_index(c, headers, idx_id)
        assert failed_idx["status"] == "failed"
        assert failed_idx["error_code"] == "MODEL_LOAD"
        assert failed_idx["error_advice"] == _ERROR_ADVICE_MAP["MODEL_LOAD"]
        assert "Face model weights not found" in failed_idx["error_message"]


def test_warmup_exception_fails_jobs_with_model_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Warmup raising an exception sets pipeline_ready=False and fails queued/new jobs with MODEL_LOAD."""
    raw = _make_clip_bytes(tmp_path, "A_p11_exc.mp4")

    def _crashing_warmup(progress_cb=None):
        raise RuntimeError("ONNX runtime failed to initialize")

    import pipeline.adapter as adapter

    monkeypatch.setattr(adapter, "get_warmup", lambda: _crashing_warmup)

    settings = Settings(
        _env_file=None,
        USE_FAKE_PIPELINE=True,
        AUTO_INDEX_ON_UPLOAD=False,
        DATA_DIR=tmp_path / "exc_data",
        JWT_SECRET=TEST_JWT_SECRET,
    )
    with TestClient(create_app(settings)) as c:
        health = _wait_warmup_settled(c)
        assert health["pipeline_ready"] is False
        assert health["warmup"]["state"] == "failed"
        assert "ONNX runtime failed to initialize" in health["warmup"]["message"]

        headers = _auth_headers(c, username="inv_p11_exc")
        clip_id = c.post(
            "/clips",
            headers=headers,
            data={"atm_id": "atm_demo"},
            files={"file": ("A_p11_exc.mp4", raw, "video/mp4")},
        ).json()["id"]

        run_id = c.post(
            f"/clips/{clip_id}/process",
            headers=headers,
            json={"transaction_time": "2026-11-26T15:30:02", "window_sec": 1},
        ).json()["run_id"]
        failed = _poll_run(c, headers, run_id)
        assert failed["status"] == "failed"
        assert failed["error_code"] == "MODEL_LOAD"
        assert failed["error_advice"] == _ERROR_ADVICE_MAP["MODEL_LOAD"]
        assert "ONNX runtime failed to initialize" in failed["error_message"]
