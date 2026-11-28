"""Inspect true video frame PTS via ffprobe and compare against pipeline.frames timestamps and content."""

import argparse
from bisect import bisect_left
import json
from pathlib import Path
import random
import statistics
import subprocess
import sys
import tempfile
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.frames import iter_sampled_frames, video_info


def _pick_float(record: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for k in keys:
        val = record.get(k)
        if val is not None and val != "N/A":
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None


def read_true_pts(video_path: Path) -> dict[str, Any]:
    """Read presentation timestamps (sorted for display order) from ffprobe frames, falling back to packets."""
    cmd_frames = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_frames",
        "-show_entries",
        "frame=pts_time,pkt_pts_time,best_effort_timestamp_time",
        "-show_entries",
        "stream=start_time:format=start_time",
        "-of",
        "json",
        str(video_path),
    ]
    proc = subprocess.run(cmd_frames, capture_output=True, text=True, check=True)
    payload = json.loads(proc.stdout)

    pts_list: list[float] = []
    source = "frames"
    for fr in payload.get("frames", []):
        v = _pick_float(fr, ("pts_time", "best_effort_timestamp_time", "pkt_pts_time"))
        if v is not None:
            pts_list.append(v)

    if not pts_list:
        source = "packets"
        cmd_pkts = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_packets",
            "-show_entries",
            "packet=pts_time,dts_time",
            "-show_entries",
            "stream=start_time:format=start_time",
            "-of",
            "json",
            str(video_path),
        ]
        proc_p = subprocess.run(cmd_pkts, capture_output=True, text=True, check=True)
        payload_p = json.loads(proc_p.stdout)
        for pkt in payload_p.get("packets", []):
            v = _pick_float(pkt, ("pts_time", "dts_time"))
            if v is not None:
                pts_list.append(v)
        if not payload.get("streams") and payload_p.get("streams"):
            payload = payload_p

    pts_list.sort()
    streams = payload.get("streams") or [{}]
    fmt = payload.get("format") or {}
    stream_start = _pick_float(streams[0], ("start_time",))
    format_start = _pick_float(fmt, ("start_time",))

    gaps = [pts_list[i + 1] - pts_list[i] for i in range(len(pts_list) - 1)]
    med_gap = float(statistics.median(gaps)) if gaps else 0.0
    large_gaps = [
        {"idx": i, "t0": round(pts_list[i], 4), "t1": round(pts_list[i + 1], 4), "gap": round(g, 4)}
        for i, g in enumerate(gaps)
        if med_gap > 0.0 and g > 2.0 * med_gap
    ]
    large_gaps_sorted = sorted(large_gaps, key=lambda d: d["gap"], reverse=True)

    return {
        "source": source,
        "pts": pts_list,
        "frame_count": len(pts_list),
        "first_pts": pts_list[0] if pts_list else None,
        "last_pts": pts_list[-1] if pts_list else None,
        "median_gap": med_gap,
        "large_gap_count": len(large_gaps),
        "largest_gaps": large_gaps_sorted[:5],
        "stream_start_time": stream_start,
        "format_start_time": format_start,
    }


def _nearest_pts(sorted_pts: list[float], target: float) -> float:
    pos = bisect_left(sorted_pts, target)
    if pos == 0:
        return sorted_pts[0]
    if pos >= len(sorted_pts):
        return sorted_pts[-1]
    before = sorted_pts[pos - 1]
    after = sorted_pts[pos]
    return before if abs(target - before) <= abs(after - target) else after


def _ffmpeg_gray_160x90(video_path: Path, t_sec: float, out_png: Path, accurate: bool) -> Any:
    import cv2

    if accurate:
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(video_path), "-ss", f"{max(0.0, t_sec):.4f}", "-frames:v", "1", str(out_png)]
    else:
        cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{max(0.0, t_sec):.4f}", "-i", str(video_path), "-frames:v", "1", str(out_png)]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0 or not out_png.exists():
        return None
    img = cv2.imread(str(out_png))
    if img is None:
        return None
    small = cv2.resize(img, (160, 90), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)


def _bgr_to_gray_160x90(bgr: Any) -> Any:
    import cv2

    small = cv2.resize(bgr, (160, 90), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, max(0, int(round((p / 100.0) * (len(sorted_vals) - 1)))))
    return float(sorted_vals[idx])


