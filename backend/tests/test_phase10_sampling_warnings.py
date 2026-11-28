"""Phase 10 acceptance tests: sampling rate, coverage window, warnings, PDF & allow_truncate."""

import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.models import ClipIndex, Run, User
from backend.app.security import hash_password
from pipeline.contract import Frame, IndexResult, Metrics, PipelineResult


def _make_clip_bytes(tmp_path: Path, name: str = "A_p10.mp4") -> bytes:
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


def _auth_headers(client: TestClient, username: str = "inv_p10") -> dict[str, str]:
    pw = "Phase10Pass123!"
    with client.app.state.session_factory() as db:
        db.add(
            User(
                username=username,
                password_hash=hash_password(pw),
                role="investigator",
                full_name="Phase 10 Tester",
                active=True,
            )
        )
        db.commit()
    resp = client.post("/auth/login", json={"username": username, "password": pw})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _poll_run(client: TestClient, headers: dict[str, str], run_id: int) -> dict:
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        body = client.get(f"/runs/{run_id}", headers=headers).json()
        if body["status"] in {"done", "failed"}:
            return body
        time.sleep(0.05)
    raise AssertionError(f"Run {run_id} did not finish")


def _poll_index(client: TestClient, headers: dict[str, str], index_id: int) -> dict:
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        body = client.get(f"/indexes/{index_id}", headers=headers).json()
        if body["status"] in {"done", "failed"}:
            return body
        time.sleep(0.05)
    raise AssertionError(f"Index {index_id} did not finish")


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    raw = pdf_bytes.decode("latin1", errors="ignore")
    chunks = re.findall(r"\(((?:\\.|[^\\()])*)\)\s*Tj", raw)
    return " ".join(
        c.replace(r"\(", "(").replace(r"\)", ")").replace(r"\\", "\\") for c in chunks
    )


