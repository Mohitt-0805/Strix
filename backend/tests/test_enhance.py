"""Phase 7 acceptance tests: frame enhancement baseline, caching, validation, PDF."""

import hashlib
import logging
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.models import AuditLog, FrameRecord, User
from backend.app.security import hash_password
from backend.tests.conftest import TEST_JWT_SECRET


def _make_clip_bytes(tmp_path: Path, name: str = "A_enh.mp4") -> bytes:
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


def _auth_headers(client: TestClient, username: str = "inv_enh") -> dict[str, str]:
    pw = "EnhancePass123!"
    with client.app.state.session_factory() as db:
        db.add(
            User(
                username=username,
                password_hash=hash_password(pw),
                role="investigator",
                full_name="Enhance Tester",
                active=True,
            )
        )
        db.commit()
    resp = client.post("/auth/login", json={"username": username, "password": pw})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _upload_and_process(
    client: TestClient, headers: dict[str, str], raw_bytes: bytes
) -> int:
    up = client.post(
        "/clips",
        headers=headers,
        data={"atm_id": "atm_demo"},
        files={"file": ("A_enh.mp4", raw_bytes, "video/mp4")},
    )
    assert up.status_code == 201
    clip_id = up.json()["id"]

    proc = client.post(
        f"/clips/{clip_id}/process",
        headers=headers,
        json={"transaction_time": "2026-11-26T15:30:02", "window_sec": 1, "sample_fps": 2.0},
    )
    assert proc.status_code == 202
    run_id = proc.json()["run_id"]

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        st = client.get(f"/runs/{run_id}", headers=headers).json()
        if st["status"] == "done":
            return run_id
        time.sleep(0.05)
    raise AssertionError("Run did not finish")


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    raw = pdf_bytes.decode("latin1", errors="ignore")
    chunks = re.findall(r"\(((?:\\.|[^\\()])*)\)\s*Tj", raw)
    return " ".join(
        c.replace(r"\(", "(").replace(r"\)", ")").replace(r"\\", "\\") for c in chunks
    )


