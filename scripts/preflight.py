"""Preflight readiness check for Strix live/offline demos."""

import importlib.metadata as importlib_metadata
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


REQUIRED_PACKAGES = (
    "torch",
    "torchvision",
    "onnxruntime-gpu",
    "opencv-contrib-python",
    "numpy",
    "insightface",
    "open_clip_torch",
    "supervision",
    "pydantic",
    "pytest",
)
MEDIA_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".jpg", ".jpeg", ".png", ".npy", ".npz"}


def check_python_venv() -> tuple[str, str, str]:
    ver = sys.version_info
    ver_str = f"{ver.major}.{ver.minor}.{ver.micro}"
    in_venv = ".venv" in Path(sys.executable).parts
    ok_ver = (ver.major, ver.minor) in {(3, 10), (3, 11)}
    if in_venv and ok_ver:
        return ("python_venv", "PASS", f"{sys.executable} (Python {ver_str})")
    if not ok_ver:
        return ("python_venv", "FAIL", f"Python {ver_str} not 3.10/3.11 ({sys.executable})")
    return ("python_venv", "FAIL", f"Not running inside .venv ({sys.executable})")


def check_packages() -> tuple[str, str, str]:
    dists = {d.metadata["Name"].lower(): d.version for d in importlib_metadata.distributions() if d.metadata.get("Name")}
    missing = [p for p in REQUIRED_PACKAGES if p.lower() not in dists]
    if missing:
        return ("packages", "FAIL", f"Missing: {', '.join(missing)}")

    cv_pkgs = [n for n in dists if n.startswith("opencv-")]
    if cv_pkgs != ["opencv-contrib-python"]:
        return ("packages", "FAIL", f"Unexpected opencv packages: {cv_pkgs}")

    ort_pkgs = [n for n in dists if n.startswith("onnxruntime")]
    if ort_pkgs != ["onnxruntime-gpu"]:
        return ("packages", "FAIL", f"Unexpected onnxruntime packages: {ort_pkgs}")

    ultra = [n for n in dists if "ultralytics" in n]
    if ultra:
        return ("packages", "FAIL", f"Forbidden ultralytics packages: {ultra}")

    return ("packages", "PASS", f"All {len(REQUIRED_PACKAGES)} required packages OK, no ultralytics")


def check_cv2_ffmpeg() -> tuple[str, str, str]:
    import cv2

    has_sr = hasattr(cv2, "dnn_superres")
    has_ffmpeg = shutil.which("ffmpeg") is not None
    has_ffprobe = shutil.which("ffprobe") is not None
    if has_sr and has_ffmpeg and has_ffprobe:
        return ("cv2_ffmpeg", "PASS", "cv2.dnn_superres + ffmpeg + ffprobe available")
    problems = []
    if not has_sr:
        problems.append("missing cv2.dnn_superres")
    if not has_ffmpeg:
        problems.append("ffmpeg not on PATH")
    if not has_ffprobe:
        problems.append("ffprobe not on PATH")
    return ("cv2_ffmpeg", "FAIL", "; ".join(problems))


def check_gpu() -> tuple[str, str, str]:
    import onnxruntime as ort
    import torch

    smi_summary = "nvidia-smi unavailable"
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            smi_summary = proc.stdout.strip().splitlines()[0]
    except Exception:
        pass

    torch_cuda = torch.cuda.is_available()
    ort_provs = ort.get_available_providers()

    from pipeline.faces import get_active_provider, get_face_app

    get_face_app()
    active_ort = get_active_provider()
    detail = f"{smi_summary} | torch.cuda={torch_cuda} | ort_active={active_ort} (avail={ort_provs})"
    if active_ort != "CUDAExecutionProvider":
        return ("gpu", "WARN", f"faces run on CPU | {detail}")
    return ("gpu", "PASS", detail)


def check_models_offline() -> tuple[str, str, str]:
    model_dir = Path(os.environ.get("MODEL_DIR", "data/models"))
    if not model_dir.exists() or not os.access(model_dir, os.R_OK):
        return ("models_offline", "FAIL", f"MODEL_DIR unreadable: {model_dir}")

    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "verify_models.py")],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        return ("models_offline", "PASS", f"All 3 models loaded offline (MODEL_DIR={model_dir})")
    err = (proc.stdout + "\n" + proc.stderr).strip().splitlines()[-1] if (proc.stdout or proc.stderr) else "failed"
    return ("models_offline", "FAIL", err)


def check_disk_space(path: Path = REPO_ROOT) -> tuple[str, str, str]:
    free_gb = shutil.disk_usage(path).free / (1024.0 ** 3)
    if free_gb < 2.0:
        return ("disk_space", "FAIL", f"{free_gb:.2f} GB free (< 2 GB)")
    if free_gb < 5.0:
        return ("disk_space", "WARN", f"{free_gb:.2f} GB free (< 5 GB)")
    return ("disk_space", "PASS", f"{free_gb:.2f} GB free")


