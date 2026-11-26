"""Interactive or headless tool to define an ATM polygon zone in atm_zone.json."""

import argparse
import json
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.frames import iter_sampled_frames
from pipeline.link_transaction import DEFAULT_ZONE_CONFIG


def _save_zone(atm_id: str, poly_norm: list[list[float]], note: str, config_path: Path) -> None:
    data: dict = {}
    if config_path.exists():
        data = json.loads(config_path.read_text(encoding="utf-8"))
    data[atm_id] = {
        "polygon": [[round(x, 4), round(y, 4)] for x, y in poly_norm],
        "note": note,
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Saved zone '{atm_id}' to {config_path}")


def _parse_cli_points(raw: str, w: int, h: int) -> list[list[float]]:
    pts: list[list[float]] = []
    for token in raw.strip().split():
        x_str, y_str = token.split(",", 1)
        x_norm = max(0.0, min(1.0, float(x_str) / float(w)))
        y_norm = max(0.0, min(1.0, float(y_str) / float(h)))
        pts.append([x_norm, y_norm])
    if len(pts) < 3:
        raise ValueError("Need at least 3 polygon points.")
    return pts


def _pick_interactive(frame, atm_id: str, note: str, config_path: Path) -> None:
    import cv2
    import numpy as np

    h, w = frame.shape[:2]
    points_px: list[tuple[int, int]] = []
    win = f"Pick ATM Zone ({atm_id}) - Enter=save, r=reset, q=quit"

    def on_mouse(event, x, y, _flags, _param) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            points_px.append((x, y))

    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(win, on_mouse)

    while True:
        canvas = frame.copy()
        for px, py in points_px:
            cv2.circle(canvas, (px, py), 5, (0, 255, 255), -1)
        if len(points_px) >= 2:
            cv2.polylines(canvas, [np.array(points_px, dtype=np.int32)], False, (0, 255, 0), 2)
        cv2.imshow(win, canvas)

        key = cv2.waitKey(30) & 0xFF
        if key in (13, 10) and len(points_px) >= 3:
            poly_norm = [[x / float(w), y / float(h)] for x, y in points_px]
            _save_zone(atm_id, poly_norm, note, config_path)
            break
        if key == ord("r"):
            points_px.clear()
        elif key in (ord("q"), 27):
            print("Cancelled without saving.")
            break

    cv2.destroyAllWindows()


def main() -> int:
    parser = argparse.ArgumentParser(description="Pick an ATM polygon zone from a video frame.")
    parser.add_argument("video", type=Path, help="Path to video file")
    parser.add_argument("--atm-id", type=str, default="atm_01", help="ATM identifier key")
    parser.add_argument("--sec", type=float, default=0.0, help="Timestamp in seconds to display")
    parser.add_argument("--note", type=str, default="Picked from video frame", help="Zone note")
    parser.add_argument("--points", type=str, default=None, help="Headless pixel points: 'x,y x,y ...'")
    parser.add_argument("--config", type=Path, default=DEFAULT_ZONE_CONFIG, help="Output JSON path")
    args = parser.parse_args()

    samples = list(iter_sampled_frames(args.video, args.sec, args.sec + 1.0, sample_fps=2.0))
    if not samples:
        raise RuntimeError(f"Could not read frame near {args.sec}s from {args.video}")
    _, frame = samples[0]
    h, w = frame.shape[:2]

    has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    if args.points is not None or not has_display:
        raw = args.points or input(f"Frame size {w}x{h}. Enter points 'x,y x,y ...': ")
        poly_norm = _parse_cli_points(raw, w, h)
        _save_zone(args.atm_id, poly_norm, args.note, args.config)
    else:
        _pick_interactive(frame, args.atm_id, args.note, args.config)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
