"""End-to-end Strix face evidence pipeline.

Heavy ML libraries (torch, cv2, insightface, onnxruntime) are imported inside
functions only so lightweight modules can import pipeline.run_pipeline without them.
"""

import argparse
from datetime import datetime
from pathlib import Path
import sys
import time
from typing import Any

from pipeline.contract import Frame, PipelineResult


def _save_picked_outputs(
    picked: list[Any],
    frames_by_time: dict[float, Any],
    clip_dir: Path,
) -> list[Frame]:
    """Save frame JPG, face crop JPG, and embedding NPY for each picked ScoredFace."""
    import cv2
    from pipeline.embeddings import save_embedding

    clip_dir.mkdir(parents=True, exist_ok=True)
    frame_models: list[Frame] = []

    for item in picked:
        t = float(item.t)
        tms = f"{int(round(t * 1000.0)):06d}"
        frame_id = f"f_{tms}"
        frame_path = clip_dir / f"frame_{tms}.jpg"
        crop_path = clip_dir / f"crop_{tms}.jpg"
        emb_path = clip_dir / f"emb_{tms}.npy"

        frame = frames_by_time.get(t)
        if frame is not None:
            cv2.imwrite(str(frame_path), frame)
            if item.face_obs.face_box is not None:
                h, w = frame.shape[:2]
                x1, y1, x2, y2 = item.face_obs.face_box
                cx1 = max(0, int(round(x1)))
                cy1 = max(0, int(round(y1)))
                cx2 = min(w, int(round(x2)))
                cy2 = min(h, int(round(y2)))
                if cx2 > cx1 and cy2 > cy1:
                    cv2.imwrite(str(crop_path), frame[cy1:cy2, cx1:cx2])

        if item.face_obs.embedding is not None:
            save_embedding(emb_path, item.face_obs.embedding)

        frame_models.append(
            Frame(
                frame_id=frame_id,
                frame_path=str(frame_path),
                timestamp_sec=round(t, 3),
                quality_score=float(item.quality_score),
                reliability=item.reliability,
                flags=list(item.flags),
                enhanced=False,
                enhancement=None,
                metrics=item.metrics,
                embedding_path=str(emb_path),
                match_ready=bool(item.is_match_ready),
                rank_reason=item.rank_reason,
                crop_path=str(crop_path) if crop_path.exists() else None,
            )
        )

    return frame_models


def _run_tracking(
    samples: list[tuple[float, Any]],
    detections_per_frame: list[list[dict[str, Any]]],
    tracker: str,
    sample_fps: float,
) -> list[Any]:
    """Track person detections using IoUTracker or ByteTrackAdapter."""
    from pipeline.detect_track import ByteTrackAdapter, IoUTracker

    if tracker == "bytetrack":
        trk = ByteTrackAdapter(frame_rate=max(1, int(round(sample_fps))))
    elif tracker == "iou":
        trk = IoUTracker()
    else:
        raise ValueError(f"Unknown tracker: {tracker!r}")

    for (ts, _), dets in zip(samples, detections_per_frame):
        trk.update(ts, dets)
    return trk.finish()


def _run_output_dir(
    out_dir: str | Path,
    clip_id: str,
    tx_offset_sec: float,
    window_sec: float,
    atm_id: str,
) -> Path:
    """Build collision-free output folder <out_dir>/<clip_id>/tx<tx>_w<w>_<atm>/."""
    tx_label = f"{tx_offset_sec:g}".replace(".", "p")
    w_label = f"{window_sec:g}".replace(".", "p")
    atm_label = atm_id or "nozone"
    return Path(out_dir) / clip_id / f"tx{tx_label}_w{w_label}_{atm_label}"


