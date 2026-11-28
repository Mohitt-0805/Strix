"""Phase 9 acceptance tests: demo pack external asset ingestion, flags, PDF notice & zone rules."""

import logging
import re
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.models import FrameRecord, IndexFaceRecord, User
from backend.app.security import hash_password
from backend.tests.conftest import TEST_JWT_SECRET
from pipeline.contract import (
    Enhancement,
    Frame,
    IndexFace,
    IndexResult,
    IndexTrack,
    Metrics,
    PipelineResult,
)


def _make_clip_bytes(tmp_path: Path, name: str = "demo_clip.mp4") -> bytes:
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


def _auth_headers(client: TestClient, username: str = "inv_p9") -> dict[str, str]:
    pw = "Phase9Pass123!"
    with client.app.state.session_factory() as db:
        db.add(
            User(
                username=username,
                password_hash=hash_password(pw),
                role="investigator",
                full_name="Phase 9 Tester",
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


def _write_jpg(path: Path, size: tuple[int, int] = (160, 120), color=(30, 90, 150)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color=color).save(path, format="JPEG", quality=90)


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    raw = pdf_bytes.decode("latin1", errors="ignore")
    chunks = re.findall(r"\(((?:\\.|[^\\()])*)\)\s*Tj", raw)
    return " ".join(
        c.replace(r"\(", "(").replace(r"\)", ")").replace(r"\\", "\\") for c in chunks
    )


def test_config_public_reports_demo_pack_enabled(tmp_path: Path) -> None:
    """GET /config/public reports demo_pack_enabled=False when unset and True when set."""
    s_off = Settings(
        _env_file=None,
        USE_FAKE_PIPELINE=False,
        DATA_DIR=tmp_path / "d_off",
        JWT_SECRET=TEST_JWT_SECRET,
    )
    with TestClient(create_app(s_off)) as c_off:
        r_off = c_off.get("/config/public")
        assert r_off.status_code == 200
        assert r_off.json()["demo_pack_enabled"] is False

    pack_dir = tmp_path / "my_demo_pack"
    pack_dir.mkdir(parents=True, exist_ok=True)
    s_on = Settings(
        _env_file=None,
        USE_FAKE_PIPELINE=False,
        DEMO_PACK_DIR=str(pack_dir),
        DATA_DIR=tmp_path / "d_on",
        JWT_SECRET=TEST_JWT_SECRET,
    )
    with TestClient(create_app(s_on)) as c_on:
        r_on = c_on.get("/config/public")
        assert r_on.status_code == 200
        assert r_on.json()["demo_pack_enabled"] is True


def test_demo_pack_run_copies_external_assets_sets_flag_and_pdf_notice(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """External absolute demo-pack paths are copied inside DATA_DIR, served_from_demo_pack=True works."""
    raw = _make_clip_bytes(tmp_path)
    headers = _auth_headers(client, username="inv_dp_run")
    up = client.post(
        "/clips",
        headers=headers,
        data={"atm_id": "atm_demo"},
        files={"file": ("demo_clip.mp4", raw, "video/mp4")},
    )
    assert up.status_code == 201
    clip_id = up.json()["id"]

    # External folder outside DATA_DIR containing demo-pack assets (and one missing crop).
    ext_root = tmp_path / "external_demo_pack"
    f1_jpg = ext_root / "frames" / "dp_frame_142.jpg"
    c1_jpg = ext_root / "crops" / "dp_crop_142.jpg"
    enh1_jpg = ext_root / "enh" / "dp_crop_142_enh_x4.jpg"
    e1_npy = ext_root / "embs" / "dp_emb_142.npy"
    f2_jpg = ext_root / "frames" / "dp_frame_158.jpg"
    missing_crop = ext_root / "crops" / "missing_crop_158.jpg"
    e2_npy = ext_root / "embs" / "dp_emb_158.npy"

    _write_jpg(f1_jpg, (320, 240))
    _write_jpg(c1_jpg, (96, 96))
    _write_jpg(enh1_jpg, (192, 192), color=(200, 30, 30))
    _write_jpg(f2_jpg, (320, 240))
    vec = np.ones(512, dtype=np.float32)
    vec /= np.linalg.norm(vec)
    e1_npy.parent.mkdir(parents=True, exist_ok=True)
    np.save(e1_npy, vec)
    np.save(e2_npy, vec)

    def _demo_pack_run(
        clip_path,
        tx_offset_sec,
        window_sec=10,
        atm_id="",
        transaction_time=None,
        **kwargs,
    ) -> PipelineResult:
        return PipelineResult(
            clip_id=Path(clip_path).stem,
            transaction_time=transaction_time or "2026-11-26T15:30:02.123000",
            person_track_id=1,
            served_from_demo_pack=True,
            link_confidence="High",
            link_reason="Cached manifest match",
            best_frames=[
                Frame(
                    frame_id="142",
                    frame_path=str(f1_jpg.resolve()),
                    crop_path=str(c1_jpg.resolve()),
                    embedding_path=str(e1_npy.resolve()),
                    timestamp_sec=1.5,
                    quality_score=0.91,
                    reliability="High",
                    flags=[],
                    enhanced=True,
                    enhancement=Enhancement(
                        enhanced_path=str(enh1_jpg.resolve()),
                        method="lanczos",
                        scale=4,
                        model_version="lanczos_v1",
                        crop_box=[10, 10, 48, 48],
                        search_embedding_source="original",
                    ),
                    metrics=Metrics(
                        sharpness=0.9,
                        face_size=80.0,
                        pose_yaw=2.0,
                        illumination=0.8,
                        occlusion=0.05,
                    ),
                ),
                Frame(
                    frame_id="158",
                    frame_path=str(f2_jpg.resolve()),
                    crop_path=str(missing_crop.resolve()),
                    embedding_path=str(e2_npy.resolve()),
                    timestamp_sec=2.0,
                    quality_score=0.72,
                    reliability="Medium",
                    flags=["blur"],
                    enhanced=False,
                    metrics=Metrics(
                        sharpness=0.6,
                        face_size=64.0,
                        pose_yaw=8.0,
                        illumination=0.7,
                        occlusion=0.1,
                    ),
                ),
            ],
        )

    import pipeline.adapter as adapter

    monkeypatch.setattr(adapter, "get_run", lambda: _demo_pack_run)

    with caplog.at_level(logging.WARNING):
        proc = client.post(
            f"/clips/{clip_id}/process",
            headers=headers,
            json={"transaction_time": "2026-11-26T15:30:02.123456", "window_sec": 1},
        )
    assert proc.status_code == 202
    run_id = proc.json()["run_id"]
    done = _poll_run(client, headers, run_id)
    assert done["status"] == "done"
    assert done["tx_offset_sec"] == pytest.approx(2.123, abs=1e-6)
    assert done["served_from_demo_pack"] is True
    assert any("missing_crop_158.jpg" in rec.message for rec in caplog.records)

    res_resp = client.get(f"/runs/{run_id}/result", headers=headers)
    assert res_resp.status_code == 200
    res_body = res_resp.json()
    assert res_body["served_from_demo_pack"] is True

    data_root = client.app.state.settings.resolved_data_dir
    expected_prefix = f"outputs/{clip_id}/run_{run_id}/"
    fr142, fr158 = res_body["best_frames"]

    # Paths are inside DATA_DIR/outputs/<clip_id>/run_<run_id>/ keeping original filenames.
    assert fr142["frame_path"] == f"{expected_prefix}dp_frame_142.jpg"
    assert fr142["crop_path"] == f"{expected_prefix}dp_crop_142.jpg"
    assert fr142["embedding_path"] == f"{expected_prefix}dp_emb_142.npy"
    assert fr142["enhancement"]["enhanced_path"] == f"{expected_prefix}dp_crop_142_enh_x4.jpg"
    for rel in (
        fr142["frame_path"],
        fr142["crop_path"],
        fr142["embedding_path"],
        fr142["enhancement"]["enhanced_path"],
    ):
        assert (data_root / rel).is_file()

    # Signed URLs work via /files without Authorization header.
    assert client.get(fr142["image_url"]).status_code == 200
    assert client.get(fr142["crop_url"]).status_code == 200
    assert client.get(fr142["enhanced_url"]).status_code == 200

    # Missing source crop gave null crop_path and null crop_url cleanly.
    assert fr158["crop_path"] is None
    assert fr158["crop_url"] is None
    assert client.get(fr158["image_url"]).status_code == 200

    # DB rows never store paths outside DATA_DIR.
    with client.app.state.session_factory() as db:
        rows = db.query(FrameRecord).filter(FrameRecord.run_id == run_id).all()
        assert len(rows) == 2
        for row in rows:
            for col in (row.frame_path_rel, row.crop_path_rel, row.embedding_path_rel):
                if col is not None:
                    assert not Path(col).is_absolute()
                    assert col.startswith(expected_prefix)

    # Evidence PDF prints exact demo pack notice line.
    pdf_resp = client.get(f"/runs/{run_id}/evidence.pdf", headers=headers)
    assert pdf_resp.status_code == 200
    assert pdf_resp.content.startswith(b"%PDF")
    extracted = _extract_pdf_text(pdf_resp.content)
    assert "RESULT SERVED FROM A PRE-COMPUTED DEMO PACK (not computed live for this upload)" in extracted


def test_demo_pack_index_copies_external_assets_and_sets_flag(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """External absolute demo-pack index paths are copied inside DATA_DIR and served_from_demo_pack=True is returned."""
    raw = _make_clip_bytes(tmp_path, "idx_clip.mp4")
    headers = _auth_headers(client, username="inv_dp_idx")
    up = client.post(
        "/clips",
        headers=headers,
        data={"atm_id": "atm_demo"},
        files={"file": ("idx_clip.mp4", raw, "video/mp4")},
    )
    assert up.status_code == 201
    clip_id = up.json()["id"]

    ext_idx = tmp_path / "external_index_pack"
    ext_npz = ext_idx / "index.npz"
    ext_json = ext_idx / "index.json"
    ext_frame = ext_idx / "t1_frame.jpg"
    ext_crop = ext_idx / "t1_crop.jpg"
    ext_emb = ext_idx / "t1_emb.npy"
    ext_npz.parent.mkdir(parents=True, exist_ok=True)
    ext_npz.write_bytes(b"NPZ")
    ext_json.write_text("{}", encoding="utf-8")
    _write_jpg(ext_frame, (320, 240))
    _write_jpg(ext_crop, (96, 96))
    vec = np.ones(512, dtype=np.float32)
    vec /= np.linalg.norm(vec)
    np.save(ext_emb, vec)

    def _demo_pack_index(clip_path, **kwargs) -> IndexResult:
        return IndexResult(
            clip_id=clip_id,
            start_sec=0.0,
            end_sec=4.0,
            index_npz_path=str(ext_npz.resolve()),
            index_json_path=str(ext_json.resolve()),
            total_embeddings=1,
            served_from_demo_pack=True,
            tracks=[
                IndexTrack(
                    track_id=1,
                    first_t=0.5,
                    last_t=2.5,
                    n_observations=3,
                    short_track=False,
                    faces=[
                        IndexFace(
                            t=1.0,
                            quality_score=0.88,
                            reliability="High",
                            match_ready=True,
                            flags=[],
                            face_box=[10.0, 10.0, 70.0, 70.0],
                            crop_path=str(ext_crop.resolve()),
                            frame_path=str(ext_frame.resolve()),
                            embedding_path=str(ext_emb.resolve()),
                        )
                    ],
                )
            ],
        )

    import pipeline.adapter as adapter

    monkeypatch.setattr(adapter, "get_index_clip", lambda: _demo_pack_index)

    start_resp = client.post(f"/clips/{clip_id}/index", headers=headers, json={})
    assert start_resp.status_code == 202
    index_id = start_resp.json()["index_id"]
    done = _poll_index(client, headers, index_id)
    assert done["status"] == "done"
    assert done["served_from_demo_pack"] is True

    list_resp = client.get(f"/clips/{clip_id}/indexes", headers=headers)
    assert list_resp.status_code == 200
    assert list_resp.json()[0]["served_from_demo_pack"] is True

    expected_prefix = f"outputs/{clip_id}/index_{index_id}/"
    data_root = client.app.state.settings.resolved_data_dir
    for fname in ("index.npz", "index.json", "t1_frame.jpg", "t1_crop.jpg", "t1_emb.npy"):
        assert (data_root / expected_prefix / fname).is_file()

    face = done["tracks"][0]["faces"][0]
    assert client.get(face["crop_url"]).status_code == 200
    assert client.get(face["frame_url"]).status_code == 200

    with client.app.state.session_factory() as db:
        f_row = db.query(IndexFaceRecord).filter(IndexFaceRecord.index_id == index_id).one()
        assert f_row.crop_rel == f"{expected_prefix}t1_crop.jpg"
        assert f_row.frame_rel == f"{expected_prefix}t1_frame.jpg"
        assert f_row.embedding_rel == f"{expected_prefix}t1_emb.npy"


def test_gateway_atm_id_and_polygon_rules_for_run_and_index(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Known atm_id + polygon -> both passed; unknown atm_id + polygon -> omitted; unknown without polygon -> 422."""
    raw = _make_clip_bytes(tmp_path, "zone_clip.mp4")
    headers = _auth_headers(client, username="inv_dp_zone")
    up = client.post(
        "/clips",
        headers=headers,
        files={"file": ("zone_clip.mp4", raw, "video/mp4")},
    )
    assert up.status_code == 201
    clip_id = up.json()["id"]

    # Unknown atm_id without polygon -> 422 for both process and index.
    assert (
        client.post(
            f"/clips/{clip_id}/process",
            headers=headers,
            json={"transaction_time": "2026-11-26T15:30:02", "atm_id": "unknown_free_text"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/clips/{clip_id}/index",
            headers=headers,
            json={"atm_id": "unknown_free_text"},
        ).status_code
        == 422
    )

    # Set polygon on clip.
    poly = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]]
    assert (
        client.patch(
            f"/clips/{clip_id}",
            headers=headers,
            json={"zone_polygon_norm": poly, "atm_id": "atm_demo"},
        ).status_code
        == 200
    )

    run_kwargs_log: list[dict] = []
    idx_kwargs_log: list[dict] = []

    def _spy_run(**kwargs):
        run_kwargs_log.append(dict(kwargs))
        from pipeline.fake_pipeline import run as fake_run

        return fake_run(
            clip_path=kwargs["clip_path"],
            tx_offset_sec=kwargs["tx_offset_sec"],
            window_sec=kwargs["window_sec"],
            zone_polygon_norm=kwargs.get("zone_polygon_norm"),
            atm_id=kwargs.get("atm_id", ""),
        )

    def _spy_index(**kwargs):
        idx_kwargs_log.append(dict(kwargs))
        from pipeline.fake_pipeline import index_clip as fake_idx

        return fake_idx(
            clip_path=kwargs["clip_path"],
            out_dir=kwargs["out_dir"],
            zone_polygon_norm=kwargs.get("zone_polygon_norm"),
            atm_id=kwargs.get("atm_id"),
        )

    import pipeline.adapter as adapter

    monkeypatch.setattr(adapter, "get_run", lambda: _spy_run)
    monkeypatch.setattr(adapter, "get_index_clip", lambda: _spy_index)

    # Known atm_id with polygon -> passed to run and index.
    r1 = client.post(
        f"/clips/{clip_id}/process",
        headers=headers,
        json={"transaction_time": "2026-11-26T15:30:02", "window_sec": 1, "atm_id": "atm_demo"},
    )
    assert r1.status_code == 202
    assert _poll_run(client, headers, r1.json()["run_id"])["status"] == "done"
    assert run_kwargs_log[-1]["atm_id"] == "atm_demo"
    assert run_kwargs_log[-1]["zone_polygon_norm"] == poly

    i1 = client.post(f"/clips/{clip_id}/index", headers=headers, json={"atm_id": "atm_demo"})
    assert i1.status_code == 202
    assert _poll_index(client, headers, i1.json()["index_id"])["status"] == "done"
    assert idx_kwargs_log[-1]["atm_id"] == "atm_demo"
    assert idx_kwargs_log[-1]["zone_polygon_norm"] == poly

    # Unknown free-text atm_id with polygon -> omitted from run and index kwargs.
    r2 = client.post(
        f"/clips/{clip_id}/process",
        headers=headers,
        json={"transaction_time": "2026-11-26T15:30:02", "window_sec": 1, "atm_id": "free-text-cam-9"},
    )
    assert r2.status_code == 202
    assert _poll_run(client, headers, r2.json()["run_id"])["status"] == "done"
    assert "atm_id" not in run_kwargs_log[-1]
    assert run_kwargs_log[-1]["zone_polygon_norm"] == poly

    i2 = client.post(
        f"/clips/{clip_id}/index",
        headers=headers,
        json={"atm_id": "free-text-cam-9"},
    )
    assert i2.status_code == 202
    assert _poll_index(client, headers, i2.json()["index_id"])["status"] == "done"
    assert "atm_id" not in idx_kwargs_log[-1]
    assert idx_kwargs_log[-1]["zone_polygon_norm"] == poly
