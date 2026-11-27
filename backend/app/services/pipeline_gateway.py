"""Gateway adapting pipeline.adapter run() and index_clip() safely."""

import inspect
import os
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.app.models import (
    Clip,
    ClipIndex,
    FrameRecord,
    IndexFaceRecord,
    IndexTrackRecord,
    Run,
)
from backend.app.services.fake_assets import materialize_fake_assets
from backend.app.services.storage import from_rel, to_rel
from pipeline.contract import IndexResult, PipelineResult


def _extract_flag_scores_list(raw_items: Any) -> list[dict[str, float] | None]:
    """Extract optional flag_scores dicts from raw frame/face objects or dicts."""
    if not isinstance(raw_items, list):
        return []
    extracted: list[dict[str, float] | None] = []
    for item in raw_items:
        if isinstance(item, dict):
            scores = item.get("flag_scores")
        else:
            scores = getattr(item, "flag_scores", None)
            if scores is None:
                extra = getattr(item, "model_extra", None) or {}
                scores = extra.get("flag_scores")
        if isinstance(scores, dict):
            extracted.append({str(k): float(v) for k, v in scores.items()})
        else:
            extracted.append(None)
    return extracted


def _build_supported_kwargs(
    target_fn: Callable[..., Any],
    all_kwargs: dict[str, Any],
    required_keys: tuple[str, ...],
) -> dict[str, Any]:
    """Filter optional pipeline kwargs using inspect.signature."""
    sig = inspect.signature(target_fn)
    accepts_var_kw = any(
        param.kind == inspect.Parameter.VAR_KEYWORD
        for param in sig.parameters.values()
    )
    if accepts_var_kw:
        return {
            k: v
            for k, v in all_kwargs.items()
            if v is not None or k in required_keys
        }

    filtered: dict[str, Any] = {
        key: all_kwargs[key] for key in required_keys if key in sig.parameters
    }
    for key, val in all_kwargs.items():
        if key in required_keys or key not in sig.parameters:
            continue
        if val is not None:
            filtered[key] = val
    return filtered


def _normalize_result_paths(result: PipelineResult, settings: Settings) -> PipelineResult:
    """Convert all file paths inside PipelineResult to DATA_DIR-relative forward slashes."""
    data_root = settings.resolved_data_dir
    norm_frames = []
    for frame in result.best_frames:
        enh = frame.enhancement
        if enh is not None and enh.enhanced_path:
            enh = enh.model_copy(
                update={"enhanced_path": to_rel(enh.enhanced_path, data_root)}
            )
        norm_frames.append(
            frame.model_copy(
                update={
                    "frame_path": to_rel(frame.frame_path, data_root),
                    "crop_path": (
                        to_rel(frame.crop_path, data_root) if frame.crop_path else None
                    ),
                    "embedding_path": to_rel(frame.embedding_path, data_root),
                    "enhancement": enh,
                }
            )
        )
    return result.model_copy(update={"best_frames": norm_frames})


def execute_pipeline_for_run(
    *,
    db: Session,
    run: Run,
    clip: Clip,
    settings: Settings,
    progress_cb: Callable[[Any], None] | None = None,
) -> PipelineResult:
    """Invoke pipeline.adapter.get_run(), normalize outputs, and persist frame rows."""
    os.environ["USE_FAKE_PIPELINE"] = "1" if settings.use_fake_pipeline else "0"
    from pipeline.adapter import get_run

    run_fn = get_run()
    data_root = settings.resolved_data_dir
    clip_abs_path = from_rel(clip.stored_path, data_root, allowed_roots=("uploads",))
    out_dir_abs = (data_root / "outputs" / clip.id / f"run_{run.id}").resolve()
    out_dir_abs.mkdir(parents=True, exist_ok=True)

    candidate_kwargs: dict[str, Any] = {
        "clip_path": str(clip_abs_path),
        "tx_offset_sec": run.tx_offset_sec,
        "window_sec": run.window_sec,
        "transaction_time": run.transaction_time.isoformat(),
        "sample_fps": run.sample_fps,
        "tracker": run.tracker,
        "out_dir": str(out_dir_abs),
        "progress_cb": progress_cb,
    }
    if clip.zone_polygon_norm is not None:
        candidate_kwargs["zone_polygon_norm"] = clip.zone_polygon_norm
    else:
        candidate_kwargs["atm_id"] = run.atm_id or ""

    call_kwargs = _build_supported_kwargs(
        run_fn, candidate_kwargs, ("clip_path", "tx_offset_sec", "window_sec")
    )

    raw_result = run_fn(**call_kwargs)
    raw_frames = (
        raw_result.get("best_frames")
        if isinstance(raw_result, dict)
        else getattr(raw_result, "best_frames", None)
    )
    raw_flag_scores = _extract_flag_scores_list(raw_frames)
    result = (
        raw_result
        if isinstance(raw_result, PipelineResult)
        else PipelineResult.model_validate(raw_result)
    )

    if settings.use_fake_pipeline:
        result = materialize_fake_assets(
            result,
            clip_id=clip.id,
            run_id=run.id,
            original_filename=clip.original_filename,
            data_dir=data_root,
            embed_dim=settings.embed_dim,
        )

    normalized = _normalize_result_paths(result, settings)
    result_dump = normalized.model_dump(mode="json")
    for idx, scores in enumerate(raw_flag_scores):
        if scores is not None and idx < len(result_dump.get("best_frames", [])):
            result_dump["best_frames"][idx]["flag_scores"] = scores

    run.link_low_margin = bool(normalized.link_low_margin)
    run.result_json = result_dump
    for idx, frame in enumerate(normalized.best_frames):
        frame_scores = raw_flag_scores[idx] if idx < len(raw_flag_scores) else None
        db.add(
            FrameRecord(
                run_id=run.id,
                frame_id=str(frame.frame_id),
                timestamp_sec=frame.timestamp_sec,
                quality_score=frame.quality_score,
                reliability=frame.reliability,
                flags=list(frame.flags),
                flag_scores=frame_scores,
                face_box=list(frame.face_box) if frame.face_box is not None else None,
                match_ready=frame.match_ready,
                rank_reason=frame.rank_reason,
                frame_path_rel=frame.frame_path,
                crop_path_rel=frame.crop_path,
                embedding_path_rel=frame.embedding_path,
                enhanced=frame.enhanced,
                enhancement=(
                    frame.enhancement.model_dump(mode="json")
                    if frame.enhancement is not None
                    else None
                ),
                metrics=frame.metrics.model_dump(mode="json"),
                selected=False,
            )
        )
    db.commit()
    return normalized