def run(
    clip_path: str | Path,
    tx_offset_sec: float,
    window_sec: float = 10,
    atm_id: str = "",
    transaction_time: str | None = None,
    sample_fps: float = 2.0,
    tracker: str = "iou",
    out_dir: str | Path = "data/outputs",
) -> PipelineResult:
    """Run the full Strix pipeline on a clip and save outputs + result.json."""
    from pipeline.detect_track import Track, detect_persons
    from pipeline.faces import detect_faces_on_track
    from pipeline.frames import iter_sampled_frames, video_info
    from pipeline.link_transaction import link_transaction, load_zone
    from pipeline.quality import score_track_faces, select_best_frames

    video_path = Path(clip_path)
    clip_id = video_path.stem
    run_dir = _run_output_dir(out_dir, clip_id, float(tx_offset_sec), float(window_sec), atm_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    result_path = run_dir / "result.json"

    if transaction_time is None:
        tx_iso = datetime.now().isoformat(timespec="seconds")
        print(f"[pipeline] Warning: transaction_time not provided, using current time {tx_iso}")
    else:
        tx_iso = transaction_time

    timings_ms: dict[str, float] = {}

    # 1. Sample frames (window +/- 1s margin, capped at 200 frames in iter_sampled_frames).
    t0 = time.perf_counter()
    start_sec = max(0.0, float(tx_offset_sec) - float(window_sec) - 1.0)
    end_sec = float(tx_offset_sec) + float(window_sec) + 1.0
    samples = list(iter_sampled_frames(video_path, start_sec, end_sec, float(sample_fps)))
    timings_ms["frames"] = round((time.perf_counter() - t0) * 1000.0, 2)

    if not samples:
        res = PipelineResult(
            clip_id=clip_id,
            transaction_time=tx_iso,
            person_track_id=None,
            best_frames=[],
            link_confidence="Low",
            link_reason="No frames sampled in transaction window",
            selection_reason="Face not visible",
            timings_ms=timings_ms,
        )
        result_path.write_text(res.model_dump_json(indent=2), encoding="utf-8")
        return res

    h, w = samples[0][1].shape[:2]
    duration_sec = video_info(video_path)["duration_sec"]
    zone_poly = load_zone(atm_id)["polygon"] if atm_id else None

    # 2. Person detection.
    t0 = time.perf_counter()
    detections = detect_persons([frame for _, frame in samples])
    timings_ms["detect_persons"] = round((time.perf_counter() - t0) * 1000.0, 2)

    # 3. Tracking.
    t0 = time.perf_counter()
    tracks = _run_tracking(samples, detections, tracker=tracker, sample_fps=float(sample_fps))
    timings_ms["track"] = round((time.perf_counter() - t0) * 1000.0, 2)

    # 4. Transaction linking.
    t0 = time.perf_counter()
    link_res = link_transaction(
        tracks,
        zone_poly,
        w,
        h,
        float(tx_offset_sec),
        float(window_sec),
        video_duration_sec=duration_sec,
    )
    timings_ms["link_transaction"] = round((time.perf_counter() - t0) * 1000.0, 2)

    if link_res.chosen_track_id is None:
        res = PipelineResult(
            clip_id=clip_id,
            transaction_time=tx_iso,
            person_track_id=None,
            best_frames=[],
            link_confidence=link_res.confidence,
            link_reason=link_res.reason,
            selection_reason=None,
            timings_ms=timings_ms,
        )
        result_path.write_text(res.model_dump_json(indent=2), encoding="utf-8")
        return res

    chosen_track = next((tr for tr in tracks if tr.track_id == link_res.chosen_track_id), None)
    if chosen_track is None:
        res = PipelineResult(
            clip_id=clip_id,
            transaction_time=tx_iso,
            person_track_id=None,
            best_frames=[],
            link_confidence=link_res.confidence,
            link_reason=f"Chosen track {link_res.chosen_track_id} missing",
            selection_reason=None,
            timings_ms=timings_ms,
        )
        result_path.write_text(res.model_dump_json(indent=2), encoding="utf-8")
        return res

    # 5. Restrict eligible observations to [tx - window, tx + window] (exclude 1s warm-up margin).
    win_start = max(0.0, float(tx_offset_sec) - float(window_sec))
    win_end = float(tx_offset_sec) + float(window_sec)
    eligible_obs = [
        obs for obs in chosen_track.observations
        if (win_start - 1e-6) <= float(obs["t"]) <= (win_end + 1e-6)
    ]
    print(
        f"[pipeline] Window [{win_start:.2f}, {win_end:.2f}] s: "
        f"{len(eligible_obs)} eligible observations (from {len(chosen_track.observations)} in track)"
    )
    eligible_track = Track(track_id=chosen_track.track_id, observations=eligible_obs)

    frames_by_time = {ts: frame for ts, frame in samples}
    t0 = time.perf_counter()
    face_obs = detect_faces_on_track(eligible_track, frames_by_time)
    timings_ms["faces"] = round((time.perf_counter() - t0) * 1000.0, 2)

    # 6. Quality scoring + flags + reliability.
    t0 = time.perf_counter()
    scored = score_track_faces(face_obs, frames_by_time)
    timings_ms["quality"] = round((time.perf_counter() - t0) * 1000.0, 2)

    # 7. Select best frames.
    t0 = time.perf_counter()
    picked, sel_reason = select_best_frames(scored, k=5, min_gap_sec=0.4)
    timings_ms["select_best_frames"] = round((time.perf_counter() - t0) * 1000.0, 2)

    best_frames = _save_picked_outputs(picked, frames_by_time, run_dir) if picked else []
    track_id_out: int | None = None if not best_frames else int(link_res.chosen_track_id)

    res = PipelineResult(
        clip_id=clip_id,
        transaction_time=tx_iso,
        person_track_id=track_id_out,
        best_frames=best_frames,
        link_confidence=link_res.confidence,
        link_reason=link_res.reason,
        selection_reason=sel_reason,
        timings_ms=timings_ms,
    )
    result_path.write_text(res.model_dump_json(indent=2), encoding="utf-8")
    return res


def _print_summary(res: PipelineResult, result_path: Path) -> None:
    print(f"\nClip: {res.clip_id} | Track: {res.person_track_id} | Link confidence: {res.link_confidence}")
    if res.link_reason:
        print(f"Link reason: {res.link_reason}")
    if res.selection_reason:
        print(f"Selection reason: {res.selection_reason}")

    print(f"\n{'frame_id':<10}  {'t':>7}  {'score':>6}  {'rel':>6}  {'ready':>5}  {'flags'}")
    print("-" * 68)
    for fr in res.best_frames:
        flags_str = ", ".join(fr.flags) if fr.flags else "-"
        print(
            f"{str(fr.frame_id):<10}  {fr.timestamp_sec:>7.2f}  {fr.quality_score:>6.3f}  "
            f"{fr.reliability:>6}  {str(fr.match_ready):>5}  {flags_str}"
        )

    if res.timings_ms:
        parts = ", ".join(f"{k}={v:.1f}ms" for k, v in res.timings_ms.items())
        print(f"\nTimings: {parts}")
    print(f"Output folder: {result_path.parent}")
    print(f"Saved result: {result_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Strix ATM face evidence pipeline.")
    parser.add_argument("video", type=Path, help="Path to video file")
    parser.add_argument("--atm-id", type=str, default="", help="ATM zone ID (empty for fallback)")
    parser.add_argument("--tx", type=float, required=True, help="Transaction offset in seconds")
    parser.add_argument("--window", type=float, default=10.0, help="Window (+/- sec)")
    parser.add_argument("--transaction-time", type=str, default=None, help="ISO transaction timestamp")
    parser.add_argument("--fps", type=float, default=2.0, help="Sample FPS")
    parser.add_argument("--tracker", type=str, default="iou", choices=["iou", "bytetrack"])
    parser.add_argument("--out-dir", type=Path, default=Path("data/outputs"), help="Output directory")
    args = parser.parse_args()

    res = run(
        clip_path=args.video,
        tx_offset_sec=args.tx,
        window_sec=args.window,
        atm_id=args.atm_id,
        transaction_time=args.transaction_time,
        sample_fps=args.fps,
        tracker=args.tracker,
        out_dir=args.out_dir,
    )
    run_dir = _run_output_dir(args.out_dir, res.clip_id, args.tx, args.window, args.atm_id)
    _print_summary(res, run_dir / "result.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
