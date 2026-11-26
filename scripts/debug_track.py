"""Debug script to run person detection + tracking and save an annotated MP4."""

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.detect_track import Track, track_persons
from pipeline.frames import iter_sampled_frames


PALETTE = [
    (0, 255, 0),
    (255, 165, 0),
    (0, 255, 255),
    (255, 0, 255),
    (255, 255, 0),
    (128, 255, 128),
]


def _color_for_id(track_id: int) -> tuple[int, int, int]:
    return PALETTE[(track_id - 1) % len(PALETTE)]


def _print_track_table(tracks: list[Track], tracker_name: str) -> None:
    print(f"\n=== Tracks ({tracker_name}) | total={len(tracks)} ===")
    print(f"{'ID':>4}  {'first_t':>8}  {'last_t':>8}  {'duration':>8}  {'obs':>5}")
    print("-" * 42)
    for tr in tracks:
        print(
            f"{tr.track_id:>4}  {tr.first_t:>8.2f}  {tr.last_t:>8.2f}  "
            f"{tr.duration:>8.2f}  {len(tr.observations):>5}"
        )


def run_debug_track(
    video_path: Path,
    start_sec: float,
    end_sec: float,
    sample_fps: float,
    tracker: str = "iou",
    score_thresh: float = 0.5,
) -> tuple[list[Track], Path]:
    """Run tracking on sampled frames, write an annotated MP4, and print track summary."""
    import cv2

    samples = list(iter_sampled_frames(video_path, start_sec, end_sec, sample_fps))
    if not samples:
        raise RuntimeError(f"No frames sampled from {video_path} in [{start_sec}, {end_sec}]")

    tracks = track_persons(
        samples,
        tracker=tracker,  # type: ignore[arg-type]
        score_thresh=score_thresh,
        sample_fps=sample_fps,
    )

    # Index observations by timestamp so we can draw track IDs on each frame.
    by_ts: dict[float, list[tuple[int, list[float], float]]] = {}
    for tr in tracks:
        for obs in tr.observations:
            by_ts.setdefault(round(obs["t"], 6), []).append(
                (tr.track_id, obs["box"], obs["score"])
            )

    h, w = samples[0][1].shape[:2]
    out_dir = REPO_ROOT / "data" / "outputs" / "debug"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{video_path.stem}_{tracker}_track.mp4"

    writer = cv2.VideoWriter(
        str(out_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        max(1.0, sample_fps),
        (w, h),
    )
    try:
        for ts, frame in samples:
            annotated = frame.copy()
            for tid, box, score in by_ts.get(round(ts, 6), []):
                x1, y1, x2, y2 = [int(round(v)) for v in box]
                color = _color_for_id(tid)
                cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
                cv2.putText(
                    annotated,
                    f"ID {tid} ({score:.2f})",
                    (x1, max(18, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    color,
                    2,
                )
            cv2.putText(
                annotated,
                f"t={ts:.2f}s [{tracker}]",
                (10, 26),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 255),
                2,
            )
            writer.write(annotated)
    finally:
        writer.release()

    _print_track_table(tracks, tracker)
    print(f"Saved annotated MP4: {out_path}")
    return tracks, out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Debug person tracking on a video clip.")
    parser.add_argument("video", type=Path, help="Path to input video")
    parser.add_argument("--start", type=float, default=0.0, help="Start time in seconds")
    parser.add_argument("--end", type=float, default=10.0, help="End time in seconds")
    parser.add_argument("--fps", type=float, default=2.0, help="Sample FPS")
    parser.add_argument("--tracker", type=str, default="iou", choices=["iou", "bytetrack"])
    parser.add_argument("--thresh", type=float, default=0.5, help="Detection score threshold")
    args = parser.parse_args()

    run_debug_track(
        video_path=args.video,
        start_sec=args.start,
        end_sec=args.end,
        sample_fps=args.fps,
        tracker=args.tracker,
        score_thresh=args.thresh,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
