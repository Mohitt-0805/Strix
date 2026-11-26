"""Generate a 10 s 25 fps synthetic test video with burned-in frame numbers."""

from pathlib import Path
import subprocess
import sys


def make_test_video(output_path: Path | None = None) -> Path:
    """Create a 10 s 25 fps testsrc2 MP4 in data/samples/ with frame numbers."""
    out = output_path or (Path(__file__).resolve().parent.parent / "data" / "samples" / "testsrc2_10s_25fps.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)

    # testsrc2 renders a built-in frame counter and timestamp; drawtext adds an explicit label if available.
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=640x360:rate=25:duration=10",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(out),
    ]
    subprocess.run(cmd, check=True)
    return out


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    created = make_test_video(target)
    print(f"Created test video: {created}")
