"""Phase 3 acceptance tests: storage, probe, upload, clips, signed URLs, Range."""

import hashlib
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.errors import AppError
from backend.app.main import create_app
from backend.app.models import AuditLog, User
from backend.app.security import hash_password
from backend.app.services.probe import UNREADABLE_VIDEO_ADVICE
from backend.app.services.storage import from_rel, to_rel
from backend.app.signing import compute_file_signature
from backend.tests.conftest import TEST_JWT_SECRET


def _make_sample_clip(
    dest: Path, *, duration: int = 5, creation_time_utc: str | None = None
) -> Path:
    """Generate a synthetic clip via ffmpeg lavfi; skip test if ffmpeg is absent."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg not installed on PATH")

    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={duration}:size=320x240:rate=10",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
    ]
    if creation_time_utc:
        cmd.extend(["-metadata", f"creation_time={creation_time_utc}"])
    cmd.append(str(dest))

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        pytest.skip(f"ffmpeg failed to build synthetic clip: {proc.stderr}")
    return dest


def _create_user_and_token(
    client: TestClient, username: str = "inv_clip", role: str = "investigator"
) -> tuple[int, str]:
    password = "ClipUserPass123!"
    with client.app.state.session_factory() as db:
        user = User(
            username=username,
            password_hash=hash_password(password),
            role=role,
            full_name="Clip Tester",
            active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id

    resp = client.post(
        "/auth/login", json={"username": username, "password": password}
    )
    assert resp.status_code == 200
    return user_id, resp.json()["access_token"]


def test_storage_to_rel_and_from_rel_rules(tmp_path: Path) -> None:
    """to_rel normalizes paths inside DATA_DIR; from_rel rejects escapes and symlinks."""
    data_dir = tmp_path / "data"
    (data_dir / "uploads" / "c1").mkdir(parents=True)
    clip_file = data_dir / "uploads" / "c1" / "clip.mp4"
    clip_file.write_bytes(b"mp4")

    assert to_rel(clip_file, data_dir) == "uploads/c1/clip.mp4"
    assert to_rel("uploads/c1/clip.mp4", data_dir) == "uploads/c1/clip.mp4"
    assert to_rel("data/outputs/run_1/frame.jpg", data_dir) == "outputs/run_1/frame.jpg"

    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    with pytest.raises(AppError):
        to_rel(outside, data_dir)

    assert from_rel("uploads/c1/clip.mp4", data_dir) == clip_file.resolve()
    with pytest.raises(AppError):
        from_rel("../outside.txt", data_dir)
    with pytest.raises(AppError):
        from_rel(str(outside), data_dir)
    with pytest.raises(AppError):
        from_rel("strix.db", data_dir, allowed_roots=("uploads", "outputs"))

    link_path = data_dir / "uploads" / "escape_link.mp4"
    link_path.symlink_to(outside)
    with pytest.raises(AppError):
        from_rel("uploads/escape_link.mp4", data_dir, allowed_roots=("uploads",))


def test_upload_validation_bad_ext_fake_mp4_and_oversize(
    client: TestClient, tmp_path: Path
) -> None:
    """Bad extension 422, text renamed .mp4 422 with advice, oversize 413."""
    _, token = _create_user_and_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    bad_ext = client.post(
        "/clips",
        headers=headers,
        files={"file": ("notes.txt", b"hello world", "text/plain")},
    )
    assert bad_ext.status_code == 422
    assert bad_ext.json()["code"] == "INVALID_EXTENSION"

    fake_mp4 = client.post(
        "/clips",
        headers=headers,
        files={"file": ("fake.mp4", b"this is plain text not mp4", "video/mp4")},
    )
    assert fake_mp4.status_code == 422
    assert fake_mp4.json()["code"] == "UNREADABLE_VIDEO"
    assert UNREADABLE_VIDEO_ADVICE in fake_mp4.json()["detail"]

    # Nothing unreadable should remain in uploads/.
    uploads_dir = client.app.state.settings.resolved_data_dir / "uploads"
    assert list(uploads_dir.glob("*/*.mp4")) == []

    # Oversize upload returns 413.
    small_limit_settings = Settings(
        _env_file=None,
        USE_FAKE_PIPELINE=True,
        DATA_DIR=tmp_path / "small_data",
        JWT_SECRET=TEST_JWT_SECRET,
        MAX_UPLOAD_MB=1,
    )
    with TestClient(create_app(small_limit_settings)) as small_client:
        _, small_token = _create_user_and_token(small_client, username="small_u")
        oversize_payload = b"\x00" * (1024 * 1024 + 64)
        over = small_client.post(
            "/clips",
            headers={"Authorization": f"Bearer {small_token}"},
            files={"file": ("big.mp4", oversize_payload, "video/mp4")},
        )
        assert over.status_code == 413
        assert over.json()["code"] == "FILE_TOO_LARGE"


def test_upload_probe_creation_time_patch_signed_urls_and_range(
    client: TestClient, tmp_path: Path
) -> None:
    """End-to-end Phase 3: upload real clip, creation_time TZ, PATCH, signed /files, Range 206."""
    clip_src = _make_sample_clip(
        tmp_path / "atm_test.mp4",
        duration=5,
        creation_time_utc="2026-11-26T10:00:00Z",
    )
    raw_bytes = clip_src.read_bytes()
    expected_sha = hashlib.sha256(raw_bytes).hexdigest()

    user_id, token = _create_user_and_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    upload = client.post(
        "/clips",
        headers=headers,
        data={"atm_id": "ATM-042", "notes": "Lobby cam"},
        files={"file": ("../evil_dir/atm_test.mp4", raw_bytes, "video/mp4")},
    )
    assert upload.status_code == 201, upload.text
    body = upload.json()
    clip_id = body["id"]
    assert body["original_filename"] == "atm_test.mp4"
    assert body["sha256"] == expected_sha
    assert body["size_bytes"] == len(raw_bytes)
    assert body["duration_sec"] == pytest.approx(5.0, abs=0.5)
    assert body["width"] == 320
    assert body["height"] == 240
    assert body["stored_path"] == f"uploads/{clip_id}/atm_test.mp4"
    # 10:00:00 UTC -> 15:30:00 Asia/Kolkata
    assert body["clip_start_time"].startswith("2026-11-26T15:30:00")
    assert body["clip_start_source"] == "ffprobe_converted"
    assert body["video_url"].startswith("/files?")

    # List & get clips.
    assert any(c["id"] == clip_id for c in client.get("/clips", headers=headers).json())
    assert client.get(f"/clips/{clip_id}", headers=headers).status_code == 200

    # PATCH clip metadata & polygon validation.
    bad_poly = client.patch(
        f"/clips/{clip_id}",
        headers=headers,
        json={"zone_polygon_norm": [[0.1, 0.1], [0.9, 0.9]]},
    )
    assert bad_poly.status_code == 422

    patched = client.patch(
        f"/clips/{clip_id}",
        headers=headers,
        json={
            "clip_start_time": "2026-11-26T16:00:00",
            "zone_polygon_norm": [[0.1, 0.1], [0.8, 0.1], [0.8, 0.9], [0.1, 0.9]],
            "notes": "Updated notes",
        },
    )
    assert patched.status_code == 200
    assert patched.json()["clip_start_source"] == "user"
    assert patched.json()["notes"] == "Updated notes"

    # Signed URL works without Authorization header.
    signed_url = body["video_url"]
    full_signed = client.get(signed_url)
    assert full_signed.status_code == 200
    assert full_signed.content == raw_bytes

    # Range request on signed URL returns 206 Partial Content.
    r206 = client.get(signed_url, headers={"Range": "bytes=0-99"})
    assert r206.status_code == 206
    assert r206.headers["content-range"] == f"bytes 0-99/{len(raw_bytes)}"
    assert r206.content == raw_bytes[:100]

    # Range request on /clips/{id}/video returns 206 Partial Content.
    clip_r206 = client.get(
        f"/clips/{clip_id}/video",
        headers={**headers, "Range": "bytes=10-49"},
    )
    assert clip_r206.status_code == 206
    assert clip_r206.content == raw_bytes[10:50]

    # ?download=1 sets Content-Disposition and writes download_video audit entry.
    dl = client.get(f"{signed_url}&download=1")
    assert dl.status_code == 200
    assert "attachment;" in dl.headers.get("content-disposition", "")
    with client.app.state.session_factory() as db:
        dl_entries = (
            db.query(AuditLog).filter(AuditLog.action == "download_video").all()
        )
        assert len(dl_entries) == 1

    # Expired signed URL -> 403.
    parsed = urlparse(signed_url)
    qs = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    past_exp = int(time.time()) - 60
    secret = client.app.state.settings.jwt_secret
    expired_sig = compute_file_signature(qs["p"], user_id, past_exp, secret)
    expired_resp = client.get(
        f"/files?{urlencode({'p': qs['p'], 'uid': user_id, 'exp': past_exp, 'sig': expired_sig})}"
    )
    assert expired_resp.status_code == 403
    assert expired_resp.json()["code"] == "SIGNED_URL_EXPIRED"

    # Tampered signature -> 403.
    bad_sig_resp = client.get(
        f"/files?{urlencode({'p': qs['p'], 'uid': qs['uid'], 'exp': qs['exp'], 'sig': '0'*64})}"
    )
    assert bad_sig_resp.status_code == 403
    assert bad_sig_resp.json()["code"] == "INVALID_SIGNATURE"

    # Valid signature over '../' or absolute path -> 403.
    future_exp = int(time.time()) + 300
    for bad_path in ("../etc/passwd", "/etc/passwd", "strix.db"):
        sig = compute_file_signature(bad_path, user_id, future_exp, secret)
        resp = client.get(
            f"/files?{urlencode({'p': bad_path, 'uid': user_id, 'exp': future_exp, 'sig': sig})}"
        )
        assert resp.status_code == 403
        assert resp.json()["code"] == "INVALID_PATH"