def compare_reader_to_truth(video_path: Path, truth: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compare iter_sampled_frames timestamps and frame contents against ffprobe PTS truth."""
    import numpy as np

    tr = truth or read_true_pts(video_path)
    pts = tr["pts"]
    if not pts:
        raise RuntimeError(f"No video PTS entries found in {video_path}")

    vinfo = video_info(video_path)
    dur = float(vinfo["duration_sec"]) or float(pts[-1])
    span = min(20.0, max(2.0, dur * 0.15))
    ranges = [
        ("start", 0.0, min(dur, span)),
        ("middle", max(0.0, 0.5 * dur - 0.5 * span), min(dur, 0.5 * dur + 0.5 * span)),
        ("end", max(0.0, dur - span), dur),
    ]

    abs_errors: list[float] = []
    signed_errors: list[float] = []
    sampled_items: list[tuple[float, Any]] = []

    for _name, r_start, r_end in ranges:
        if r_end <= r_start:
            continue
        batch = list(iter_sampled_frames(video_path, r_start, r_end, sample_fps=2.0, max_frames=100))
        sampled_items.extend(batch)
        for ts, _fr in batch:
            nearest = _nearest_pts(pts, ts)
            signed_errors.append(ts - nearest)
            abs_errors.append(abs(ts - nearest))

    sorted_abs = sorted(abs_errors)
    err_stats = {
        "n_samples": len(sorted_abs),
        "median": round(statistics.median(sorted_abs), 4) if sorted_abs else None,
        "p95": round(_percentile(sorted_abs, 95.0), 4) if sorted_abs else None,
        "max": round(sorted_abs[-1], 4) if sorted_abs else None,
    }

    # Content check at 10 random sampled frames: compare reader frame vs ffmpeg at nearest true PTS
    # using both fast (-ss before -i) and accurate (-ss after -i) seeking.
    rng = random.Random(42)
    picks = rng.sample(sampled_items, min(10, len(sampled_items)))
    content_rows: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp_dir = Path(tmp_str)
        for idx, (ts, fr) in enumerate(picks):
            true_t = _nearest_pts(pts, ts)
            reader_gray = _bgr_to_gray_160x90(fr)
            ff_fast = _ffmpeg_gray_160x90(video_path, true_t, tmp_dir / f"fast_{idx}.png", accurate=False)
            ff_acc = _ffmpeg_gray_160x90(video_path, true_t, tmp_dir / f"acc_{idx}.png", accurate=True)

            mad_fast = (
                round(float(np.mean(np.abs(reader_gray.astype(np.float32) - ff_fast.astype(np.float32)))), 2)
                if ff_fast is not None
                else None
            )
            mad_acc = (
                round(float(np.mean(np.abs(reader_gray.astype(np.float32) - ff_acc.astype(np.float32)))), 2)
                if ff_acc is not None
                else None
            )
            content_rows.append(
                {
                    "reader_t": round(ts, 4),
                    "true_pts": round(true_t, 4),
                    "label_diff": round(ts - true_t, 4),
                    "mad_fast_seek": mad_fast,
                    "mad_accurate_seek": mad_acc,
                }
            )

    return {
        "truth": tr,
        "error_stats": err_stats,
        "content_rows": content_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect true PTS with ffprobe and compare against pipeline.frames.")
    parser.add_argument("video", type=Path, help="Path to video file")
    args = parser.parse_args()

    res = compare_reader_to_truth(args.video)
    tr = res["truth"]
    print(f"Video: {args.video}")
    print(
        f"ffprobe ({tr['source']}): frame_count={tr['frame_count']}, first_pts={tr['first_pts']}, "
        f"last_pts={tr['last_pts']}, median_gap={tr['median_gap']:.4f}s, "
        f"gaps_gt_2x={tr['large_gap_count']}"
    )
    print(f"start_time: stream={tr['stream_start_time']}, format={tr['format_start_time']}")
    if tr["largest_gaps"]:
        print("Largest gaps (> 2x median):", tr["largest_gaps"])
    print(f"Reader timestamp error vs nearest true PTS: {res['error_stats']}")
    print("\nContent check (10 random sampled frames):")
    print(f"{'reader_t':>10}  {'true_pts':>10}  {'diff':>9}  {'mad_fast':>9}  {'mad_acc':>9}")
    for row in res["content_rows"]:
        print(
            f"{row['reader_t']:>10.4f}  {row['true_pts']:>10.4f}  {row['label_diff']:>+9.4f}  "
            f"{str(row['mad_fast_seek']):>9}  {str(row['mad_accurate_seek']):>9}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
