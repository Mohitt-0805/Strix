"""Phase 2 acceptance tests: auth, users, roles, throttle, audit chain, triggers, seed."""

import csv
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.app.config import Settings
from backend.app.models import AuditLog, User
from backend.app.security import hash_password
from backend.scripts.seed_users import seed_users


def _seed_test_users(client: TestClient) -> tuple[str, str]:
    """Insert an admin and an investigator directly for test isolation."""
    admin_pw = "AdminPass123!"
    inv_pw = "InvestigatorPass123!"
    session_factory = client.app.state.session_factory
    with session_factory() as db:
        db.add_all(
            [
                User(
                    username="admin_test",
                    password_hash=hash_password(admin_pw),
                    role="admin",
                    full_name="Test Admin",
                    active=True,
                ),
                User(
                    username="inv_test",
                    password_hash=hash_password(inv_pw),
                    role="investigator",
                    full_name="Test Investigator",
                    active=True,
                ),
            ]
        )
        db.commit()
    return admin_pw, inv_pw


def _login(client: TestClient, username: str, password: str) -> dict:
    resp = client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_login_me_and_wrong_password_logged(client: TestClient) -> None:
    """Valid login returns JWT and /auth/me works; wrong password returns 401 and logs."""
    admin_pw, _ = _seed_test_users(client)

    bad = client.post(
        "/auth/login",
        json={"username": "admin_test", "password": "wrong-password"},
    )
    assert bad.status_code == 401
    assert bad.json()["code"] == "INVALID_CREDENTIALS"

    # Unauthenticated /auth/me returns 401.
    unauth = client.get("/auth/me")
    assert unauth.status_code == 401
    assert unauth.json()["code"] == "UNAUTHORIZED"

    login_data = _login(client, "admin_test", admin_pw)
    assert login_data["token_type"] == "bearer"
    assert login_data["user"]["username"] == "admin_test"
    assert "password_hash" not in login_data["user"]

    me_resp = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {login_data['access_token']}"},
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["role"] == "admin"

    # Verify login_failed was recorded without leaking the password.
    audit_resp = client.get(
        "/audit",
        params={"action": "login_failed"},
        headers={"Authorization": f"Bearer {login_data['access_token']}"},
    )
    assert audit_resp.status_code == 200
    items = audit_resp.json()["items"]
    assert len(items) == 1
    assert items[0]["username"] == "admin_test"
    assert "wrong-password" not in str(items[0])


def test_login_throttle_returns_429(client: TestClient) -> None:
    """After 5 failed logins in 5 minutes for username+IP, 6th attempt returns 429."""
    _seed_test_users(client)

    for _ in range(5):
        resp = client.post(
            "/auth/login",
            json={"username": "inv_test", "password": "bad-password"},
        )
        assert resp.status_code == 401

    throttled = client.post(
        "/auth/login",
        json={"username": "inv_test", "password": "bad-password"},
    )
    assert throttled.status_code == 429
    assert throttled.json()["code"] == "TOO_MANY_LOGIN_ATTEMPTS"


