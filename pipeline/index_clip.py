"""Search-index mode for Strix: stream a clip range and index per-track faces."""

import argparse
import json
from pathlib import Path
import subprocess
import time
from typing import Any, Callable

from pipeline.contract import IndexFace, IndexResult, IndexTrack
from pipeline.errors import (
    InvalidArgumentError,
    ModelLoadError,
    VideoNotFoundError,
    VideoUnreadableError,
    ZoneNotFoundError,
    validate_zone_polygon,
)


_RELIABILITY_RANK: dict[str, int] = {"High": 2, "Medium": 1, "Low": 0}


def _emit_progress(
    progress_cb: Callable[[dict[str, Any]], None] | None,
    stage: str,
    fraction: float,
    message: str,
) -> None:
    if progress_cb is None:
        return
    try:
        progress_cb(
            {
                "stage": stage,
                "fraction": float(max(0.0, min(1.0, fraction))),
                "message": message,
            }
        )
    except Exception:
        pass


def _select_candidate_observations(observations: list[dict[str, Any]], max_even: int = 12) -> list[dict[str, Any]]:
    """Pick up to max_even evenly spaced observations plus the largest person box."""
    n = len(observations)
    if n <= max_even:
        return list(observations)

    step = (n - 1) / float(max_even - 1)
    indices = {int(round(i * step)) for i in range(max_even)}
    biggest_idx = max(
        range(n),
        key=lambda i: max(0.0, float(observations[i]["box"][2]) - float(observations[i]["box"][0]))
        * max(0.0, float(observations[i]["box"][3]) - float(observations[i]["box"][1])),
    )
    indices.add(biggest_idx)
    return [observations[i] for i in sorted(indices)]


def _index_output_dir(out_dir: str | Path, clip_id: str, start_sec: float, end_sec: float) -> Path:
    s_lbl = f"{start_sec:g}".replace(".", "p")
    e_lbl = f"{end_sec:g}".replace(".", "p")
    return Path(out_dir) / clip_id / f"index_s{s_lbl}_e{e_lbl}"


def _build_tracker(tracker: str, sample_fps: float) -> Any:
    from pipeline.detect_track import ByteTrackAdapter, IoUTracker

    if tracker == "bytetrack":
        return ByteTrackAdapter(frame_rate=max(1, int(round(sample_fps))))
    if tracker == "iou":
        return IoUTracker()
    raise InvalidArgumentError(f"Unsupported tracker: {tracker!r}")


