"""Debug script to run linking, face detection, and quality scoring on a video clip."""

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.detect_track import track_persons
from pipeline.faces import FaceObs, detect_faces_on_track
from pipeline.flags import compute_flags
from pipeline.frames import iter_sampled_frames, video_info
from pipeline.link_transaction import link_transaction, load_zone
from pipeline.quality import (
    ScoredFace,
    load_quality_config,
    score_face,
    score_track_faces,
    select_best_frames,
)


def _partial_face_reasons(face_obs: FaceObs, frame_shape: tuple[int, ...], edge_margin_px: float) -> list[str]:
    """Identify which frame or person-box edges trigger partial face."""
    if not face_obs.face_found or face_obs.face_box is None:
        return []
    h, w = frame_shape[:2]
    fx1, fy1, fx2, fy2 = [float(v) for v in face_obs.face_box]
    reasons: list[str] = []
    if fx1 <= edge_margin_px:
        reasons.append("frame_left")
    if fy1 <= edge_margin_px:
        reasons.append("frame_top")
    if fx2 >= (w - edge_margin_px):
        reasons.append("frame_right")
    if fy2 >= (h - edge_margin_px):
        reasons.append("frame_bottom")

    pbox = face_obs.person_box
    if pbox is not None and len(pbox) == 4:
        px1, py1, px2, py2 = [float(v) for v in pbox]
        if fx1 < px1 - 1.0:
            reasons.append("pbox_left")
        if fy1 < py1 - 1.0:
            reasons.append("pbox_top")
        if fx2 > px2 + 1.0:
            reasons.append("pbox_right")
        if fy2 > py2 + 1.0:
            reasons.append("pbox_bottom")
    return reasons


def _print_raw_table(
    scored: list[ScoredFace],
    frames_by_time: dict[float, object],
    edge_margin_px: float,
) -> None:
    import cv2
    import numpy as np

    print(
        f"\n{'t':>7}  {'lap_nat':>8}  {'sharp112':>8}  {'lum_mean':>8}  {'lum_std':>7}  "
        f"{'pbox_offsets(l,t,r,b)':<24}  {'partial_reason'}"
    )
    print("-" * 92)
    for item in scored:
        obs = item.face_obs
        frame = frames_by_time.get(item.t)
        if not obs.face_found or obs.face_box is None or frame is None:
            print(f"{item.t:>7.2f}  {'-':>8}  {'-':>8}  {'-':>8}  {'-':>7}  {'-':<24}  -")
            continue
        crop = _crop_face(frame, obs.face_box)
        if crop is None:
            print(f"{item.t:>7.2f}  {'-':>8}  {'-':>8}  {'-':>8}  {'-':>7}  {'-':<24}  -")
            continue

        gray_nat = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        lap_nat = float(cv2.Laplacian(gray_nat, cv2.CV_64F).var())
        lum_mean = float(np.mean(gray_nat))
        lum_std = float(np.std(gray_nat))

        fx1, fy1, fx2, fy2 = [float(v) for v in obs.face_box]
        px1, py1, px2, py2 = [float(v) for v in obs.person_box]
        offsets = f"({fx1 - px1:+.0f},{fy1 - py1:+.0f},{px2 - fx2:+.0f},{py2 - fy2:+.0f})"
        p_reasons = _partial_face_reasons(obs, frame.shape, edge_margin_px)  # type: ignore[attr-defined]
        p_str = ", ".join(p_reasons) if p_reasons else "-"
        print(
            f"{item.t:>7.2f}  {lap_nat:>8.1f}  {item.metrics.sharpness:>8.3f}  "
            f"{lum_mean:>8.1f}  {lum_std:>7.1f}  {offsets:<24}  {p_str}"
        )


def _print_quality_table(scored: list[ScoredFace]) -> None:
    print(f"\n{'t':>7}  {'q_score':>7}  {'rel':>6}  {'ready':>5}  {'flags'}")
    print("-" * 70)
    for item in scored:
        flags_str = ", ".join(item.flags) if item.flags else "-"
        print(
            f"{item.t:>7.2f}  {item.quality_score:>7.3f}  {item.reliability:>6}  "
            f"{str(item.is_match_ready):>5}  {flags_str}"
        )


