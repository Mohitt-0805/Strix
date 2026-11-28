"""Phase 12 acceptance tests: lazy app creation (PEP 562) and test hygiene."""

import os
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.config import REPO_ROOT, Settings
from backend.app.main import create_app
from backend.tests.conftest import TEST_JWT_SECRET


def test_import_main_without_env_or_jwt_secret_does_not_raise(tmp_path: Path) -> None:
    """Merely importing backend.app.main in a clean env without .env or JWT_SECRET succeeds."""
    clean_env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(REPO_ROOT),
    }
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import backend.app.config as cfg; "
                "cfg.DEFAULT_ENV_FILE = cfg.Path('nonexistent.env'); "
                "import backend.app.main as m; "
                "assert callable(m.create_app)"
            ),
        ],
        cwd=tmp_path,
        env=clean_env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"stderr={proc.stderr}"


def test_lazy_app_caches_fastapi_instance_when_jwt_secret_set(tmp_path: Path) -> None:
    """Accessing backend.app.main.app builds and caches a FastAPI instance when JWT_SECRET is set."""
    clean_env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(REPO_ROOT),
        "JWT_SECRET": "lazy-app-test-secret-key-at-least-32-chars",
        "DATA_DIR": str(tmp_path / "lazy_data"),
        "USE_FAKE_PIPELINE": "1",
        "WARMUP_ON_START": "0",
    }
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from fastapi import FastAPI; "
                "import backend.app.config as cfg; "
                "cfg.DEFAULT_ENV_FILE = cfg.Path('nonexistent.env'); "
                "import backend.app.main as m; "
                "a1 = m.app; "
                "a2 = m.app; "
                "assert isinstance(a1, FastAPI); "
                "assert a1 is a2"
            ),
        ],
        cwd=tmp_path,
        env=clean_env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"stderr={proc.stderr}"


def test_create_app_with_explicit_settings_works(tmp_path: Path) -> None:
    """create_app(settings) remains functional as a direct factory."""
    cfg = Settings(
        _env_file=None,
        USE_FAKE_PIPELINE=True,
        AUTO_INDEX_ON_UPLOAD=False,
        DATA_DIR=tmp_path / "factory_data",
        JWT_SECRET=TEST_JWT_SECRET,
    )
    built = create_app(cfg)
    assert isinstance(built, FastAPI)
    with TestClient(built) as tc:
        resp = tc.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
