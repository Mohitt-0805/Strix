"""Save a contact sheet JPG with timestamps for a given video and time range."""

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PIL import Image, ImageDraw

from pipeline.frames import iter_sampled_frames


def build_contact_sheet(
    video_path: Path,
    start_sec: float,
    end_sec: float,
    sample_fps: float = 2.0,
    cols: int = 4,
    thumb_width: int = 320,
    output_path: Path | None = None,
) -> Path:
    """Sample frames from video_path and save a labeled contact sheet JPG."""
    import cv2

    samples = list(iter_sampled_frames(video_path, start_sec, end_sec, sample_fps))
    if not samples:
        raise RuntimeError(f"No frames sampled from {video_path} in [{start_sec}, {end_sec}]")

    thumbs: list[Image.Image] = []
    for ts, bgr in samples:
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb)
        scale = thumb_width / pil_img.width
        thumb_h = max(1, int(round(pil_img.height * scale)))
        thumb = pil_img.resize((thumb_width, thumb_h), Image.Resampling.LANCZOS)

        draw = ImageDraw.Draw(thumb)
        label = f"t={ts:.2f}s"
        draw.rectangle([(4, 4), (92, 22)], fill=(0, 0, 0))
        draw.text((8, 7), label, fill=(255, 255, 0))
        thumbs.append(thumb)

    cell_w = thumb_width
    cell_h = max(t.height for t in thumbs)
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), color=(20, 20, 20))

    for idx, thumb in enumerate(thumbs):
        r, c = divmod(idx, cols)
        sheet.paste(thumb, (c * cell_w, r * cell_h))

    out = output_path or (
        Path(__file__).resolve().parent.parent
        / "data"
        / "outputs"
        / f"{video_path.stem}_contact_sheet.jpg"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, format="JPEG", quality=92)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a timestamped contact sheet from a video.")
    parser.add_argument("video", type=Path, help="Path to input video file")
    parser.add_argument("--start", type=float, default=0.0, help="Start time in seconds")
    parser.add_argument("--end", type=float, default=5.0, help="End time in seconds")
    parser.add_argument("--fps", type=float, default=2.0, help="Sample FPS")
    parser.add_argument("--out", type=Path, default=None, help="Output JPG path")
    args = parser.parse_args()

    out = build_contact_sheet(
        video_path=args.video,
        start_sec=args.start,
        end_sec=args.end,
        sample_fps=args.fps,
        output_path=args.out,
    )
    print(f"Saved contact sheet: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