def _crop_face(frame: object, face_box: list[float]) -> object | None:
    h, w = frame.shape[:2]  # type: ignore[attr-defined]
    x1, y1, x2, y2 = face_box
    cx1 = max(0, int(round(x1)))
    cy1 = max(0, int(round(y1)))
    cx2 = min(w, int(round(x2)))
    cy2 = min(h, int(round(y2)))
    if cx2 <= cx1 or cy2 <= cy1:
        return None
    return frame[cy1:cy2, cx1:cx2]  # type: ignore[index]


def _save_picked_contact_sheet(
    picked: list[ScoredFace],
    frames_by_time: dict[float, object],
    out_path: Path,
    cell_size: int = 180,
) -> Path | None:
    """Save a contact sheet of picked frames labeled with score, reliability, and flags."""
    if not picked:
        return None
    import cv2
    import numpy as np

    cols = min(5, len(picked))
    rows = (len(picked) + cols - 1) // cols
    label_h = 54
    cell_h = cell_size + label_h
    sheet = np.full((rows * cell_h, cols * cell_size, 3), 24, dtype=np.uint8)

    for idx, item in enumerate(picked):
        if item.face_obs.face_box is None:
            continue
        frame = frames_by_time.get(item.t)
        if frame is None:
            continue
        crop = _crop_face(frame, item.face_obs.face_box)
        if crop is None:
            continue

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

        line1 = f"t={item.t:.2f} s={item.quality_score:.2f}"
        line2 = f"rel={item.reliability}"
        line3 = ",".join(item.flags[:2]) if item.flags else "ok"
        cv2.putText(sheet, line1, (x0 + 4, y0 + cell_size + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 0), 1)
        cv2.putText(sheet, line2, (x0 + 4, y0 + cell_size + 31), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 255, 200), 1)
        cv2.putText(sheet, line3, (x0 + 4, y0 + cell_size + 47), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (200, 220, 255), 1)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), sheet)
    return out_path