def test_roles_users_and_investigator_forbidden(client: TestClient) -> None:
    """Admin manages users and audit; investigator gets 403 on /users and /audit."""
    admin_pw, inv_pw = _seed_test_users(client)
    admin_token = _login(client, "admin_test", admin_pw)["access_token"]
    inv_token = _login(client, "inv_test", inv_pw)["access_token"]

    inv_headers = {"Authorization": f"Bearer {inv_token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Investigator is blocked from admin endpoints.
    for method, path in (
        ("GET", "/users"),
        ("POST", "/users"),
        ("GET", "/audit"),
        ("GET", "/audit/export.csv"),
        ("GET", "/audit/verify"),
    ):
        kwargs = {"headers": inv_headers}
        if method == "POST":
            kwargs["json"] = {
                "username": "x",
                "password": "Password123!",
                "role": "investigator",
                "full_name": "X",
            }
        resp = client.request(method, path, **kwargs)
        assert resp.status_code == 403
        assert resp.json()["code"] == "FORBIDDEN"

    # Admin creates a new investigator and lists users.
    created = client.post(
        "/users",
        headers=admin_headers,
        json={
            "username": "new_inv",
            "password": "StrongPassword99",
            "role": "investigator",
            "full_name": "New Investigator",
        },
    )
    assert created.status_code == 201
    assert created.json()["username"] == "new_inv"

    dup = client.post(
        "/users",
        headers=admin_headers,
        json={
            "username": "new_inv",
            "password": "StrongPassword99",
            "role": "investigator",
            "full_name": "Duplicate",
        },
    )
    assert dup.status_code == 409
    assert dup.json()["code"] == "USERNAME_EXISTS"

    listed = client.get("/users", headers=admin_headers)
    assert listed.status_code == 200
    assert {u["username"] for u in listed.json()} == {"admin_test", "inv_test", "new_inv"}


def test_audit_export_csv_and_verify_detects_tamper(client: TestClient) -> None:
    """Audit CSV export logs audit_export; verify passes then detects tampering."""
    admin_pw, _ = _seed_test_users(client)
    admin_token = _login(client, "admin_test", admin_pw)["access_token"]
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Export CSV and check headers + recorded audit_export action.
    csv_resp = client.get("/audit/export.csv", headers=headers)
    assert csv_resp.status_code == 200
    assert csv_resp.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(csv_resp.text)))
    assert any(row["action"] == "audit_export" for row in rows)

    ok_verify = client.get("/audit/verify", headers=headers)
    assert ok_verify.status_code == 200
    assert ok_verify.json()["ok"] is True
    assert ok_verify.json()["first_bad_id"] is None

    # Simulate direct SQLite tampering by dropping triggers temporarily, editing row 1.
    engine = client.app.state.engine
    with engine.begin() as conn:
        conn.execute(text("DROP TRIGGER IF EXISTS trg_audit_log_no_update;"))
        conn.execute(text("UPDATE audit_log SET action = 'tampered_action' WHERE id = 1;"))

    bad_verify = client.get("/audit/verify", headers=headers)
    assert bad_verify.status_code == 200
    body = bad_verify.json()
    assert body["ok"] is False
    assert body["first_bad_id"] == 1


def test_audit_log_triggers_block_update_and_delete(client: TestClient) -> None:
    """SQLite triggers raise on UPDATE and DELETE of audit_log."""
    admin_pw, _ = _seed_test_users(client)
    _login(client, "admin_test", admin_pw)

    engine = client.app.state.engine
    with engine.begin() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM audit_log")).scalar_one()
        assert count >= 1

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("UPDATE audit_log SET action = 'hacked' WHERE id = 1;"))

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM audit_log WHERE id = 1;"))

    with client.app.state.session_factory() as db:
        row = db.get(AuditLog, 1)
        assert row is not None
        assert row.action == "login_success"


def test_seed_users_script_env_and_random(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """seed_users reads env passwords or generates random ones once, and is idempotent."""
    settings = Settings(
        _env_file=None,
        USE_FAKE_PIPELINE=True,
        DATA_DIR=tmp_path / "seed_data",
        JWT_SECRET="seed-test-secret-at-least-32-characters-long",
    )

    # Without env vars: generates random passwords for both users.
    monkeypatch.delenv("STRIX_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("STRIX_INVESTIGATOR_PASSWORD", raising=False)
    generated = seed_users(settings)
    assert set(generated.keys()) == {"admin", "investigator"}
    assert len(generated["admin"]) >= 16
    assert generated["admin"] != generated["investigator"]

    # Second run skips existing users and generates nothing.
    second = seed_users(settings)
    assert second == {}

    # With env vars on a fresh DB: uses env passwords and generates nothing.
    settings_env = Settings(
        _env_file=None,
        USE_FAKE_PIPELINE=True,
        DATA_DIR=tmp_path / "seed_env_data",
        JWT_SECRET="seed-test-secret-at-least-32-characters-long",
    )
    monkeypatch.setenv("STRIX_ADMIN_PASSWORD", "EnvAdminPass!123")
    monkeypatch.setenv("STRIX_INVESTIGATOR_PASSWORD", "EnvInvPass!123")
    generated_env = seed_users(settings_env)
    assert generated_env == {}
