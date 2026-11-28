"""Compare pipeline/frames.py timestamps against ffmpeg reference frames."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.frames import iter_sampled_frames, video_info


def _ffprobe_stream_info(video_path: Path) -> dict[str, str]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=r_frame_rate,avg_frame_rate,nb_frames,duration",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(video_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    payload = json.loads(proc.stdout)
    stream = (payload.get("streams") or [{}])[0]
    fmt = payload.get("format") or {}
    return {
        "r_frame_rate": str(stream.get("r_frame_rate", "N/A")),
        "avg_frame_rate": str(stream.get("avg_frame_rate", "N/A")),
        "nb_frames": str(stream.get("nb_frames", "N/A")),
        "duration": str(stream.get("duration") or fmt.get("duration") or "N/A"),
    }


def _ffmpeg_frame_160x90_gray(video_path: Path, t_sec: float, tmp_dir: Path, tag: str) -> object | None:
    import cv2

    out_png = tmp_dir / f"ff_{tag}.png"
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-ss",
        f"{max(0.0, t_sec):.4f}",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        str(out_png),
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0 or not out_png.exists():
        return None
    img = cv2.imread(str(out_png))
    if img is None:
        return None
    small = cv2.resize(img, (160, 90), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)


def _to_160x90_gray(bgr_frame: object) -> object:
    import cv2

    small = cv2.resize(bgr_frame, (160, 90), interpolation=cv2.INTER_AREA)  # type: ignore[arg-type]
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)


def _reader_frame_at(video_path: Path, t_sec: float) -> tuple[float, object] | None:
    start = max(0.0, t_sec - 0.5)
    end = t_sec + 0.5
    samples = list(iter_sampled_frames(video_path, start, end, sample_fps=4.0))
    if not samples:
        return None
    return min(samples, key=lambda pair: abs(pair[0] - t_sec))


def measure_drift(
    video_path: Path,
    times: list[float],
    search_sec: float = 3.0,
) -> list[dict[str, object]]:
    """Compare reader timestamps against ffmpeg reference frames at target times.

    Offsets are ordered by smallest abs(offset) first so static scenes with
    identical frames break ties cleanly at 0.00s instead of negative offsets.
    """
    import numpy as np

    raw_offsets = [round(-search_sec + 0.25 * i, 2) for i in range(int(round(2 * search_sec / 0.25)) + 1)]
    offsets = sorted(raw_offsets, key=lambda o: (abs(o), o))
    results: list[dict[str, object]] = []

    with tempfile.TemporaryDirectory() as tmpdir_str:
        tmp_dir = Path(tmpdir_str)
        for idx, t_sec in enumerate(times):
            picked = _reader_frame_at(video_path, t_sec)
            if picked is None:
                results.append({"t_sec": t_sec, "reader_t": None, "exact_mad": None, "best_offset": None, "best_mad": None, "drifted": False})
                continue
            reader_t, reader_bgr = picked
            reader_gray = _to_160x90_gray(reader_bgr)

            ff_exact = _ffmpeg_frame_160x90_gray(video_path, reader_t, tmp_dir, f"exact_{idx}_{t_sec:.2f}")
            exact_mad = (
                float(np.mean(np.abs(reader_gray.astype(np.float32) - ff_exact.astype(np.float32))))
                if ff_exact is not None
                else float("nan")
            )

            best_off = 0.0
            best_mad = float("inf")
            for off in offsets:
                probe_t = reader_t + off
                if probe_t < 0.0:
                    continue
                ff_off = _ffmpeg_frame_160x90_gray(video_path, probe_t, tmp_dir, f"off_{idx}_{t_sec:.2f}_{off:+.2f}")
                if ff_off is None:
                    continue
                mad = float(np.mean(np.abs(reader_gray.astype(np.float32) - ff_off.astype(np.float32))))
                if mad < best_mad - 1e-6:
                    best_mad = mad
                    best_off = off

            results.append(
                {
                    "t_sec": float(t_sec),
                    "reader_t": float(reader_t),
                    "exact_mad": float(exact_mad),
                    "best_offset": float(best_off) if best_mad < float("inf") else None,
                    "best_mad": float(best_mad) if best_mad < float("inf") else None,
                    "drifted": bool(best_mad < float("inf") and abs(best_off) > 0.25),
                }
            )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Check pipeline/frames.py timestamps against ffmpeg.")
    parser.add_argument("video", type=Path, help="Path to video file")
    parser.add_argument("--times", type=float, nargs="+", required=True, help="Timestamps in seconds")
    parser.add_argument("--search", type=float, default=3.0, help="Search half-window in seconds")
    args = parser.parse_args()

    probe = _ffprobe_stream_info(args.video)
    info = video_info(args.video)
    print(
        f"ffprobe: r_frame_rate={probe['r_frame_rate']}, avg_frame_rate={probe['avg_frame_rate']}, "
        f"nb_frames={probe['nb_frames']}, duration={probe['duration']}"
    )
    print(f"reader:  assumed_fps={info['fps']:.4f}, vfr_suspected={info.get('vfr_suspected', 'N/A')}")
    print()

    rows = measure_drift(args.video, args.times, search_sec=args.search)
    drift_detected = False
    for row in rows:
        if row["reader_t"] is None:
            print(f"t={row['t_sec']:.2f}s: reader returned no frame")
            continue
        msg = (
            f"t={row['t_sec']:>6.2f}s (reader_t={row['reader_t']:>6.2f}s) | "
            f"exact_mad={row['exact_mad']:>5.2f} | best_offset={row['best_offset']:+.2f}s (mad={row['best_mad']:>5.2f})"
        )
        if row["drifted"]:
            drift_detected = True
            msg += f"  --> TIMESTAMP DRIFT of about {row['best_offset']:+.2f} s"
        print(msg)

    return 1 if drift_detected else 0


if __name__ == "__main__":
    raise SystemExit(main())
