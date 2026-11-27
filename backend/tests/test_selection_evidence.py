"""Phase 6 acceptance tests: frame selection and ReportLab evidence PDF export."""

import hashlib
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.config import FAKE_BANNER_TEXT, HUMAN_VERIFICATION_NOTICE
from backend.app.models import AuditLog, FrameRecord, User
from backend.app.security import hash_password
from pipeline.contract import PipelineResult


def _make_clip_bytes(tmp_path: Path, name: str = "A_ev.mp4") -> bytes:
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


def _create_user_headers(
    client: TestClient,
    *,
    username: str = "inv_ev",
    full_name: str = "अंशिका राजपुरोहित (José)",
    role: str = "investigator",
) -> dict[str, str]:
    pw = "EvidencePass123!"
    with client.app.state.session_factory() as db:
        db.add(
            User(
                username=username,
                password_hash=hash_password(pw),
                role=role,
                full_name=full_name,
                active=True,
            )
        )
        db.commit()
    resp = client.post("/auth/login", json={"username": username, "password": pw})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _upload_and_process(
    client: TestClient, headers: dict[str, str], filename: str, raw_bytes: bytes
) -> tuple[str, int]:
    up = client.post(
        "/clips",
        headers=headers,
        data={"atm_id": "ATM-601"},
        files={"file": (filename, raw_bytes, "video/mp4")},
    )
    assert up.status_code == 201, up.text
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
            return clip_id, run_id
        if st["status"] == "failed":
            raise AssertionError(f"Run failed: {st}")
        time.sleep(0.05)
    raise AssertionError(f"Run {run_id} timed out")


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract literal PDF Tj strings with unescaped parentheses for assertions."""
    raw = pdf_bytes.decode("latin1", errors="ignore")
    chunks = re.findall(r"\(((?:\\.|[^\\()])*)\)\s*Tj", raw)
    unescaped = [
        c.replace(r"\(", "(").replace(r"\)", ")").replace(r"\\", "\\")
        for c in chunks
    ]
    return " ".join(unescaped)


def test_selection_and_evidence_pdf_fake_warning_search_and_audit(
    client: TestClient, tmp_path: Path
) -> None:
    """Selection replaces selected frames; evidence PDF starts with %PDF, has warning, search, hash."""
    raw = _make_clip_bytes(tmp_path)
    headers = _create_user_headers(client)
    _clip_a1, run_1 = _upload_and_process(client, headers, "A_one.mp4", raw)
    _clip_a2, run_2 = _upload_and_process(client, headers, "A_two.mp4", raw)

    # Invalid frame id in selection -> 422.
    bad_sel = client.post(
        f"/runs/{run_1}/selection",
        headers=headers,
        json={"frame_ids": ["nonexistent_id"]},
    )
    assert bad_sel.status_code == 422
    assert bad_sel.json()["code"] == "INVALID_FRAME_SELECTION"

    # Select two frames (including 158 which has enhancement in fake sample).
    sel = client.post(
        f"/runs/{run_1}/selection",
        headers=headers,
        json={"frame_ids": ["142", 158]},
    )
    assert sel.status_code == 200
    assert sel.json()["selected_frame_ids"] == ["142", "158"]

    # Replace selection with a single frame then back to two frames to verify replacement.
    sel_replace = client.post(
        f"/runs/{run_1}/selection",
        headers=headers,
        json={"frame_ids": ["171"]},
    )
    assert sel_replace.json()["selected_frame_ids"] == ["171"]
    client.post(
        f"/runs/{run_1}/selection",
        headers=headers,
        json={"frame_ids": ["142", "158"]},
    )

    search_resp = client.post(
        "/search",
        headers=headers,
        json={"run_id": run_1, "frame_id": "142", "top_k": 5},
    )
    assert search_resp.status_code == 200
    search_id = search_resp.json()["search_id"]

    # Wrong run_id or wrong search_id -> 404.
    assert client.get("/runs/99999/evidence.pdf", headers=headers).status_code == 404
    assert (
        client.get(f"/runs/{run_1}/evidence.pdf?search_id=99999", headers=headers).status_code
        == 404
    )
    # search_id belongs to run_1, not run_2 -> 404 on run_2.
    assert (
        client.get(
            f"/runs/{run_2}/evidence.pdf?search_id={search_id}", headers=headers
        ).status_code
        == 404
    )

    # Download evidence PDF as investigator.
    pdf_resp = client.get(
        f"/runs/{run_1}/evidence.pdf?search_id={search_id}",
        headers=headers,
    )
    assert pdf_resp.status_code == 200
    assert pdf_resp.headers["content-type"] == "application/pdf"
    pdf_bytes = pdf_resp.content
    assert pdf_bytes.startswith(b"%PDF")
    extracted = _extract_pdf_text(pdf_bytes)
    assert FAKE_BANNER_TEXT in extracted
    assert HUMAN_VERIFICATION_NOTICE in extracted
    assert f"EV-{run_1}" in extracted
    assert "ENHANCED (espcn, 4x, espcn_x4_v1)" in extracted
    assert "uncalibrated similarity, tune on sample data" in extracted

    expected_pdf_sha = hashlib.sha256(pdf_bytes).hexdigest()
    with client.app.state.session_factory() as db:
        dl_entries = (
            db.query(AuditLog)
            .filter(AuditLog.action == "download_evidence")
            .order_by(AuditLog.id.desc())
            .all()
        )
        assert len(dl_entries) == 1
        assert dl_entries[0].details["pdf_sha256"] == expected_pdf_sha
        sel_entries = (
            db.query(AuditLog).filter(AuditLog.action == "frames_selected").all()
        )
        assert len(sel_entries) == 3


def test_evidence_pdf_zero_frames_missing_image_and_long_non_ascii(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PDF handles 0 frames, missing images ('image unavailable'), long text, and non-ASCII."""
    raw = _make_clip_bytes(tmp_path)
    headers = _create_user_headers(
        client,
        username="inv_nonascii",
        full_name="रवि शर्मा <Test & Co>",
    )

    # Case A: zero frames run.
    def _empty_run(clip_path, tx_offset_sec, window_sec=10):
        return PipelineResult(
            clip_id=Path(clip_path).parent.name,
            transaction_time="2026-11-26T15:30:02",
            person_track_id=None,
            best_frames=[],
            link_confidence="Low",
            link_reason="No person entered ATM zone",
            selection_reason="Face not visible in transaction window",
        )

    import pipeline.adapter as adapter

    monkeypatch.setattr(adapter, "get_run", lambda: _empty_run)
    _, zero_run = _upload_and_process(client, headers, "empty_clip.mp4", raw)
    zero_pdf = client.get(f"/runs/{zero_run}/evidence.pdf", headers=headers)
    assert zero_pdf.status_code == 200
    assert zero_pdf.content.startswith(b"%PDF")
    assert b"Face not visible in transaction window" in zero_pdf.content

    # Case B: missing image files + very long rank_reason.
    monkeypatch.undo()
    _, normal_run = _upload_and_process(client, headers, "A_missing.mp4", raw)
    data_root = client.app.state.settings.resolved_data_dir
    with client.app.state.session_factory() as db:
        rows = db.query(FrameRecord).filter(FrameRecord.run_id == normal_run).all()
        for row in rows:
            row.rank_reason = "Long rank reason: " + ("very_long_detail_" * 25)
            for rel in (row.frame_path_rel, row.crop_path_rel):
                if rel:
                    p = data_root / rel
                    if p.exists():
                        p.unlink()
        db.commit()

    missing_pdf = client.get(f"/runs/{normal_run}/evidence.pdf", headers=headers)
    assert missing_pdf.status_code == 200
    assert missing_pdf.content.startswith(b"%PDF")
    assert b"image unavailable" in missing_pdf.content