def _write_demo_metrics_table(
    best_item: ScoredFace,
    frames_by_time: dict[float, object],
    out_path: Path,
) -> Path | None:
    """Write metrics_table.txt comparing the original best crop against degraded copies."""
    frame = frames_by_time.get(best_item.t)
    if frame is None or best_item.face_obs.face_box is None:
        return None
    crop = _crop_face(frame, best_item.face_obs.face_box)
    if crop is None:
        return None

    import cv2
    import numpy as np

    cfg = load_quality_config()
    h, w = crop.shape[:2]  # type: ignore[attr-defined]

    def _make_obs(cw: int, ch: int, box_override: list[float] | None = None, pbox_override: list[float] | None = None) -> FaceObs:
        fbox = box_override or [0.0, 0.0, float(cw), float(ch)]
        # Use an inner margin for non-partial cases so original isn't flagged as touching edge.
        pbox = pbox_override or [-10.0, -10.0, float(cw) + 10.0, float(ch) + 10.0]
        return FaceObs(
            t=best_item.t,
            face_found=True,
            face_box=fbox,
            det_score=best_item.face_obs.det_score,
            landmarks=None,
            yaw=0.0,
            pitch=0.0,
            roll=0.0,
            yaw_lm=0.0,
            face_width_px=float(fbox[2] - fbox[0]),
            embedding=None,
            person_box=pbox,
        )

    # Pad original slightly so it doesn't touch the frame edge unless we want partial-face.
    pad = 8
    orig_frame = cv2.copyMakeBorder(crop, pad, pad, pad, pad, cv2.BORDER_REFLECT_101)
    orig_obs = _make_obs(
        w,
        h,
        box_override=[float(pad), float(pad), float(pad + w), float(pad + h)],
        pbox_override=[0.0, 0.0, float(w + 2 * pad), float(h + 2 * pad)],
    )

    blurred = cv2.GaussianBlur(orig_frame, (15, 15), 4.0)
    darker = np.clip(orig_frame.astype(np.float32) * 0.25, 0, 255).astype(np.uint8)
    brighter = np.clip(orig_frame.astype(np.float32) * 1.9 + 60.0, 0, 255).astype(np.uint8)

    shrunk_h = max(10, int(round(40.0 * h / max(1, w))))
    shrunk_crop = cv2.resize(crop, (40, shrunk_h), interpolation=cv2.INTER_AREA)
    shrunk_frame = cv2.copyMakeBorder(shrunk_crop, pad, pad, pad, pad, cv2.BORDER_REFLECT_101)
    shrunk_obs = _make_obs(
        40,
        shrunk_h,
        box_override=[float(pad), float(pad), float(pad + 40), float(pad + shrunk_h)],
        pbox_override=[0.0, 0.0, float(40 + 2 * pad), float(shrunk_h + 2 * pad)],
    )

    off_crop = crop[:, max(0, w // 3) :] if w >= 12 else crop
    oh, ow = off_crop.shape[:2]
    off_obs = _make_obs(
        ow,
        oh,
        box_override=[0.0, 0.0, float(ow), float(oh)],
        pbox_override=[0.0, 0.0, float(ow), float(oh)],
    )

    variants = [
        ("original", orig_obs, orig_frame),
        ("gaussian_blur", orig_obs, blurred),
        ("darker", orig_obs, darker),
        ("brighter", orig_obs, brighter),
        ("shrunk_40px", shrunk_obs, shrunk_frame),
        ("off_center", off_obs, off_crop),
    ]

    lines = [
        f"{'variant':<15} {'q_score':>7} {'sharp':>7} {'size':>7} {'illum':>7} {'occl':>7}  flags",
        "-" * 78,
    ]
    for name, obs, img in variants:
        m, q = score_face(obs, img, cfg)
        fl = compute_flags(obs, img, m, cfg)
        lines.append(
            f"{name:<15} {q:>7.3f} {m.sharpness:>7.3f} {m.face_size:>7.3f} "
            f"{m.illumination:>7.3f} {m.occlusion:>7.3f}  {', '.join(fl) if fl else '-'}"
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def run_debug_quality(
    video_path: Path,
    atm_id: str | None,
    tx_offset_sec: float,
    window_sec: float = 10.0,
    sample_fps: float = 2.0,
    tracker: str = "iou",
    raw: bool = False,
) -> int:
    """Run linking, face detection, quality scoring, and save debug artifacts."""
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

    print(f"Chosen track: {result.chosen_track_id} | Confidence: {result.confidence}")
    frames_by_time = {ts: frame for ts, frame in samples}
    face_obs = detect_faces_on_track(chosen_track, frames_by_time)
    scored = score_track_faces(face_obs, frames_by_time)
    picked, reason = select_best_frames(scored, k=5, min_gap_sec=0.4)

    _print_quality_table(scored)
    if raw:
        cfg = load_quality_config()
        _print_raw_table(scored, frames_by_time, float(cfg["occlusion"]["edge_margin_px"]))

    print("\nPicked frames:")
    for item in picked:
        flags_str = ", ".join(item.flags) if item.flags else "-"
        print(
            f"  t={item.t:.2f}s | score={item.quality_score:.3f} | "
            f"rel={item.reliability} | ready={item.is_match_ready} | "
            f"reason={item.rank_reason} | flags={flags_str}"
        )
    if reason:
        print(f"Selection reason: {reason}")

    atm_label = atm_id or "nozone"
    tx_label = f"{tx_offset_sec:g}".replace(".", "p")
    out_dir = REPO_ROOT / "data" / "outputs" / "debug" / "quality" / f"{video_path.stem}_{atm_label}_tx{tx_label}"

    sheet_path = _save_picked_contact_sheet(picked, frames_by_time, out_dir / "contact_sheet.jpg")
    if sheet_path is not None:
        print(f"Saved contact sheet: {sheet_path}")

    if picked:
        table_path = _write_demo_metrics_table(picked[0], frames_by_time, out_dir / "metrics_table.txt")
        if table_path is not None:
            print(f"Saved metrics table: {table_path}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Debug face quality scoring on the linked ATM track.")
    parser.add_argument("video", type=Path, help="Path to video file")
    parser.add_argument("--atm-id", type=str, default="atm_01", help="ATM zone ID (or '' for fallback)")
    parser.add_argument("--tx", type=float, required=True, help="Transaction offset in seconds")
    parser.add_argument("--window", type=float, default=10.0, help="Window (+/- sec)")
    parser.add_argument("--fps", type=float, default=2.0, help="Sample FPS")
    parser.add_argument("--tracker", type=str, default="iou", choices=["iou", "bytetrack"])
    parser.add_argument("--raw", action="store_true", help="Print raw pixel/geometry diagnostics")
    args = parser.parse_args()

    return run_debug_quality(
        video_path=args.video,
        atm_id=args.atm_id or None,
        tx_offset_sec=args.tx,
        window_sec=args.window,
        sample_fps=args.fps,
        tracker=args.tracker,
        raw=args.raw,
    )


if __name__ == "__main__":
    raise SystemExit(main())
