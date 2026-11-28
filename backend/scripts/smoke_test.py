"""End-to-end smoke test against a running Strix backend server.

Run from the repository root:
    STRIX_SMOKE_PASSWORD="..." python backend/scripts/smoke_test.py
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx


def _generate_test_clip(dest: Path) -> None:
    """Create a 4-second synthetic MP4 clip with creation_time using ffmpeg."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg binary not found on PATH")
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-v",
            "error",
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
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.strip()}")


def run_smoke_test(base_url: str, username: str, password: str) -> int:
    """Execute full workflow against base_url and print PASS/FAIL per step."""
    results: list[tuple[str, bool, str]] = []

    def record(step: str, ok: bool, detail: str) -> None:
        tag = "PASS" if ok else "FAIL"
        print(f"[{tag}] {step}: {detail}")
        results.append((step, ok, detail))

    with httpx.Client(base_url=base_url.rstrip("/"), timeout=30.0) as client:
        # 1. Health & Public Config
        try:
            h = client.get("/health")
            c = client.get("/config/public")
            assert h.status_code == 200 and h.json()["status"] == "ok"
            assert c.status_code == 200 and "notice" in c.json()
            record("health_and_config", True, f"mode={c.json()['pipeline_mode']}")
        except Exception as exc:
            record("health_and_config", False, str(exc))
            return 1

        # 2. Login
        try:
            login = client.post(
                "/auth/login",
                json={"username": username, "password": password},
            )
            assert login.status_code == 200, login.text
            token = login.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            record("login", True, f"user={username}")
        except Exception as exc:
            record("login", False, str(exc))
            return 1

        # 3. GET /zones
        try:
            z = client.get("/zones", headers=headers)
            assert z.status_code == 200, z.text
            zone_ids = [item["id"] for item in z.json()]
            assert "atm_demo" in zone_ids
            record("get_zones", True, f"zones={zone_ids}")
        except Exception as exc:
            record("get_zones", False, str(exc))
            return 1

        # 4. Generate & upload clip with atm_demo
        clip_id = ""
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                clip_path = Path(tmpdir) / "A_smoke_clip.mp4"
                _generate_test_clip(clip_path)
                with clip_path.open("rb") as fh:
                    up = client.post(
                        "/clips",
                        headers=headers,
                        data={"atm_id": "atm_demo", "notes": "smoke test"},
                        files={"file": ("A_smoke_clip.mp4", fh, "video/mp4")},
                    )
            assert up.status_code == 201, up.text
            clip_id = up.json()["id"]
            record("upload_clip", True, f"clip_id={clip_id}")
        except Exception as exc:
            record("upload_clip", False, str(exc))
            return 1

        # 5. Wait for auto-index job if queued
        try:
            idx_list = client.get(f"/clips/{clip_id}/indexes", headers=headers)
            assert idx_list.status_code == 200
            indexes = idx_list.json()
            if not indexes:
                record("auto_index", True, "no auto-index queued (AUTO_INDEX_ON_UPLOAD=0)")
            else:
                index_id = indexes[0]["index_id"]
                deadline = time.monotonic() + 30.0
                detail = {}
                while time.monotonic() < deadline:
                    r = client.get(f"/indexes/{index_id}", headers=headers)
                    assert r.status_code == 200
                    detail = r.json()
                    if detail["status"] in {"done", "failed"}:
                        break
                    time.sleep(0.1)
                assert detail.get("status") == "done", f"index failed: {detail}"
                record(
                    "auto_index",
                    True,
                    f"index_id={index_id}, embeddings={detail.get('total_embeddings')}",
                )
        except Exception as exc:
            record("auto_index", False, str(exc))

        # 6. Process clip and poll until done
        run_id = 0
        frame_ids: list[str] = []
        try:
            proc = client.post(
                f"/clips/{clip_id}/process",
                headers=headers,
                json={
                    "transaction_time": "2026-11-26T15:30:02",
                    "window_sec": 1,
                    "sample_fps": 2.0,
                    "tracker": "iou",
                },
            )
            assert proc.status_code == 202, proc.text
            run_id = proc.json()["run_id"]
            deadline = time.monotonic() + 45.0
            run_body: dict = {}
            while time.monotonic() < deadline:
                st = client.get(f"/runs/{run_id}", headers=headers)
                assert st.status_code == 200
                run_body = st.json()
                if run_body["status"] in {"done", "failed"}:
                    break
                time.sleep(0.1)
            assert run_body.get("status") == "done", f"run failed: {run_body}"
            frames = run_body["result"]["best_frames"]
            frame_ids = [str(f["frame_id"]) for f in frames]
            record("process_and_poll", True, f"run_id={run_id}, frames={len(frame_ids)}")
        except Exception as exc:
            record("process_and_poll", False, str(exc))
            return 1

        # 7. Select two frames
        try:
            chosen = frame_ids[:2]
            sel = client.post(
                f"/runs/{run_id}/selection",
                headers=headers,
                json={"frame_ids": chosen},
            )
            assert sel.status_code == 200, sel.text
            assert sel.json()["selected_frame_ids"] == chosen
            record("select_frames", True, f"selected={chosen}")
        except Exception as exc:
            record("select_frames", False, str(exc))

        # 8. Enhance one frame
        try:
            target_fid = frame_ids[0]
            enh = client.post(
                f"/runs/{run_id}/frames/{target_fid}/enhance",
                headers=headers,
                json={"crop_box": [160, 80, 120, 120], "scale": 4, "method": "lanczos"},
            )
            assert enh.status_code == 200, enh.text
            enh_body = enh.json()
            img_check = client.get(enh_body["enhanced_url"])
            assert img_check.status_code == 200 and img_check.content[:2] == b"\xff\xd8"
            record(
                "enhance_frame",
                True,
                f"frame_id={target_fid}, model={enh_body['model_version']}",
            )
        except Exception as exc:
            record("enhance_frame", False, str(exc))

        # 9. Search
        search_id = None
        try:
            sr = client.post(
                "/search",
                headers=headers,
                json={"run_id": run_id, "frame_id": frame_ids[0], "top_k": 5},
            )
            assert sr.status_code == 200, sr.text
            sr_body = sr.json()
            search_id = sr_body["search_id"]
            assert "notice" in sr_body
            record(
                "search",
                True,
                f"search_id={search_id}, matches={len(sr_body['matches'])}",
            )
        except Exception as exc:
            record("search", False, str(exc))

        # 10. Download evidence PDF
        try:
            q = f"?search_id={search_id}" if search_id is not None else ""
            pdf = client.get(f"/runs/{run_id}/evidence.pdf{q}", headers=headers)
            assert pdf.status_code == 200, pdf.text
            assert pdf.headers["content-type"] == "application/pdf"
            assert pdf.content.startswith(b"%PDF")
            record("evidence_pdf", True, f"bytes={len(pdf.content)}")
        except Exception as exc:
            record("evidence_pdf", False, str(exc))

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    failed = total - passed
    print(f"\nSmoke test summary: {passed}/{total} passed, {failed} failed")
    return 0 if failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Strix backend smoke test.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Server URL")
    parser.add_argument(
        "--username",
        default=os.environ.get("STRIX_SMOKE_USER", "investigator"),
        help="Login username",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("STRIX_SMOKE_PASSWORD")
        or os.environ.get("STRIX_INVESTIGATOR_PASSWORD")
        or "",
        help="Login password (or set STRIX_SMOKE_PASSWORD)",
    )
    args = parser.parse_args()
    if not args.password:
        print(
            "ERROR: Provide --password or set STRIX_SMOKE_PASSWORD.",
            file=sys.stderr,
        )
        return 2
    return run_smoke_test(args.base_url, args.username, args.password)


if __name__ == "__main__":
    raise SystemExit(main())