def execute_index_for_job(
    *,
    db: Session,
    index_job: ClipIndex,
    clip: Clip,
    settings: Settings,
    progress_cb: Callable[[Any], None] | None = None,
) -> IndexResult:
    """Invoke pipeline.adapter.get_index_clip(), normalise paths, and persist track/face rows."""
    os.environ["USE_FAKE_PIPELINE"] = "1" if settings.use_fake_pipeline else "0"
    from pipeline.adapter import get_index_clip

    index_fn = get_index_clip()
    data_root = settings.resolved_data_dir
    clip_abs_path = from_rel(clip.stored_path, data_root, allowed_roots=("uploads",))
    out_dir_abs = (data_root / "outputs" / clip.id / f"index_{index_job.id}").resolve()
    out_dir_abs.mkdir(parents=True, exist_ok=True)

    candidate_kwargs: dict[str, Any] = {
        "clip_path": str(clip_abs_path),
        "start_sec": index_job.start_sec,
        "end_sec": index_job.end_sec,
        "sample_fps": index_job.sample_fps,
        "tracker": index_job.tracker,
        "faces_per_track": index_job.faces_per_track,
        "out_dir": str(out_dir_abs),
        "progress_cb": progress_cb,
    }
    if clip.zone_polygon_norm is not None:
        candidate_kwargs["zone_polygon_norm"] = clip.zone_polygon_norm
    elif index_job.atm_id:
        candidate_kwargs["atm_id"] = index_job.atm_id

    call_kwargs = _build_supported_kwargs(index_fn, candidate_kwargs, ("clip_path",))
    raw_result = index_fn(**call_kwargs)

    # Extract optional face.flag_scores per track before Pydantic validation.
    raw_tracks = (
        raw_result.get("tracks")
        if isinstance(raw_result, dict)
        else getattr(raw_result, "tracks", None)
    ) or []
    raw_scores_by_track: list[list[dict[str, float] | None]] = []
    for raw_tr in raw_tracks:
        raw_faces = (
            raw_tr.get("faces")
            if isinstance(raw_tr, dict)
            else getattr(raw_tr, "faces", None)
        ) or []
        raw_scores_by_track.append(_extract_flag_scores_list(raw_faces))

    result = (
        raw_result
        if isinstance(raw_result, IndexResult)
        else IndexResult.model_validate(raw_result)
    )

    index_job.npz_rel = (
        to_rel(result.index_npz_path, data_root) if result.index_npz_path else None
    )
    index_job.json_rel = (
        to_rel(result.index_json_path, data_root) if result.index_json_path else None
    )
    index_job.total_embeddings = int(result.total_embeddings)
    index_job.timings_ms = dict(result.timings_ms) if result.timings_ms is not None else None

    for t_idx, track in enumerate(result.tracks):
        db.add(
            IndexTrackRecord(
                index_id=index_job.id,
                track_id=int(track.track_id),
                first_t=float(track.first_t),
                last_t=float(track.last_t),
                n_observations=int(track.n_observations),
                short_track=bool(track.short_track),
                dwell_sec_in_zone=track.dwell_sec_in_zone,
                reason=track.reason,
                face_count=len(track.faces),
            )
        )
        track_scores = raw_scores_by_track[t_idx] if t_idx < len(raw_scores_by_track) else []
        for f_idx, face in enumerate(track.faces):
            f_scores = track_scores[f_idx] if f_idx < len(track_scores) else None
            db.add(
                IndexFaceRecord(
                    index_id=index_job.id,
                    track_id=int(track.track_id),
                    t=float(face.t),
                    quality_score=float(face.quality_score),
                    reliability=face.reliability,
                    match_ready=bool(face.match_ready),
                    flags=list(face.flags),
                    flag_scores=f_scores,
                    face_box=[float(v) for v in face.face_box] if face.face_box is not None else None,
                    crop_rel=to_rel(face.crop_path, data_root) if face.crop_path else None,
                    frame_rel=to_rel(face.frame_path, data_root) if face.frame_path else None,
                    embedding_rel=to_rel(face.embedding_path, data_root),
                    short_track=bool(track.short_track),
                )
            )

    db.commit()
    return result
