"""Phase 6A acceptance tests: zones, dict progress_cb, typed error_advice, margin & flag_scores."""

import re
import shutil
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app.models import FrameRecord, Run, User
from backend.app.security import hash_password
from pipeline.contract import Metrics
from pipeline.errors import (
    InvalidArgumentError,
    ModelLoadError,
    VideoNotFoundError,
    VideoUnreadableError,
    ZoneNotFoundError,
)


def _make_clip_bytes(tmp_path: Path, name: str = "A_p6a.mp4") -> bytes:
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


def _auth_headers(client: TestClient, username: str = "inv_p6a") -> dict[str, str]:
    pw = "Phase6APass123!"
    with client.app.state.session_factory() as db:
        db.add(
            User(
                username=username,
                password_hash=hash_password(pw),
                role="investigator",
                full_name="Phase 6A Tester",
                active=True,
            )
        )
        db.commit()
    resp = client.post("/auth/login", json={"username": username, "password": pw})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _upload(
    client: TestClient, headers: dict[str, str], raw: bytes, *, atm_id: str | None = "atm_demo"
) -> str:
    data = {"atm_id": atm_id} if atm_id is not None else {}
    resp = client.post(
        "/clips",
        headers=headers,
        data=data,
        files={"file": ("A_p6a.mp4", raw, "video/mp4")},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _poll(client: TestClient, headers: dict[str, str], run_id: int) -> dict:
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        body = client.get(f"/runs/{run_id}", headers=headers).json()
        if body["status"] in {"done", "failed"}:
            return body
        time.sleep(0.05)
    raise AssertionError(f"Run {run_id} did not finish")


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    raw = pdf_bytes.decode("latin1", errors="ignore")
    chunks = re.findall(r"\(((?:\\.|[^\\()])*)\)\s*Tj", raw)
    return " ".join(
        c.replace(r"\(", "(").replace(r"\)", ")").replace(r"\\", "\\") for c in chunks
    )


def test_zones_endpoint_and_zone_validation_rules(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /zones returns sorted zones; unknown atm_id returns 422 ZONE_NOT_FOUND; custom poly omits atm_id."""
    raw = _make_clip_bytes(tmp_path)
    headers = _auth_headers(client, username="inv_zones")

    assert client.get("/zones").status_code == 401
    zones_resp = client.get("/zones", headers=headers)
    assert zones_resp.status_code == 200
    zones = zones_resp.json()
    ids = [z["id"] for z in zones]
    assert ids == sorted(ids)
    assert ids == ["atm_01", "atm_155", "atm_217", "atm_40", "atm_demo"]
    assert all("note" in z and len(z["polygon"]) >= 3 for z in zones)

    clip_id = _upload(client, headers, raw, atm_id=None)

    # PATCH invalid polygons -> 422 ZONE_INVALID
    for bad_poly in (
        [[0.1, 0.1], [0.2, 0.2]],
        [[0.1, 0.1], [1.5, 0.2], [0.5, 0.5]],
        [[0.1, 0.1], [0.2], [0.5, 0.5]],
        "not-a-polygon",
    ):
        r = client.patch(
            f"/clips/{clip_id}",
            headers=headers,
            json={"zone_polygon_norm": bad_poly},
        )
        assert r.status_code == 422
        assert r.json()["code"] == "ZONE_INVALID"

    # Unknown atm_id when clip has no zone_polygon_norm -> 422 ZONE_NOT_FOUND with valid ids.
    bad_proc = client.post(
        f"/clips/{clip_id}/process",
        headers=headers,
        json={"transaction_time": "2026-11-26T15:30:02", "atm_id": "atm_unknown"},
    )
    assert bad_proc.status_code == 422
    assert bad_proc.json()["code"] == "ZONE_NOT_FOUND"
    for valid_id in ids:
        assert valid_id in bad_proc.json()["detail"]

    # When clip.zone_polygon_norm is set, gateway passes zone_polygon_norm and does NOT pass atm_id.
    poly = [[0.1, 0.1], [0.8, 0.1], [0.8, 0.9]]
    assert (
        client.patch(
            f"/clips/{clip_id}",
            headers=headers,
            json={"zone_polygon_norm": poly, "atm_id": "atm_demo"},
        ).status_code
        == 200
    )

    captured_kwargs: dict = {}

    def _spy_run(**kwargs):
        captured_kwargs.update(kwargs)
        from pipeline.fake_pipeline import run as fake_run

        return fake_run(
            clip_path=kwargs["clip_path"],
            tx_offset_sec=kwargs["tx_offset_sec"],
            window_sec=kwargs["window_sec"],
            zone_polygon_norm=kwargs.get("zone_polygon_norm"),
        )

    import pipeline.adapter as adapter

    monkeypatch.setattr(adapter, "get_run", lambda: _spy_run)
    ok_proc = client.post(
        f"/clips/{clip_id}/process",
        headers=headers,
        json={"transaction_time": "2026-11-26T15:30:02", "window_sec": 1},
    )
    assert ok_proc.status_code == 202
    assert _poll(client, headers, ok_proc.json()["run_id"])["status"] == "done"
    assert captured_kwargs.get("zone_polygon_norm") == poly
    assert "atm_id" not in captured_kwargs


def test_progress_cb_dict_updates_stage_fraction_and_message(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """progress_cb accepts a dict {stage, fraction, message} and stores them on Run."""
    raw = _make_clip_bytes(tmp_path)
    headers = _auth_headers(client, username="inv_prog")
    clip_id = _upload(client, headers, raw)

    observed_during_run: dict = {}

    def _progress_run(clip_path, tx_offset_sec, window_sec=10, progress_cb=None):
        assert progress_cb is not None
        progress_cb({"stage": "faces", "fraction": 0.7, "message": "Detecting faces (custom)"})
        # Also verify mid-run DB state before returning.
        with client.app.state.session_factory() as db:
            row = db.query(Run).order_by(Run.id.desc()).first()
            observed_during_run["stage"] = row.stage
            observed_during_run["progress"] = row.progress
            observed_during_run["progress_message"] = row.progress_message

        # Must swallow malformed payloads without raising.
        progress_cb({"fraction": "not-a-float"})

        from pipeline.fake_pipeline import run as fake_run

        return fake_run(clip_path=clip_path, tx_offset_sec=tx_offset_sec, window_sec=window_sec)

    import pipeline.adapter as adapter

    monkeypatch.setattr(adapter, "get_run", lambda: _progress_run)
    proc = client.post(
        f"/clips/{clip_id}/process",
        headers=headers,
        json={"transaction_time": "2026-11-26T15:30:02", "window_sec": 1},
    )
    assert proc.status_code == 202
    run_id = proc.json()["run_id"]
    final = _poll(client, headers, run_id)
    assert final["status"] == "done"
    assert observed_during_run == {
        "stage": "faces",
        "progress": 0.7,
        "progress_message": "Detecting faces (custom)",
    }
    assert final["stage"] == "done"
    assert final["progress"] == 1.0
    assert "Done" in final["progress_message"]


@pytest.mark.parametrize(
    ("exc_factory", "expected_code", "expected_advice"),
    [
        (
            lambda: VideoNotFoundError("missing clip file"),
            "VIDEO_NOT_FOUND",
            "The uploaded file is missing, re-upload it",
        ),
        (
            lambda: VideoUnreadableError("corrupt moov atom"),
            "VIDEO_UNREADABLE",
            "Export the clip as MP4 (H.264) from the DVR/NVR software or convert it with FFmpeg",
        ),
        (
            lambda: InvalidArgumentError("window_sec must be > 0"),
            "INVALID_ARGUMENT",
            "window_sec must be > 0",
        ),
        (
            lambda: ZoneNotFoundError("zone not found"),
            "ZONE_NOT_FOUND",
            "No ATM zone is stored for this clip, pick a known zone or draw one",
        ),
        (
            lambda: ModelLoadError("weights missing"),
            "MODEL_LOAD_ERROR",
            "The pipeline models failed to load, check the weights and GPU on the pipeline machine",
        ),
        (
            lambda: type("CustomModelLoad", (RuntimeError,), {"code": "MODEL_LOAD"})("gpu init failed"),
            "MODEL_LOAD",
            "The pipeline models failed to load, check the weights and GPU on the pipeline machine",
        ),
    ],
)
def test_typed_pipeline_errors_store_error_advice(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exc_factory,
    expected_code: str,
    expected_advice: str,
) -> None:
    """Typed pipeline errors store error_code, error_message, and error_advice without tracebacks."""
    raw = _make_clip_bytes(tmp_path)
    headers = _auth_headers(client, username=f"inv_err_{expected_code.lower()}")
    clip_id = _upload(client, headers, raw)

    def _failing_run(clip_path, tx_offset_sec, window_sec=10):
        raise exc_factory()

    import pipeline.adapter as adapter

    monkeypatch.setattr(adapter, "get_run", lambda: _failing_run)
    proc = client.post(
        f"/clips/{clip_id}/process",
        headers=headers,
        json={"transaction_time": "2026-11-26T15:30:02", "window_sec": 1},
    )
    run_id = proc.json()["run_id"]
    failed = _poll(client, headers, run_id)
    assert failed["status"] == "failed"
    assert failed["error_code"] == expected_code
    assert failed["error_advice"] == expected_advice
    assert "Traceback" not in (failed["error_message"] or "")


def test_link_low_margin_face_box_flag_scores_and_pdf(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stores/returns link_low_margin, face_box, flag_scores and renders them in the PDF."""
    raw = _make_clip_bytes(tmp_path)
    headers = _auth_headers(client, username="inv_flags")
    clip_id = _upload(client, headers, raw)

    def _rich_run(clip_path, tx_offset_sec, window_sec=10):
        return {
            "clip_id": clip_id,
            "transaction_time": "2026-11-26T15:30:02",
            "person_track_id": 2,
            "link_confidence": "Medium",
            "link_reason": "Two people entered within 1s",
            "link_low_margin": True,
            "selection_reason": "Selected highest quality face",
            "best_frames": [
                {
                    "frame_id": "f_0001",
                    "frame_path": "data/outputs/x/frame_1.jpg",
                    "crop_path": "data/outputs/x/crop_1.jpg",
                    "embedding_path": "data/outputs/x/emb_1.npy",
                    "timestamp_sec": 2.0,
                    "quality_score": 0.78,
                    "reliability": "Medium",
                    "flags": ["cap", "mask", "helmet"],
                    "flag_scores": {"cap": 0.71, "mask": 0.64},
                    "face_box": [120, 80, 210, 170],
                    "enhanced": False,
                    "enhancement": None,
                    "metrics": Metrics(
                        sharpness=0.75,
                        face_size=90.0,
                        pose_yaw=5.0,
                        illumination=0.7,
                        occlusion=0.2,
                    ).model_dump(),
                    "match_ready": True,
                    "rank_reason": "Clear frontal crop",
                }
            ],
        }

    import pipeline.adapter as adapter

    monkeypatch.setattr(adapter, "get_run", lambda: _rich_run)
    proc = client.post(
        f"/clips/{clip_id}/process",
        headers=headers,
        json={"transaction_time": "2026-11-26T15:30:02", "window_sec": 1},
    )
    run_id = proc.json()["run_id"]
    done = _poll(client, headers, run_id)
    assert done["status"] == "done"
    assert done["link_low_margin"] is True
    frame_out = done["result"]["best_frames"][0]
    assert done["result"]["link_low_margin"] is True
    assert frame_out["face_box"] == [120, 80, 210, 170]
    assert frame_out["flags"] == ["cap", "mask", "helmet"]
    assert frame_out["flag_scores"] == {"cap": 0.71, "mask": 0.64}

    with client.app.state.session_factory() as db:
        fr_db = db.query(FrameRecord).filter(FrameRecord.run_id == run_id).one()
        assert fr_db.face_box == [120, 80, 210, 170]
        assert fr_db.flag_scores == {"cap": 0.71, "mask": 0.64}

    pdf_resp = client.get(f"/runs/{run_id}/evidence.pdf", headers=headers)
    assert pdf_resp.status_code == 200
    text = _extract_pdf_text(pdf_resp.content)
    assert "link_low_margin=True" in text
    assert "cap (model estimate 0.71)" in text
    assert "mask (model estimate 0.64)" in text
    assert "Flags are model estimates and can be wrong in both directions. A human must verify." in text