def index_clip(
    clip_path: str | Path,
    start_sec: float = 0.0,
    end_sec: float | None = None,
    sample_fps: float = 1.0,
    tracker: str = "iou",
    faces_per_track: int = 3,
    min_face_px: int = 40,
    out_dir: str | Path = "data/outputs",
    zone_polygon_norm: list[list[float]] | None = None,
    atm_id: str | None = None,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
    max_seconds: float = 600.0,
) -> IndexResult:
    """Stream a clip range in chunks, track persons, and index top face embeddings."""
    import cv2
    import numpy as np

    from pipeline.detect_track import Track, detect_persons
    from pipeline.embeddings import save_embedding
    from pipeline.faces import assign_faces_to_tracks, detect_faces_on_track
    from pipeline.frames import iter_sampled_frames, video_info
    from pipeline.link_transaction import link_transaction, load_zone
    from pipeline.quality import score_track_faces

    video_path = Path(clip_path)
    if not video_path.exists():
        raise VideoNotFoundError(f"Video file not found: {video_path}")
    if float(start_sec) < 0.0:
        raise InvalidArgumentError(f"start_sec must be >= 0, got {start_sec}")
    if float(sample_fps) <= 0.0:
        raise InvalidArgumentError(f"sample_fps must be > 0, got {sample_fps}")
    if int(faces_per_track) <= 0:
        raise InvalidArgumentError(f"faces_per_track must be > 0, got {faces_per_track}")
    if int(min_face_px) < 0:
        raise InvalidArgumentError(f"min_face_px must be >= 0, got {min_face_px}")
    if float(max_seconds) <= 0.0:
        raise InvalidArgumentError(f"max_seconds must be > 0, got {max_seconds}")
    if tracker not in {"iou", "bytetrack"}:
        raise InvalidArgumentError(f"Unsupported tracker: {tracker!r}")

    zone_poly: list[list[float]] | None = None
    if zone_polygon_norm is not None:
        zone_poly = validate_zone_polygon(zone_polygon_norm)
    elif atm_id:
        try:
            zone_poly = load_zone(atm_id)["polygon"]
        except KeyError as exc:
            raise ZoneNotFoundError(str(exc)) from exc

    try:
        info = video_info(video_path)
    except (subprocess.CalledProcessError, ValueError, OSError, KeyError) as exc:
        raise VideoUnreadableError(f"Failed to read video {video_path}: {exc}") from exc

    duration_sec = float(info["duration_sec"])
    actual_end = duration_sec if end_sec is None else min(float(end_sec), duration_sec if duration_sec > 0 else float(end_sec))
    if actual_end <= float(start_sec):
        raise InvalidArgumentError(f"end_sec ({actual_end}) must be > start_sec ({start_sec})")
    if (actual_end - float(start_sec)) > float(max_seconds):
        raise InvalidArgumentError(
            f"Requested range {actual_end - float(start_sec):.1f}s exceeds max_seconds={max_seconds}"
        )

    clip_id = video_path.stem
    index_dir = _index_output_dir(out_dir, clip_id, float(start_sec), actual_end)
    index_dir.mkdir(parents=True, exist_ok=True)
    npz_path = index_dir / "index.npz"
    json_path = index_dir / "index.json"

    timings_ms: dict[str, float] = {"frames": 0.0, "detect_persons": 0.0, "track": 0.0, "faces": 0.0, "occluders": 0.0, "quality": 0.0, "save": 0.0}

    _emit_progress(progress_cb, "frames", 0.05, f"Streaming frames [{start_sec:.1f}, {actual_end:.1f}]")
    trk = _build_tracker(tracker, float(sample_fps))
    frames_by_time: dict[float, Any] = {}
    frame_shape: tuple[int, int] | None = None

    chunk_size = 100
    chunk: list[tuple[float, Any]] = []
    frame_iter = iter_sampled_frames(video_path, float(start_sec), actual_end, float(sample_fps), max_frames=None)

    def _process_chunk(batch: list[tuple[float, Any]]) -> None:
        nonlocal frame_shape
        if not batch:
            return
        if frame_shape is None:
            fh, fw = batch[0][1].shape[:2]
            frame_shape = (fh, fw)
        for ts, fr in batch:
            frames_by_time[ts] = fr

        t_det = time.perf_counter()
        try:
            dets = detect_persons([fr for _, fr in batch])
        except Exception as exc:
            raise ModelLoadError(f"Person detector failed: {exc}") from exc
        timings_ms["detect_persons"] += (time.perf_counter() - t_det) * 1000.0

        t_trk = time.perf_counter()
        for (ts, _), det_list in zip(batch, dets):
            trk.update(ts, det_list)
        timings_ms["track"] += (time.perf_counter() - t_trk) * 1000.0

    while True:
        t_fr = time.perf_counter()
        try:
            item = next(frame_iter)
        except StopIteration:
            timings_ms["frames"] += (time.perf_counter() - t_fr) * 1000.0
            break
        except Exception as exc:
            raise VideoUnreadableError(f"Failed reading frames from {video_path}: {exc}") from exc
        timings_ms["frames"] += (time.perf_counter() - t_fr) * 1000.0

        chunk.append(item)
        if len(chunk) >= chunk_size:
            _process_chunk(chunk)
            _emit_progress(
                progress_cb,
                "detect_persons",
                min(0.50, 0.10 + 0.40 * ((item[0] - float(start_sec)) / max(1e-6, actual_end - float(start_sec)))),
                f"Detected/tracked up to t={item[0]:.1f}s",
            )
            chunk = []

    if chunk:
        _process_chunk(chunk)

    tracks = trk.finish()
    _emit_progress(progress_cb, "faces", 0.55, f"Extracting faces for {len(tracks)} tracks")

    person_boxes_by_time: dict[float, list[tuple[int, list[float]]]] = {}
    for tr in tracks:
        for o in tr.observations:
            person_boxes_by_time.setdefault(round(float(o["t"]), 6), []).append((int(tr.track_id), list(o["box"])))

    # 1) Detect candidate faces per track, then enforce one-face-per-track per timestamp.
    raw_faces_by_track: dict[int, list[Any]] = {}
    for idx, tr in enumerate(tracks):
        cand_obs = _select_candidate_observations(tr.observations, max_even=12)
        sub_track = Track(track_id=tr.track_id, observations=cand_obs)
        t_face = time.perf_counter()
        try:
            raw_faces_by_track[int(tr.track_id)] = detect_faces_on_track(sub_track, frames_by_time)
        except Exception as exc:
            raise ModelLoadError(f"Face model failed: {exc}") from exc
        timings_ms["faces"] += (time.perf_counter() - t_face) * 1000.0
        _emit_progress(
            progress_cb,
            "faces",
            0.55 + 0.25 * ((idx + 1) / max(1, len(tracks))),
            f"Detected faces for track {tr.track_id} ({idx + 1}/{len(tracks)})",
        )

    by_t_tid: dict[float, dict[int, Any]] = {}
    for tid, f_list in raw_faces_by_track.items():
        for fo in f_list:
            by_t_tid.setdefault(round(float(fo.t), 6), {})[tid] = fo
    assigned_by_t_tid = {t_key: assign_faces_to_tracks(obs_map) for t_key, obs_map in by_t_tid.items()}

    index_tracks: list[IndexTrack] = []
    all_embeddings: list[Any] = []
    all_metadata: list[dict[str, Any]] = []

    tx_mid = 0.5 * (float(start_sec) + actual_end)
    half_win = 0.5 * (actual_end - float(start_sec))

    for idx, tr in enumerate(tracks):
        tid = int(tr.track_id)
        dwell_val: float | None = None
        if zone_poly is not None and frame_shape is not None:
            fh, fw = frame_shape
            link_res = link_transaction([tr], zone_poly, fw, fh, tx_mid, half_win, video_duration_sec=duration_sec)
            if link_res.ranking:
                dwell_val = float(link_res.ranking[0]["dwell_sec_in_zone"])
            else:
                dwell_val = 0.0

        face_obs = [assigned_by_t_tid[round(float(fo.t), 6)][tid] for fo in raw_faces_by_track[tid]]
        other_boxes_for_track = {
            float(fo.t): [
                box for other_tid, box in person_boxes_by_time.get(round(float(fo.t), 6), [])
                if other_tid != tid
            ]
            for fo in face_obs
        }

        t_qual = time.perf_counter()
        occ_timings: dict[str, float] = {}
        scored = score_track_faces(
            face_obs,
            frames_by_time,
            other_person_boxes_by_time=other_boxes_for_track,
            timings_out=occ_timings,
        )
        occ_ms = occ_timings.get("occluders", 0.0)
        timings_ms["occluders"] += occ_ms
        timings_ms["quality"] += max(0.0, (time.perf_counter() - t_qual) * 1000.0 - occ_ms)

        found = [s for s in scored if s.face_obs.face_found and s.face_obs.embedding is not None]
        valid = [s for s in found if float(s.face_obs.face_width_px or 0.0) >= float(min_face_px)]

        track_faces: list[IndexFace] = []
        reason: str | None = None
        if not found:
            reasons = [getattr(fo, "reason", None) for fo in face_obs if getattr(fo, "reason", None)]
            reason = str(reasons[0]) if reasons else "No face found"
        elif not valid:
            reason = f"Face under {int(min_face_px)} px"
        else:
            ranked = sorted(
                valid,
                key=lambda s: (
                    bool(s.is_match_ready),
                    _RELIABILITY_RANK.get(s.reliability, 0),
                    float(s.quality_score),
                ),
                reverse=True,
            )[: int(faces_per_track)]

            t_save = time.perf_counter()
            for item in ranked:
                t_val = round(float(item.t), 3)
                tms = f"{int(round(t_val * 1000.0)):06d}"
                frame_path = index_dir / f"track{tr.track_id}_frame_{tms}.jpg"
                crop_path = index_dir / f"track{tr.track_id}_crop_{tms}.jpg"
                emb_path = index_dir / f"track{tr.track_id}_emb_{tms}.npy"

                frame = frames_by_time.get(float(item.t))
                if frame is not None:
                    cv2.imwrite(str(frame_path), frame)
                    if item.face_obs.face_box is not None:
                        fh, fw = frame.shape[:2]
                        x1, y1, x2, y2 = item.face_obs.face_box
                        cx1 = max(0, int(round(x1)))
                        cy1 = max(0, int(round(y1)))
                        cx2 = min(fw, int(round(x2)))
                        cy2 = min(fh, int(round(y2)))
                        if cx2 > cx1 and cy2 > cy1:
                            cv2.imwrite(str(crop_path), frame[cy1:cy2, cx1:cx2])

                vec = np.asarray(item.face_obs.embedding, dtype=np.float32)
                norm = float(np.linalg.norm(vec))
                if norm > 0.0:
                    vec = vec / norm
                save_embedding(emb_path, vec)

                face_box = [round(float(v), 2) for v in (item.face_obs.face_box or [0.0, 0.0, 0.0, 0.0])]
                face_entry = IndexFace(
                    t=t_val,
                    quality_score=float(item.quality_score),
                    reliability=item.reliability,
                    match_ready=bool(item.is_match_ready),
                    flags=list(item.flags),
                    face_box=face_box,
                    crop_path=str(crop_path),
                    frame_path=str(frame_path),
                    embedding_path=str(emb_path),
                    flag_scores=item.flag_scores,
                )
                track_faces.append(face_entry)
                all_embeddings.append(vec)
                all_metadata.append(
                    {
                        "track_id": int(tr.track_id),
                        "t": t_val,
                        "quality_score": float(item.quality_score),
                        "reliability": item.reliability,
                        "match_ready": bool(item.is_match_ready),
                        "flags": list(item.flags),
                        "face_box": face_box,
                        "crop_path": str(crop_path),
                        "frame_path": str(frame_path),
                        "embedding_path": str(emb_path),
                    }
                )
            timings_ms["save"] += (time.perf_counter() - t_save) * 1000.0

        n_obs = len(tr.observations)
        index_tracks.append(
            IndexTrack(
                track_id=int(tr.track_id),
                first_t=round(tr.first_t, 3),
                last_t=round(tr.last_t, 3),
                n_observations=n_obs,
                short_track=n_obs < 2,
                dwell_sec_in_zone=dwell_val,
                faces=track_faces,
                reason=reason,
            )
        )
        _emit_progress(
            progress_cb,
            "faces",
            0.55 + 0.35 * ((idx + 1) / max(1, len(tracks))),
            f"Processed track {tr.track_id} ({idx + 1}/{len(tracks)})",
        )

    _emit_progress(progress_cb, "save", 0.95, "Writing index.npz and index.json")
    t_save_idx = time.perf_counter()
    emb_matrix = (
        np.vstack(all_embeddings).astype(np.float32)
        if all_embeddings
        else np.zeros((0, 512), dtype=np.float32)
    )
    np.savez(
        str(npz_path),
        embeddings=emb_matrix,
        metadata_json=np.array(json.dumps(all_metadata)),
    )
    timings_ms["save"] += (time.perf_counter() - t_save_idx) * 1000.0

    rounded_timings = {k: round(v, 2) for k, v in timings_ms.items()}
    result = IndexResult(
        clip_id=clip_id,
        start_sec=round(float(start_sec), 3),
        end_sec=round(actual_end, 3),
        tracks=index_tracks,
        index_npz_path=str(npz_path),
        index_json_path=str(json_path),
        total_embeddings=len(all_embeddings),
        timings_ms=rounded_timings,
    )
    json_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    _emit_progress(progress_cb, "done", 1.0, "Done")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Index faces across a video clip range for search.")
    parser.add_argument("video", type=Path, help="Path to video file")
    parser.add_argument("--start", type=float, default=0.0, help="Start time in seconds")
    parser.add_argument("--end", type=float, default=None, help="End time in seconds")
    parser.add_argument("--fps", type=float, default=1.0, help="Sample FPS")
    parser.add_argument("--tracker", type=str, default="iou", choices=["iou", "bytetrack"])
    parser.add_argument("--faces-per-track", type=int, default=3)
    parser.add_argument("--min-face-px", type=int, default=40)
    parser.add_argument("--atm-id", type=str, default=None)
    parser.add_argument("--out-dir", type=Path, default=Path("data/outputs"))
    args = parser.parse_args()

    res = index_clip(
        clip_path=args.video,
        start_sec=args.start,
        end_sec=args.end,
        sample_fps=args.fps,
        tracker=args.tracker,
        faces_per_track=args.faces_per_track,
        min_face_px=args.min_face_px,
        atm_id=args.atm_id,
        out_dir=args.out_dir,
    )
    print(f"Indexed {res.clip_id} [{res.start_sec}, {res.end_sec}]s | Tracks: {len(res.tracks)}")
    for tr in res.tracks:
        print(
            f"  track={tr.track_id} [{tr.first_t:.2f}..{tr.last_t:.2f}] | "
            f"faces={len(tr.faces)} | reason={tr.reason or '-'}"
        )
    if res.timings_ms:
        print("Timings:", ", ".join(f"{k}={v:.1f}ms" for k, v in res.timings_ms.items()))
    print(f"Embeddings in index.npz: {res.total_embeddings} ({res.index_npz_path})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
