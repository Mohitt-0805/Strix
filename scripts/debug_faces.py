"""Debug script to run face detection and embedding on the linked ATM track."""

import argparse
from pathlib import Path
import sys
import time

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.detect_track import track_persons
from pipeline.faces import FaceObs, detect_faces_on_track, get_active_provider, get_face_app
from pipeline.frames import iter_sampled_frames, video_info
from pipeline.link_transaction import link_transaction, load_zone


def _fmt_opt(val: float | None, fmt: str) -> str:
    return f"{val:{fmt}}" if val is not None else "-"


def _print_face_table(face_obs: list[FaceObs]) -> None:
    print(
        f"\n{'t':>7}  {'face_found':>10}  {'det_score':>9}  {'width_px':>8}  "
        f"{'yaw':>7}  {'pitch':>7}  {'roll':>7}  {'yaw_lm':>7}"
    )
    print("-" * 76)
    for obs in face_obs:
        print(
            f"{obs.t:>7.2f}  {str(obs.face_found):>10}  "
            f"{_fmt_opt(obs.det_score, '.3f'):>9}  "
            f"{_fmt_opt(obs.face_width_px, '.1f'):>8}  "
            f"{_fmt_opt(obs.yaw, '.1f'):>7}  "
            f"{_fmt_opt(obs.pitch, '.1f'):>7}  "
            f"{_fmt_opt(obs.roll, '.1f'):>7}  "
            f"{_fmt_opt(obs.yaw_lm, '.1f'):>7}"
        )


def _save_contact_sheet(
    crops_with_obs: list[tuple[object, FaceObs]],
    out_path: Path,
    cols: int = 8,
    cell_size: int = 160,
) -> Path | None:
    """Save a contact sheet JPG of all detected face crops labeled with t, det_score, yaw."""
    if not crops_with_obs:
        return None
    import cv2
    import numpy as np

    label_h = 38
    cell_h = cell_size + label_h
    rows = (len(crops_with_obs) + cols - 1) // cols
    sheet = np.full((rows * cell_h, cols * cell_size, 3), 24, dtype=np.uint8)

    for idx, (crop, obs) in enumerate(crops_with_obs):
        r, c = divmod(idx, cols)
        y0 = r * cell_h
        x0 = c * cell_size

        ch, cw = crop.shape[:2]  # type: ignore[attr-defined]
        scale = min(cell_size / max(1, cw), cell_size / max(1, ch))
        nw = max(1, int(round(cw * scale)))
        nh = max(1, int(round(ch * scale)))
        resized = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_AREA)

        dx = x0 + (cell_size - nw) // 2
        dy = y0 + (cell_size - nh) // 2
        sheet[dy : dy + nh, dx : dx + nw] = resized

        line1 = f"t={obs.t:.2f} s={obs.det_score or 0.0:.2f}"
        yaw_str = f"{obs.yaw:.1f}" if obs.yaw is not None else "-"
        line2 = f"yaw={yaw_str}"
        cv2.putText(
            sheet,
            line1,
            (x0 + 4, y0 + cell_size + 14),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (255, 255, 0),
            1,
        )
        cv2.putText(
            sheet,
            line2,
            (x0 + 4, y0 + cell_size + 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (200, 220, 255),
            1,
        )

    cv2.imwrite(str(out_path), sheet)
    return out_path


def _save_face_crops(
    face_obs: list[FaceObs],
    frames_by_time: dict[float, object],
    out_dir: Path,
) -> tuple[int, Path | None]:
    import cv2

    out_dir.mkdir(parents=True, exist_ok=True)
    saved = 0
    crops_with_obs: list[tuple[object, FaceObs]] = []
    for idx, obs in enumerate(face_obs):
        if not obs.face_found or obs.face_box is None:
            continue
        frame = frames_by_time.get(obs.t)
        if frame is None:
            continue
        h, w = frame.shape[:2]  # type: ignore[attr-defined]
        x1, y1, x2, y2 = obs.face_box
        cx1 = max(0, int(round(x1)))
        cy1 = max(0, int(round(y1)))
        cx2 = min(w, int(round(x2)))
        cy2 = min(h, int(round(y2)))
        if cx2 <= cx1 or cy2 <= cy1:
            continue
        crop = frame[cy1:cy2, cx1:cx2]  # type: ignore[index]
        score = obs.det_score or 0.0
        width = int(round(obs.face_width_px or (cx2 - cx1)))
        fname = f"obs{idx:03d}_t{obs.t:.2f}_score{score:.2f}_w{width}.jpg"
        cv2.imwrite(str(out_dir / fname), crop)
        crops_with_obs.append((crop, obs))
        saved += 1

    sheet_path = _save_contact_sheet(crops_with_obs, out_dir / "contact_sheet.jpg")
    return saved, sheet_path


def run_debug_faces(
    video_path: Path,
    atm_id: str | None,
    tx_offset_sec: float,
    window_sec: float = 10.0,
    sample_fps: float = 2.0,
    tracker: str = "iou",
) -> int:
    """Link transaction to a track, detect faces on that track, and report stats."""
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

    if result.chosen_track_id is None:
        print(f"No track chosen (reason: {result.reason}). Stopping.")
        return 0

    chosen_track = next((tr for tr in tracks if tr.track_id == result.chosen_track_id), None)
    if chosen_track is None:
        print(f"Chosen track ID {result.chosen_track_id} not found in tracks. Stopping.")
        return 0

    print(
        f"Chosen track: {result.chosen_track_id} | Confidence: {result.confidence} | "
        f"Observations: {len(chosen_track.observations)}"
    )

    frames_by_time = {ts: frame for ts, frame in samples}
    get_face_app()  # Warm up before timing face detection loop.
    t0 = time.perf_counter()
    face_obs = detect_faces_on_track(chosen_track, frames_by_time)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    atm_label = atm_id or "nozone"
    tx_label = f"{tx_offset_sec:g}".replace(".", "p")
    out_dir = REPO_ROOT / "data" / "outputs" / "debug" / "faces" / f"{video_path.stem}_{atm_label}_tx{tx_label}"
    saved_crops, sheet_path = _save_face_crops(face_obs, frames_by_time, out_dir)

    _print_face_table(face_obs)
    no_face_count = sum(1 for o in face_obs if not o.face_found)
    ms_per_obs = elapsed_ms / len(face_obs) if face_obs else 0.0
    print(f"\nObservations with no face: {no_face_count} / {len(face_obs)}")
    print(f"Time per observation: {ms_per_obs:.2f} ms (total {elapsed_ms:.1f} ms)")
    print(f"Provider: {get_active_provider()}")
    print(f"Saved {saved_crops} face crops to: {out_dir}")
    if sheet_path is not None:
        print(f"Saved contact sheet to: {sheet_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Debug face detection on the linked ATM track.")
    parser.add_argument("video", type=Path, help="Path to video file")
    parser.add_argument("--atm-id", type=str, default="atm_01", help="ATM zone ID (or '' for fallback)")
    parser.add_argument("--tx", type=float, required=True, help="Transaction offset in seconds")
    parser.add_argument("--window", type=float, default=10.0, help="Window (+/- sec)")
    parser.add_argument("--fps", type=float, default=2.0, help="Sample FPS")
    parser.add_argument("--tracker", type=str, default="iou", choices=["iou", "bytetrack"])
    args = parser.parse_args()

    return run_debug_faces(
        video_path=args.video,
        atm_id=args.atm_id or None,
        tx_offset_sec=args.tx,
        window_sec=args.window,
        sample_fps=args.fps,
        tracker=args.tracker,
    )


if __name__ == "__main__":
    raise SystemExit(main())
