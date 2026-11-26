"""Shared pytest configuration and fixtures for backend tests."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.config import Settings  # noqa: E402
from backend.app.main import create_app  # noqa: E402

TEST_JWT_SECRET = "test-secret-key-at-least-32-chars-long-0123456789"


@pytest.fixture()
def test_settings(tmp_path: Path) -> Settings:
    """Return isolated Settings backed by a temporary DATA_DIR."""
    return Settings(
        _env_file=None,
        USE_FAKE_PIPELINE=True,
        DATA_DIR=tmp_path / "data",
        JWT_SECRET=TEST_JWT_SECRET,
        CORS_ORIGINS="http://localhost:5173,http://localhost:3000",
    )


@pytest.fixture()
def client(test_settings: Settings):
    """Yield a FastAPI TestClient wired to a temporary database."""
    app = create_app(test_settings)
    with TestClient(app) as test_client:
        yield test_client
