"""Phase 1 acceptance tests: skeleton, config, DB pragmas, CORS, and error format."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text

from backend.app.config import (
    ACCEPTED_VIDEO_EXTENSIONS,
    FAKE_BANNER_TEXT,
    HUMAN_VERIFICATION_NOTICE,
    REPO_ROOT,
    Settings,
)
from backend.app.errors import AppError
from backend.app.main import create_app
from backend.tests.conftest import TEST_JWT_SECRET


def test_health_ok(client: TestClient) -> None:
    """GET /health returns 200 with DB ok and pipeline mode."""
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert body["pipeline_mode"] == "fake"
    assert isinstance(body["ffmpeg"], bool)
    assert isinstance(body["ffprobe"], bool)


def test_config_public_fake_and_real(tmp_path: Path) -> None:
    """GET /config/public returns notice, limits, extensions, and mode-specific labels."""
    fake_settings = Settings(
        _env_file=None,
        USE_FAKE_PIPELINE=True,
        DATA_DIR=tmp_path / "fake_data",
        JWT_SECRET=TEST_JWT_SECRET,
    )
    with TestClient(create_app(fake_settings)) as fake_client:
        resp = fake_client.get("/config/public")
        assert resp.status_code == 200
        body = resp.json()
        assert body["pipeline_mode"] == "fake"
        assert body["banner"] == FAKE_BANNER_TEXT
        assert body["notice"] == HUMAN_VERIFICATION_NOTICE
        assert body["accepted_extensions"] == list(ACCEPTED_VIDEO_EXTENSIONS)
        assert body["model_labels"] == ["FAKE PIPELINE"]
        assert body["limits"]["max_sampled_frames"] == 200
        assert body["limits"]["embed_dim"] == 512

    real_settings = Settings(
        _env_file=None,
        USE_FAKE_PIPELINE=False,
        DATA_DIR=tmp_path / "real_data",
        JWT_SECRET=TEST_JWT_SECRET,
    )
    with TestClient(create_app(real_settings)) as real_client:
        resp = real_client.get("/config/public")
        assert resp.status_code == 200
        body = resp.json()
        assert body["pipeline_mode"] == "real"
        assert body["banner"] is None
        assert len(body["model_labels"]) == 3
        assert "FAKE PIPELINE" not in body["model_labels"]


def test_missing_or_short_jwt_secret_refuses_to_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """App refuses to configure or start if JWT_SECRET is missing or < 32 chars."""
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, DATA_DIR=tmp_path)

    with pytest.raises(ValidationError):
        Settings(_env_file=None, DATA_DIR=tmp_path, JWT_SECRET="too-short")

    # Verify accessing lazy main.app fails when no JWT_SECRET or .env is available.
    clean_env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(REPO_ROOT),
    }
    proc_no_env = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import backend.app.config as cfg; "
                "cfg.DEFAULT_ENV_FILE = cfg.Path('nonexistent.env'); "
                "import backend.app.main as m; "
                "_ = m.app"
            ),
        ],
        cwd=tmp_path,
        env=clean_env,
        capture_output=True,
        text=True,
    )
    assert proc_no_env.returncode != 0
    assert "JWT_SECRET" in proc_no_env.stderr

    # Verify accessing lazy main.app fails when JWT_SECRET env var is too short.
    proc_short = subprocess.run(
        [sys.executable, "-c", "import backend.app.main as m; _ = m.app"],
        cwd=tmp_path,
        env={**clean_env, "JWT_SECRET": "too-short"},
        capture_output=True,
        text=True,
    )
    assert proc_short.returncode != 0
    assert "JWT_SECRET" in proc_short.stderr


def test_cors_policy(tmp_path: Path, client: TestClient) -> None:
    """Wildcard CORS is rejected and configured origins are allowed."""
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            DATA_DIR=tmp_path,
            JWT_SECRET=TEST_JWT_SECRET,
            CORS_ORIGINS="*",
        )

    allowed = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert allowed.status_code == 200
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"

    disallowed = client.get("/health", headers={"Origin": "https://evil.example.com"})
    assert disallowed.status_code == 200
    assert disallowed.headers.get("access-control-allow-origin") is None


def test_error_format(test_settings: Settings) -> None:
    """All errors return {'detail': '<message>', 'code': '<UPPER_SNAKE>'}."""
    app = create_app(test_settings)

    @app.get("/_test/app-error")
    def _raise_app_error() -> None:
        raise AppError(status_code=418, code="TEAPOT_TEST", detail="Short and stout.")

    @app.get("/_test/validation/{item_id}")
    def _validate_int(item_id: int) -> dict[str, int]:
        return {"item_id": item_id}

    @app.get("/_test/boom")
    def _raise_unexpected() -> None:
        raise RuntimeError("sensitive internal detail")

    with TestClient(app, raise_server_exceptions=False) as client:
        r404 = client.get("/no-such-route")
        assert r404.status_code == 404
        assert r404.json()["code"] == "NOT_FOUND"
        assert isinstance(r404.json()["detail"], str)

        r405 = client.post("/health")
        assert r405.status_code == 405
        assert r405.json()["code"] == "METHOD_NOT_ALLOWED"

        rapp = client.get("/_test/app-error")
        assert rapp.status_code == 418
        assert rapp.json() == {"detail": "Short and stout.", "code": "TEAPOT_TEST"}

        r422 = client.get("/_test/validation/not-an-int")
        assert r422.status_code == 422
        assert r422.json()["code"] == "VALIDATION_ERROR"
        assert "item_id" in r422.json()["detail"]

        r500 = client.get("/_test/boom")
        assert r500.status_code == 500
        assert r500.json() == {
            "detail": "Internal server error.",
            "code": "INTERNAL_ERROR",
        }


def test_sqlite_pragmas(client: TestClient) -> None:
    """SQLite connection enforces foreign_keys=ON and journal_mode=WAL."""
    engine = client.app.state.engine
    with engine.connect() as conn:
        fk = conn.execute(text("PRAGMA foreign_keys;")).scalar_one()
        journal = conn.execute(text("PRAGMA journal_mode;")).scalar_one()
    assert fk == 1
    assert str(journal).lower() == "wal"