def test_sampling_coverage_warnings_stored_returned_and_printed_in_pdf(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Monkeypatched run and index return sampling/coverage/warnings -> persisted, returned, and in PDF."""
    raw = _make_clip_bytes(tmp_path)
    headers = _auth_headers(client, username="inv_p10_full")
    up = client.post(
        "/clips",
        headers=headers,
        data={"atm_id": "atm_demo"},
        files={"file": ("A_p10.mp4", raw, "video/mp4")},
    )
    assert up.status_code == 201
    clip_id = up.json()["id"]

    def _custom_run(clip_path, tx_offset_sec, window_sec=10, **kwargs) -> PipelineResult:
        return PipelineResult(
            clip_id=clip_id,
            transaction_time="2026-11-26T15:30:02",
            person_track_id=1,
            best_frames=[
                Frame(
                    frame_id="101",
                    frame_path="data/outputs/x/f101.jpg",
                    timestamp_sec=1.5,
                    quality_score=0.85,
                    reliability="High",
                    flags=[],
                    enhanced=False,
                    metrics=Metrics(
                        sharpness=0.8,
                        face_size=90.0,
                        pose_yaw=3.0,
                        illumination=0.8,
                        occlusion=0.05,
                    ),
                    embedding_path="data/outputs/x/e101.npy",
                )
            ],
            requested_sample_fps=2.0,
            effective_sample_fps=1.0,
            warnings=[
                "Frame cap reached; sample_fps reduced automatically",
                "Low illumination detected in segment",
            ],
            coverage_start_sec=0.5,
            coverage_end_sec=3.5,
        )

    captured_index_kwargs: list[dict] = []

    def _custom_index(clip_path, **kwargs) -> IndexResult:
        captured_index_kwargs.append(dict(kwargs))
        from pipeline.fake_pipeline import index_clip as fake_idx

        base = fake_idx(clip_path=clip_path, out_dir=kwargs["out_dir"])
        return base.model_copy(
            update={
                "requested_sample_fps": 2.0,
                "effective_sample_fps": 1.5,
                "warnings": ["Index range capped for 600s budget"],
                "coverage_start_sec": 0.0,
                "coverage_end_sec": 4.0,
            }
        )

    import pipeline.adapter as adapter

    monkeypatch.setattr(adapter, "get_run", lambda: _custom_run)
    monkeypatch.setattr(adapter, "get_index_clip", lambda: _custom_index)

    proc = client.post(
        f"/clips/{clip_id}/process",
        headers=headers,
        json={"transaction_time": "2026-11-26T15:30:02", "window_sec": 1, "sample_fps": 2.0},
    )
    assert proc.status_code == 202
    run_id = proc.json()["run_id"]
    run_status = _poll_run(client, headers, run_id)
    assert run_status["status"] == "done"
    assert run_status["requested_sample_fps"] == 2.0
    assert run_status["effective_sample_fps"] == 1.0
    assert run_status["warnings"] == [
        "Frame cap reached; sample_fps reduced automatically",
        "Low illumination detected in segment",
    ]
    assert run_status["coverage_start_sec"] == 0.5
    assert run_status["coverage_end_sec"] == 3.5

    res_resp = client.get(f"/runs/{run_id}/result", headers=headers)
    assert res_resp.status_code == 200
    res_body = res_resp.json()
    assert res_body["requested_sample_fps"] == 2.0
    assert res_body["effective_sample_fps"] == 1.0
    assert res_body["warnings"] == [
        "Frame cap reached; sample_fps reduced automatically",
        "Low illumination detected in segment",
    ]
    assert res_body["coverage_start_sec"] == 0.5
    assert res_body["coverage_end_sec"] == 3.5

    # Verify DB persistence on Run.
    with client.app.state.session_factory() as db:
        row = db.get(Run, run_id)
        assert row is not None
        assert row.requested_sample_fps == 2.0
        assert row.effective_sample_fps == 1.0
        assert row.coverage_start_sec == 0.5
        assert row.coverage_end_sec == 3.5
        assert len(row.warnings or []) == 2

    # Verify PDF includes sampling line, reduced-sampling warning, and each warning line.
    pdf_resp = client.get(f"/runs/{run_id}/evidence.pdf", headers=headers)
    assert pdf_resp.status_code == 200
    extracted = _extract_pdf_text(pdf_resp.content)
    assert "Sampling: requested 2 fps, used 1 fps; coverage 0.5 s to 3.5 s of the clip" in extracted
    assert "Sampling was reduced; some brief appearances may be missed." in extracted
    assert "Frame cap reached; sample_fps reduced automatically" in extracted
    assert "Low illumination detected in segment" in extracted

    # Verify index job stores/returns new fields and gateway does NOT pass allow_truncate.
    idx_post = client.post(f"/clips/{clip_id}/index", headers=headers, json={})
    assert idx_post.status_code == 202
    index_id = idx_post.json()["index_id"]
    idx_detail = _poll_index(client, headers, index_id)
    assert idx_detail["status"] == "done"
    assert "allow_truncate" not in captured_index_kwargs[-1]
    assert idx_detail["requested_sample_fps"] == 2.0
    assert idx_detail["effective_sample_fps"] == 1.5
    assert idx_detail["warnings"] == ["Index range capped for 600s budget"]
    assert idx_detail["coverage_start_sec"] == 0.0
    assert idx_detail["coverage_end_sec"] == 4.0

    with client.app.state.session_factory() as db:
        idx_row = db.get(ClipIndex, index_id)
        assert idx_row is not None
        assert idx_row.requested_sample_fps == 2.0
        assert idx_row.effective_sample_fps == 1.5
        assert idx_row.coverage_start_sec == 0.0
        assert idx_row.coverage_end_sec == 4.0


def test_null_sampling_coverage_and_422_cap_still_work(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Null/older sampling metadata works cleanly in API & PDF, and 422 window cap stays enforced."""
    raw = _make_clip_bytes(tmp_path, "A_p10_null.mp4")
    headers = _auth_headers(client, username="inv_p10_null")
    up = client.post(
        "/clips",
        headers=headers,
        data={"atm_id": "atm_demo"},
        files={"file": ("A_p10_null.mp4", raw, "video/mp4")},
    )
    assert up.status_code == 201
    clip_id = up.json()["id"]

    # Existing 422 window cap remains unchanged: (2 * 50 + 2) * 2 = 204 > 200 -> 422.
    cap_resp = client.post(
        f"/clips/{clip_id}/process",
        headers=headers,
        json={"transaction_time": "2026-11-26T15:30:02", "window_sec": 50, "sample_fps": 2.0},
    )
    assert cap_resp.status_code == 422
    assert cap_resp.json()["code"] == "WINDOW_CAP_EXCEEDED"

    # Pipeline returning null sampling/coverage fields still completes and renders cleanly.
    def _null_run(clip_path, tx_offset_sec, window_sec=10, **kwargs) -> PipelineResult:
        return PipelineResult(
            clip_id=clip_id,
            transaction_time="2026-11-26T15:30:02",
            person_track_id=None,
            best_frames=[],
            link_confidence="Low",
            link_reason="No person entered zone",
            selection_reason="No candidate frames",
            requested_sample_fps=None,
            effective_sample_fps=None,
            warnings=[],
            coverage_start_sec=None,
            coverage_end_sec=None,
        )

    import pipeline.adapter as adapter

    monkeypatch.setattr(adapter, "get_run", lambda: _null_run)
    proc = client.post(
        f"/clips/{clip_id}/process",
        headers=headers,
        json={"transaction_time": "2026-11-26T15:30:02", "window_sec": 1, "sample_fps": 2.0},
    )
    assert proc.status_code == 202
    run_id = proc.json()["run_id"]
    run_status = _poll_run(client, headers, run_id)
    assert run_status["status"] == "done"
    assert run_status["requested_sample_fps"] is None
    assert run_status["effective_sample_fps"] is None
    assert run_status["warnings"] == []
    assert run_status["coverage_start_sec"] is None
    assert run_status["coverage_end_sec"] is None

    res_body = client.get(f"/runs/{run_id}/result", headers=headers).json()
    assert res_body["requested_sample_fps"] is None
    assert res_body["effective_sample_fps"] is None
    assert res_body["warnings"] == []
    assert res_body["coverage_start_sec"] is None
    assert res_body["coverage_end_sec"] is None

    # Older/null warnings row directly in DB also hydrates and renders PDF without crashing.
    with client.app.state.session_factory() as db:
        row = db.get(Run, run_id)
        row.warnings = None
        if isinstance(row.result_json, dict):
            updated_json = dict(row.result_json)
            updated_json.pop("warnings", None)
            row.result_json = updated_json
        db.commit()

    old_res = client.get(f"/runs/{run_id}/result", headers=headers)
    assert old_res.status_code == 200
    assert old_res.json()["warnings"] is None

    pdf_resp = client.get(f"/runs/{run_id}/evidence.pdf", headers=headers)
    assert pdf_resp.status_code == 200
    assert pdf_resp.content.startswith(b"%PDF")
    assert "Sampling was reduced" not in _extract_pdf_text(pdf_resp.content)