def check_git_status() -> tuple[str, str, str]:
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        porcelain = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
        ).stdout.strip()
        tracked = subprocess.run(
            ["git", "ls-files"], capture_output=True, text=True, check=True
        ).stdout.splitlines()
    except Exception as exc:
        return ("git_status", "WARN", f"git check failed: {exc}")

    tracked_media = [f for f in tracked if Path(f).suffix.lower() in MEDIA_EXTS]
    if tracked_media:
        return ("git_status", "FAIL", f"Media files tracked in git: {tracked_media[:5]}")
    clean = "clean" if not porcelain else f"dirty ({len(porcelain.splitlines())} items)"
    status = "PASS" if not porcelain else "WARN"
    return ("git_status", status, f"branch={branch}, tree={clean}, 0 tracked media")


def check_demo_pack() -> tuple[str, str, str]:
    from scripts.verify_offline import verify_demo_pack

    pack_dir = REPO_ROOT / "demo_pack"
    missing = verify_demo_pack(pack_dir)
    if missing:
        return ("demo_pack", "FAIL", f"{len(missing)} missing items (e.g. {missing[0]})")

    prev = os.environ.get("DEMO_PACK_DIR")
    prev_fake = os.environ.get("USE_FAKE_PIPELINE")
    try:
        os.environ["DEMO_PACK_DIR"] = str(pack_dir)
        os.environ.pop("USE_FAKE_PIPELINE", None)
        from pipeline.adapter import get_run

        t0 = time.perf_counter()
        res = get_run()(
            clip_path="data/samples/sample2.mp4",
            tx_offset_sec=155.0,
            window_sec=6.0,
            atm_id="atm_155",
        )
        dt = time.perf_counter() - t0
    finally:
        if prev is None:
            os.environ.pop("DEMO_PACK_DIR", None)
        else:
            os.environ["DEMO_PACK_DIR"] = prev
        if prev_fake is not None:
            os.environ["USE_FAKE_PIPELINE"] = prev_fake

    if not getattr(res, "served_from_demo_pack", False):
        return ("demo_pack", "FAIL", "atm_155 did not serve from demo_pack")
    if dt >= 10.0:
        return ("demo_pack", "FAIL", f"atm_155 cached run took {dt:.2f}s (>= 10s)")
    return ("demo_pack", "PASS", f"verified complete; atm_155 cached in {dt:.2f}s")


def check_live_smoke() -> tuple[str, str, str]:
    from pipeline.adapter import get_run
    from scripts.run_eval import load_manifest

    manifest_path = REPO_ROOT / "data" / "samples" / "manifest.csv"
    if not manifest_path.exists():
        return ("live_smoke", "FAIL", f"Manifest not found: {manifest_path}")

    cases = load_manifest(manifest_path)
    shortest = min(cases, key=lambda c: c.window_sec)

    prev = os.environ.pop("DEMO_PACK_DIR", None)
    prev_fake = os.environ.pop("USE_FAKE_PIPELINE", None)
    try:
        t0 = time.perf_counter()
        res: Any = get_run()(
            clip_path=shortest.clip,
            tx_offset_sec=shortest.tx_sec,
            window_sec=shortest.window_sec,
            atm_id=shortest.atm_id,
            out_dir=REPO_ROOT / "data" / "outputs" / "preflight_smoke",
        )
        total_s = time.perf_counter() - t0
    except Exception as exc:
        return ("live_smoke", "FAIL", f"{shortest.case_id} raised {type(exc).__name__}: {exc}")
    finally:
        if prev is not None:
            os.environ["DEMO_PACK_DIR"] = prev
        if prev_fake is not None:
            os.environ["USE_FAKE_PIPELINE"] = prev_fake

    timings = ", ".join(f"{k}={v:.0f}ms" for k, v in (res.timings_ms or {}).items())
    return ("live_smoke", "PASS", f"{shortest.case_id} (w={shortest.window_sec}s) in {total_s:.2f}s [{timings}]")


def check_internet() -> tuple[str, str, str]:
    try:
        sock = socket.create_connection(("1.1.1.1", 443), timeout=2.0)
        sock.close()
        return ("internet", "INFO", "reachable (not required for demo)")
    except OSError:
        return ("internet", "INFO", "offline (not required for demo)")


def run_all_checks() -> list[tuple[str, str, str]]:
    return [
        check_python_venv(),
        check_packages(),
        check_cv2_ffmpeg(),
        check_gpu(),
        check_models_offline(),
        check_disk_space(),
        check_git_status(),
        check_demo_pack(),
        check_live_smoke(),
        check_internet(),
    ]


def main() -> int:
    results = run_all_checks()
    print(f"\n{'Check':<16}  {'Status':<6}  {'Detail'}")
    print("-" * 92)
    has_fail = False
    for name, status, detail in results:
        if status == "FAIL":
            has_fail = True
        print(f"{name:<16}  {status:<6}  {detail}")
    return 1 if has_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
