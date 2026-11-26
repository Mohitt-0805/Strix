"""Debug script to visualize ATM zone linking on a video clip."""

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.detect_track import track_persons
from pipeline.frames import iter_sampled_frames, video_info
from pipeline.link_transaction import compute_anchor, link_transaction, load_zone


def _print_ranking(ranking: list[dict]) -> None:
    print(f"\n{'ID':>4}  {'dwell_s':>8}  {'anc_frac':>8}  {'overlap':>8}  {'near_tx':>8}  {'score':>8}")
    print("-" * 56)
    for row in ranking:
        print(
            f"{row['track_id']:>4}  {row['dwell_sec_in_zone']:>8.2f}  "
            f"{row['anchor_in_zone_frac']:>8.2f}  {row['mean_zone_overlap']:>8.2f}  "
            f"{row['nearest_obs_to_tx_sec']:>8.2f}  {row['score']:>8.2f}"
        )


def run_debug_link(
    video_path: Path,
    atm_id: str | None,
    tx_offset_sec: float,
    window_sec: float = 10.0,
    sample_fps: float = 2.0,
    tracker: str = "iou",
) -> Path:
    """Run detection, tracking, and transaction linking; save annotated MP4."""
    import cv2
    import numpy as np

    start_sec = max(0.0, tx_offset_sec - window_sec)
    end_sec = tx_offset_sec + window_sec
    samples = list(iter_sampled_frames(video_path, start_sec, end_sec, sample_fps))
    if not samples:
        raise RuntimeError(f"No frames sampled from {video_path} in [{start_sec}, {end_sec}]")

    h, w = samples[0][1].shape[:2]
    duration_sec = video_info(video_path)["duration_sec"]
    zone_poly = load_zone(atm_id)["polygon"] if atm_id else None

    tracks = track_persons(samples, tracker=tracker, sample_fps=sample_fps)  # type: ignore[arg-type]
    result = link_transaction(
        tracks,
        zone_poly,
        w,
        h,
        tx_offset_sec,
        window_sec,
        video_duration_sec=duration_sec,
    )

    by_ts: dict[float, list[tuple[int, list[float], float]]] = {}
    for tr in tracks:
        for obs in tr.observations:
            by_ts.setdefault(round(obs["t"], 6), []).append(
                (tr.track_id, obs["box"], obs["score"])
            )

    out_dir = REPO_ROOT / "data" / "outputs" / "debug"
    out_dir.mkdir(parents=True, exist_ok=True)
    atm_label = atm_id or "nozone"
    tx_label = f"{tx_offset_sec:g}".replace(".", "p")
    out_path = out_dir / f"{video_path.stem}_{atm_label}_tx{tx_label}_{tracker}_link.mp4"

    poly_pts = (
        np.asarray([[int(round(x * w)), int(round(y * h))] for x, y in zone_poly], dtype=np.int32)
        if zone_poly
        else None
    )

    writer = cv2.VideoWriter(
        str(out_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        max(1.0, sample_fps),
        (w, h),
    )
    try:
        for ts, frame in samples:
            annotated = frame.copy()
            if poly_pts is not None:
                cv2.polylines(annotated, [poly_pts], True, (255, 255, 0), 2)

            for tid, box, score in by_ts.get(round(ts, 6), []):
                x1, y1, x2, y2 = [int(round(v)) for v in box]
                is_chosen = tid == result.chosen_track_id
                color = (0, 255, 0) if is_chosen else (180, 180, 180)
                thickness = 3 if is_chosen else 1
                label = f"CHOSEN ID {tid}" if is_chosen else f"ID {tid} ({score:.2f})"
                cv2.rectangle(annotated, (x1, y1), (x2, y2), color, thickness)
                cv2.putText(
                    annotated,
                    label,
                    (x1, max(18, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    color,
                    2,
                )

                ax, ay, est = compute_anchor(box, h)
                in_zone = (
                    poly_pts is not None
                    and cv2.pointPolygonTest(poly_pts, (float(ax), float(ay)), False) >= 0
                )
                anc_color = (0, 255, 0) if in_zone else (0, 0, 255)
                cv2.circle(annotated, (int(round(ax)), int(round(ay))), 6, anc_color, -1)
                if est:
                    cv2.circle(annotated, (int(round(ax)), int(round(ay))), 9, (0, 255, 255), 2)

            cv2.putText(
                annotated,
                f"t={ts:.2f}s | chosen={result.chosen_track_id}",
                (10, 26),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (0, 255, 255),
                2,
            )
            writer.write(annotated)
    finally:
        writer.release()

    print(f"Chosen track: {result.chosen_track_id}")
    print(f"Confidence: {result.confidence} | Tracks in window: {result.track_count_in_window}")
    print(f"Reason: {result.reason}")
    _print_ranking(result.ranking)
    print(f"Saved annotated MP4: {out_path}")
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Debug transaction-to-track linking.")
    parser.add_argument("video", type=Path, help="Path to video file")
    parser.add_argument("--atm-id", type=str, default="atm_01", help="ATM zone ID (or '' for fallback)")
    parser.add_argument("--tx", type=float, required=True, help="Transaction offset in seconds")
    parser.add_argument("--window", type=float, default=10.0, help="Window (+/- sec)")
    parser.add_argument("--fps", type=float, default=2.0, help="Sample FPS")
    parser.add_argument("--tracker", type=str, default="iou", choices=["iou", "bytetrack"])
    args = parser.parse_args()

    run_debug_link(
        video_path=args.video,
        atm_id=args.atm_id or None,
        tx_offset_sec=args.tx,
        window_sec=args.window,
        sample_fps=args.fps,
        tracker=args.tracker,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
