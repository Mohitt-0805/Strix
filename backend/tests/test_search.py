"""Phase 5 acceptance tests: search index (FAISS & NumPy), /search, /searches/{id}, /index."""

import logging
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app.config import HUMAN_VERIFICATION_NOTICE, Settings
from backend.app.main import create_app
from backend.app.models import AuditLog, Search, User
from backend.app.routes.search import SCORE_NOTE, SEARCH_SCOPE
from backend.app.security import hash_password
from backend.app.services.fake_assets import generate_person_embedding
from backend.app.services.search_index import IndexItem, SearchIndex


def _make_clip_bytes(tmp_path: Path, name: str) -> bytes:
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


def _create_headers(client: TestClient, username: str = "inv_search") -> dict[str, str]:
    pw = "SearchPass123!"
    with client.app.state.session_factory() as db:
        db.add(
            User(
                username=username,
                password_hash=hash_password(pw),
                role="investigator",
                full_name="Search Tester",
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
        data={"atm_id": "ATM-501"},
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
            raise AssertionError(f"Run {run_id} failed: {st}")
        time.sleep(0.05)
    raise AssertionError(f"Run {run_id} timed out")


def test_search_same_person_ranks_higher_excludes_query_clip_and_rebuilds(
    test_settings: Settings, tmp_path: Path
) -> None:
    """Same person key matches higher than different person; query clip excluded; startup rebuilds."""
    clip_bytes = _make_clip_bytes(tmp_path, "base.mp4")

    with TestClient(create_app(test_settings)) as client:
        headers = _create_headers(client)
        clip_a1, run_a1 = _upload_and_process(client, headers, "A_one.mp4", clip_bytes)
        clip_a2, _run_a2 = _upload_and_process(client, headers, "A_two.mp4", clip_bytes)
        clip_b1, _run_b1 = _upload_and_process(client, headers, "B_one.mp4", clip_bytes)

        search_resp = client.post(
            "/search",
            headers=headers,
            json={"run_id": run_a1, "frame_id": 142, "top_k": 10},
        )
        assert search_resp.status_code == 200, search_resp.text
        body = search_resp.json()

        assert body["notice"] == HUMAN_VERIFICATION_NOTICE
        assert body["score_note"] == SCORE_NOTE
        assert body["scope"] == SEARCH_SCOPE
        assert body["frame_id"] == "142"

        matches = body["matches"]
        assert len(matches) == 6  # 3 frames from A_two + 3 frames from B_one
        assert all(m["clip_id"] != clip_a1 for m in matches)

        a2_scores = [m["score"] for m in matches if m["clip_id"] == clip_a2]
        b1_scores = [m["score"] for m in matches if m["clip_id"] == clip_b1]
        assert min(a2_scores) > 0.9
        assert max(b1_scores) < 0.3
        assert matches[0]["clip_id"] == clip_a2

        # Signed URLs on matches work directly and point to the right files (frame vs crop).
        for m in matches:
            frame_p = parse_qs(urlparse(m["frame_url"]).query)["p"][0]
            crop_p = parse_qs(urlparse(m["crop_url"]).query)["p"][0]
            assert frame_p.endswith(f"/frame_{m['frame_id']}.jpg")
            assert crop_p.endswith(f"/crop_{m['frame_id']}.jpg")
        assert client.get(matches[0]["crop_url"]).status_code == 200
        assert client.get(matches[0]["frame_url"]).status_code == 200

        # Saved in searches table and retrievable via GET /searches/{id}.
        search_id = body["search_id"]
        saved_resp = client.get(f"/searches/{search_id}", headers=headers)
        assert saved_resp.status_code == 200
        assert saved_resp.json()["matches"][0]["clip_id"] == clip_a2

        with client.app.state.session_factory() as db:
            assert db.get(Search, search_id) is not None
            assert db.query(AuditLog).filter(AuditLog.action == "search").count() == 1

        # POST /clips/{id}/index returns 501 NOT_AVAILABLE while pipeline.index_clip is absent.
        idx_resp = client.post(f"/clips/{clip_a1}/index", headers=headers)
        assert idx_resp.status_code == 501
        assert idx_resp.json()["code"] == "NOT_AVAILABLE"

    # Restart app against the same DB/DATA_DIR: SearchIndex rebuilds automatically at startup.
    with TestClient(create_app(test_settings)) as restarted_client:
        assert restarted_client.app.state.search_index.count() == 9
        login = restarted_client.post(
            "/auth/login", json={"username": "inv_search", "password": "SearchPass123!"}
        )
        restarted_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        again = restarted_client.post(
            "/search",
            headers=restarted_headers,
            json={"run_id": run_a1, "frame_id": "142", "top_k": 3},
        )
        assert again.status_code == 200
        assert again.json()["matches"][0]["clip_id"] == clip_a2


def test_search_index_skips_wrong_dim_and_nan_and_renormalizes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Wrong-dim, NaN, and zero vectors are skipped with warnings; valid vectors re-normalised."""
    caplog.set_level(logging.WARNING)
    idx = SearchIndex(embed_dim=512, backend="numpy")

    valid_unnorm = generate_person_embedding("A", "k1") * 5.0
    wrong_dim = np.ones(128, dtype=np.float32)
    nan_vec = np.ones(512, dtype=np.float32)
    nan_vec[0] = np.nan

    added = idx.add(
        [
            IndexItem("c1", "c1.mp4", 1, "1", 1.0, "High", (), "outputs/c1/f1.jpg", None, wrong_dim),
            IndexItem("c1", "c1.mp4", 1, "2", 2.0, "High", (), "outputs/c1/f2.jpg", None, nan_vec),
            IndexItem("c2", "c2.mp4", 2, "3", 3.0, "High", (), "outputs/c2/f3.jpg", None, valid_unnorm),
        ]
    )
    assert added == 1
    assert idx.count() == 1
    assert "Skipping" in caplog.text

    hits = idx.search(valid_unnorm, top_k=5, exclude_clip_id="c_other")
    assert len(hits) == 1
    assert hits[0].score == pytest.approx(1.0, abs=1e-5)

    assert idx.remove_run(2) == 1
    assert idx.count() == 0


def test_numpy_and_faiss_backends_agree() -> None:
    """NumPy fallback and FAISS IndexFlatIP produce identical ranking and scores."""
    try:
        import faiss  # noqa: F401
    except ImportError:
        pytest.skip("faiss-cpu not installed")

    np_index = SearchIndex(embed_dim=512, backend="numpy")
    faiss_index = SearchIndex(embed_dim=512, backend="faiss")

    items = [
        IndexItem("clipA1", "A_1.mp4", 1, "10", 1.0, "High", (), "outputs/a1/f.jpg", "outputs/a1/c.jpg", generate_person_embedding("A", "n1")),
        IndexItem("clipA2", "A_2.mp4", 2, "20", 2.0, "High", (), "outputs/a2/f.jpg", "outputs/a2/c.jpg", generate_person_embedding("A", "n2")),
        IndexItem("clipB1", "B_1.mp4", 3, "30", 3.0, "Medium", ("blur",), "outputs/b1/f.jpg", None, generate_person_embedding("B", "n3")),
        IndexItem("clipC1", "C_1.mp4", 4, "40", 4.0, "Low", ("low light",), "outputs/c1/f.jpg", None, generate_person_embedding("C", "n4")),
    ]
    np_index.add(items)
    faiss_index.add(items)
    assert np_index.count() == faiss_index.count() == 4

    query = generate_person_embedding("A", "n1")
    np_hits = np_index.search(query, top_k=10, exclude_clip_id="clipA1")
    faiss_hits = faiss_index.search(query, top_k=10, exclude_clip_id="clipA1")

    assert [(h.clip_id, h.frame_id) for h in np_hits] == [
        (h.clip_id, h.frame_id) for h in faiss_hits
    ]
    for h_np, h_faiss in zip(np_hits, faiss_hits):
        assert h_np.score == pytest.approx(h_faiss.score, abs=1e-5)
    assert np_hits[0].clip_id == "clipA2"