def test_enhance_validation_cache_sha256_audit_and_pdf(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Validate 422 rules, SHA-256 preservation, caching, audit, result URLs, and PDF."""
    raw = _make_clip_bytes(tmp_path)
    headers = _auth_headers(client)
    run_id = _upload_and_process(client, headers, raw)

    # Validation errors -> 422 ENHANCE_INVALID
    bad_scale = client.post(
        f"/runs/{run_id}/frames/142/enhance",
        headers=headers,
        json={"crop_box": [100, 80, 120, 120], "scale": 3, "method": "lanczos"},
    )
    assert bad_scale.status_code == 422
    assert bad_scale.json()["code"] == "ENHANCE_INVALID"

    bad_box = client.post(
        f"/runs/{run_id}/frames/142/enhance",
        headers=headers,
        json={"crop_box": [100, 80, 4, 4], "scale": 2, "method": "lanczos"},
    )
    assert bad_box.status_code == 422
    assert bad_box.json()["code"] == "ENHANCE_INVALID"

    bad_method = client.post(
        f"/runs/{run_id}/frames/142/enhance",
        headers=headers,
        json={"crop_box": [100, 80, 120, 120], "scale": 2, "method": "esrgan"},
    )
    assert bad_method.status_code == 422
    assert bad_method.json()["code"] == "ENHANCE_INVALID"

    data_root = client.app.state.settings.resolved_data_dir
    with client.app.state.session_factory() as db:
        frame_row = (
            db.query(FrameRecord)
            .filter(FrameRecord.run_id == run_id, FrameRecord.frame_id == "142")
            .one()
        )
        orig_path = data_root / frame_row.frame_path_rel
        orig_sha_before = hashlib.sha256(orig_path.read_bytes()).hexdigest()

    # Spy on fake_enhance to confirm the second identical call hits the cache.
    import pipeline.fake_pipeline as fp

    orig_fake_enhance = fp.fake_enhance
    call_count = 0

    def _counting_fake_enhance(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return orig_fake_enhance(*args, **kwargs)

    monkeypatch.setattr(fp, "fake_enhance", _counting_fake_enhance)

    req_body = {"crop_box": [160, 80, 120, 120], "scale": 4, "method": "lanczos"}
    r1 = client.post(
        f"/runs/{run_id}/frames/142/enhance", headers=headers, json=req_body
    )
    assert r1.status_code == 200, r1.text
    b1 = r1.json()
    assert b1["cached"] is False
    assert b1["method"] == "lanczos"
    assert b1["scale"] == 4
    assert b1["model_version"] == "lanczos_v1"
    assert b1["search_embedding_source"] == "original"
    assert b1["crop_box"] == [160, 80, 120, 120]
    assert call_count == 1

    # Original SHA-256 is unchanged.
    assert hashlib.sha256(orig_path.read_bytes()).hexdigest() == orig_sha_before

    # Enhanced file exists inside DATA_DIR and its name contains 'enh'.
    enh_rel = parse_qs(urlparse(b1["enhanced_url"]).query)["p"][0]
    enh_abs = data_root / enh_rel
    assert enh_abs.is_file()
    assert "enh" in enh_abs.name.lower()

    # Both signed URLs return valid JPEGs without Authorization header.
    assert client.get(b1["original_url"]).content[:2] == b"\xff\xd8"
    assert client.get(b1["enhanced_url"]).content[:2] == b"\xff\xd8"

    # Repeat call hits cache (no recomputation).
    r2 = client.post(
        f"/runs/{run_id}/frames/142/enhance", headers=headers, json=req_body
    )
    assert r2.status_code == 200
    assert r2.json()["cached"] is True
    assert call_count == 1

    # Audit entry recorded.
    with client.app.state.session_factory() as db:
        audits = db.query(AuditLog).filter(AuditLog.action == "frame_enhanced").all()
        assert len(audits) == 2
        assert audits[0].details["model_version"] == "lanczos_v1"
        assert audits[0].details["cached"] is False
        assert audits[1].details["cached"] is True

    # GET /runs/{id}/result includes enhancement & enhanced_url on frame 142.
    res = client.get(f"/runs/{run_id}/result", headers=headers).json()
    f142 = next(f for f in res["best_frames"] if f["frame_id"] == "142")
    assert f142["enhanced"] is True
    assert f142["enhancement"]["enhanced_path"] == enh_rel
    assert f142["enhanced_url"].startswith("/files?")

    # Evidence PDF with enhanced frame generates and includes side-by-side caption.
    client.post(f"/runs/{run_id}/selection", headers=headers, json={"frame_ids": ["142"]})
    pdf_resp = client.get(f"/runs/{run_id}/evidence.pdf", headers=headers)
    assert pdf_resp.status_code == 200
    assert pdf_resp.content.startswith(b"%PDF")
    assert "ENHANCED (lanczos, 4x, lanczos_v1)" in _extract_pdf_text(pdf_resp.content)


def test_real_mode_import_error_falls_back_to_fake_enhance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When USE_FAKE_PIPELINE=0 and pipeline.enhance.enhance_frame raises ImportError, fallback runs."""
    caplog.set_level(logging.WARNING)
    raw = _make_clip_bytes(tmp_path)
    settings = Settings(
        _env_file=None,
        USE_FAKE_PIPELINE=False,
        AUTO_INDEX_ON_UPLOAD=False,
        DATA_DIR=tmp_path / "real_fb_data",
        JWT_SECRET=TEST_JWT_SECRET,
    )

    import pipeline.adapter as adapter
    import pipeline.enhance as enh_mod
    from pipeline.fake_pipeline import run as fake_run

    monkeypatch.setattr(adapter, "get_run", lambda: fake_run)

    def _missing_cv2(*_args, **_kwargs):
        raise ImportError("No module named 'cv2'")

    monkeypatch.setattr(enh_mod, "enhance_frame", _missing_cv2)

    with TestClient(create_app(settings)) as client:
        headers = _auth_headers(client, username="inv_real_fb")
        run_id = _upload_and_process(client, headers, raw)

        # In real mode materialize_fake_assets didn't run, so write a real JPEG for frame 142.
        data_root = settings.resolved_data_dir
        with client.app.state.session_factory() as db:
            fr = (
                db.query(FrameRecord)
                .filter(FrameRecord.run_id == run_id, FrameRecord.frame_id == "142")
                .one()
            )
            frame_abs = data_root / fr.frame_path_rel
            frame_abs.parent.mkdir(parents=True, exist_ok=True)
            from PIL import Image

            Image.new("RGB", (640, 480), color=(40, 60, 80)).save(frame_abs, format="JPEG")

        resp = client.post(
            f"/runs/{run_id}/frames/142/enhance",
            headers=headers,
            json={"crop_box": [50, 50, 100, 100], "scale": 2, "method": "lanczos"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["model_version"] == "lanczos_v1"
        assert "falling back to fake_enhance" in caplog.text
