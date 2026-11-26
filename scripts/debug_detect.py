"""Debug script to run person detection on a video clip and save an annotated MP4."""

import argparse
from pathlib import Path
import sys
import time

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.detect_track import detect_persons, get_device, load_person_detector
from pipeline.frames import iter_sampled_frames


def run_debug_detect(
    video_path: Path,
    start_sec: float,
    end_sec: float,
    sample_fps: float,
    score_thresh: float = 0.5,
    device: str | None = None,
) -> Path:
    """Sample frames, detect persons, draw boxes/scores, and write an annotated MP4."""
    import cv2

    samples = list(iter_sampled_frames(video_path, start_sec, end_sec, sample_fps))
    if not samples:
        raise RuntimeError(f"No frames sampled from {video_path} in [{start_sec}, {end_sec}]")

    target_device = device if device and device != "auto" else get_device()
    model = load_person_detector(device=target_device)
    raw_frames = [frame for _, frame in samples]

    # Warm up one frame before timing so model lazy init does not skew per-frame speed.
    _ = detect_persons([raw_frames[0]], score_thresh=score_thresh, model=model)

    t0 = time.perf_counter()
    all_detections = detect_persons(raw_frames, score_thresh=score_thresh, model=model)
    elapsed_sec = time.perf_counter() - t0

    avg_ms = (elapsed_sec / len(raw_frames)) * 1000.0
    fps = len(raw_frames) / elapsed_sec if elapsed_sec > 0 else 0.0
    print(
        f"Device={target_device} | Frames={len(raw_frames)} | "
        f"Avg={avg_ms:.2f} ms/frame | Speed={fps:.2f} FPS"
    )

    h, w = raw_frames[0].shape[:2]
    out_dir = REPO_ROOT / "data" / "outputs" / "debug"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{video_path.stem}_{target_device}_detect.mp4"

    writer = cv2.VideoWriter(
        str(out_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        max(1.0, sample_fps),
        (w, h),
    )
    try:
        for (ts, frame), dets in zip(samples, all_detections):
            annotated = frame.copy()
            for det in dets:
                x1, y1, x2, y2 = [int(round(v)) for v in det["box"]]
                score = det["score"]
                cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(
                    annotated,
                    f"person {score:.2f}",
                    (x1, max(18, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (0, 255, 0),
                    2,
                )
            cv2.putText(
                annotated,
                f"t={ts:.2f}s ({target_device})",
                (10, 26),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 255),
                2,
            )
            writer.write(annotated)
    finally:
        writer.release()

    print(f"Saved annotated MP4: {out_path}")
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Debug person detection on a video clip.")
    parser.add_argument("video", type=Path, help="Path to input video")
    parser.add_argument("--start", type=float, default=0.0, help="Start time in seconds")
    parser.add_argument("--end", type=float, default=5.0, help="End time in seconds")
    parser.add_argument("--fps", type=float, default=2.0, help="Sample FPS")
    parser.add_argument("--thresh", type=float, default=0.5, help="Detection score threshold")
    parser.add_argument("--device", type=str, default="auto", choices=["auto", "cuda", "cpu"])
    args = parser.parse_args()

    run_debug_detect(
        video_path=args.video,
        start_sec=args.start,
        end_sec=args.end,
        sample_fps=args.fps,
        score_thresh=args.thresh,
        device=args.device,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
