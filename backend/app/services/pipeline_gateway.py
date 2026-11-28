"""Gateway adapting pipeline.adapter run() and index_clip() safely."""

import inspect
import logging
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.app.errors import AppError
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
from backend.app.services.zones import get_valid_zone_ids
from pipeline.contract import IndexResult, PipelineResult

logger = logging.getLogger(__name__)

_INTERNAL_REL_PREFIXES = ("outputs/", "data/outputs/", "uploads/", "data/uploads/")


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


def _ingest_asset_path(
    raw_path: str | None,
    *,
    dest_dir: Path,
    data_root: Path,
    label: str,
    prefix: str = "",
    seen_dests: dict[Path, Path] | None = None,
) -> str | None:
    """Normalise an asset path to DATA_DIR-relative, copying external files into dest_dir."""
    if not raw_path or not str(raw_path).strip():
        return None
    raw = str(raw_path).strip().replace("\\", "/")
    p = Path(raw)
    resolved_root = data_root.resolve()
    external_src: Path | None = None

    if p.is_absolute():
        resolved_p = p.resolve()
        if resolved_p != resolved_root and resolved_p.is_relative_to(resolved_root):
            return to_rel(resolved_p, data_root)
        external_src = resolved_p
    else:
        if ".." in p.parts:
            raise AppError(
                status_code=403,
                code="INVALID_PATH",
                detail="Path traversal ('..') is not allowed.",
            )
        cwd_cand = (Path.cwd() / p).resolve()
        if cwd_cand.exists() and not cwd_cand.is_relative_to(resolved_root):
            external_src = cwd_cand
        elif raw.startswith(_INTERNAL_REL_PREFIXES) or (resolved_root / p).resolve().exists():
            return to_rel(raw, data_root)
        else:
            external_src = cwd_cand

    if not external_src.is_file():
        logger.warning(
            "Missing external asset for %s at '%s'; storing null path.",
            label,
            external_src,
        )
        return None

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = (dest_dir / external_src.name).resolve()
    if seen_dests is not None:
        existing_src = seen_dests.get(dest_path)
        if existing_src is not None and existing_src != external_src:
            safe_prefix = f"{prefix}_" if prefix else "ext_"
            dest_path = (dest_dir / f"{safe_prefix}{external_src.name}").resolve()
        seen_dests[dest_path] = external_src

    if external_src != dest_path:
        shutil.copy2(external_src, dest_path)
    return to_rel(dest_path, data_root)


def _known_atm_id(primary_atm_id: str | None, clip_atm_id: str | None) -> str | None:
    """Return atm_id iff it exists in pipeline/config/atm_zone.json, else None."""
    raw = (primary_atm_id if primary_atm_id is not None else clip_atm_id or "").strip()
    if not raw:
        return None
    return raw if raw in set(get_valid_zone_ids()) else None


def _normalize_result_paths(
    result: PipelineResult,
    settings: Settings,
    *,
    dest_dir: Path,
) -> PipelineResult:
    """Copy any external assets into dest_dir and convert paths to DATA_DIR-relative."""
    data_root = settings.resolved_data_dir
    seen_dests: dict[Path, Path] = {}
    norm_frames = []
    for frame in result.best_frames:
        fid = str(frame.frame_id)
        frame_rel = _ingest_asset_path(
            frame.frame_path,
            dest_dir=dest_dir,
            data_root=data_root,
            label=f"frame {fid}",
            prefix=f"frame_{fid}",
            seen_dests=seen_dests,
        )
        crop_rel = _ingest_asset_path(
            frame.crop_path,
            dest_dir=dest_dir,
            data_root=data_root,
            label=f"crop {fid}",
            prefix=f"crop_{fid}",
            seen_dests=seen_dests,
        )
        emb_rel = _ingest_asset_path(
            frame.embedding_path,
            dest_dir=dest_dir,
            data_root=data_root,
            label=f"embedding {fid}",
            prefix=f"emb_{fid}",
            seen_dests=seen_dests,
        )
        enh = frame.enhancement
        if enh is not None and enh.enhanced_path:
            enh_rel = _ingest_asset_path(
                enh.enhanced_path,
                dest_dir=dest_dir,
                data_root=data_root,
                label=f"enhanced {fid}",
                prefix=f"enh_{fid}",
                seen_dests=seen_dests,
            )
            enh = enh.model_copy(update={"enhanced_path": enh_rel})
        norm_frames.append(
            frame.model_copy(
                update={
                    "frame_path": frame_rel,
                    "crop_path": crop_rel,
                    "embedding_path": emb_rel,
                    "enhancement": enh,
                }
            )
        )
    return result.model_copy(update={"best_frames": norm_frames})


def _extract_sampling_meta(
    raw_result: Any, validated_result: PipelineResult | IndexResult
) -> dict[str, Any]:
    """Extract optional sampling rate, warnings, and coverage window fields."""
    if isinstance(raw_result, dict):
        req_fps = raw_result.get("requested_sample_fps")
        eff_fps = raw_result.get("effective_sample_fps")
        raw_warnings = raw_result.get("warnings")
        cov_start = raw_result.get("coverage_start_sec")
        cov_end = raw_result.get("coverage_end_sec")
    else:
        req_fps = getattr(validated_result, "requested_sample_fps", None)
        eff_fps = getattr(validated_result, "effective_sample_fps", None)
        raw_warnings = getattr(validated_result, "warnings", None)
        cov_start = getattr(validated_result, "coverage_start_sec", None)
        cov_end = getattr(validated_result, "coverage_end_sec", None)

    warnings_val = (
        [str(w) for w in raw_warnings if str(w).strip()]
        if isinstance(raw_warnings, list)
        else None
    )
    return {
        "requested_sample_fps": float(req_fps) if req_fps is not None else None,
        "effective_sample_fps": float(eff_fps) if eff_fps is not None else None,
        "warnings": warnings_val,
        "coverage_start_sec": float(cov_start) if cov_start is not None else None,
        "coverage_end_sec": float(cov_end) if cov_end is not None else None,
    }


def _sanitize_raw_warnings(raw_result: Any) -> Any:
    """Ensure dict raw_result with warnings=None passes Pydantic list[str] validation."""
    if isinstance(raw_result, dict) and "warnings" in raw_result and raw_result["warnings"] is None:
        return {**raw_result, "warnings": []}
    return raw_result


def _sync_pipeline_env(settings: Settings) -> None:
    """Propagate backend pipeline env settings to os.environ before importing adapter."""
    os.environ["USE_FAKE_PIPELINE"] = "1" if settings.use_fake_pipeline else "0"
    if settings.demo_pack_dir is not None:
        os.environ["DEMO_PACK_DIR"] = settings.demo_pack_dir.strip()


def execute_pipeline_for_run(
    *,
    db: Session,
    run: Run,
    clip: Clip,
    settings: Settings,
    progress_cb: Callable[[Any], None] | None = None,
) -> PipelineResult:
    """Invoke pipeline.adapter.get_run(), ingest outputs, and persist frame rows."""
    _sync_pipeline_env(settings)
    from pipeline.adapter import get_run

    run_fn = get_run()
    data_root = settings.resolved_data_dir
    clip_abs_path = from_rel(clip.stored_path, data_root, allowed_roots=("uploads",))
    out_dir_abs = (data_root / "outputs" / clip.id / f"run_{run.id}").resolve()
    out_dir_abs.mkdir(parents=True, exist_ok=True)

    known_atm = _known_atm_id(run.atm_id, clip.atm_id)
    candidate_kwargs: dict[str, Any] = {
        "clip_path": str(clip_abs_path),
        "tx_offset_sec": round(float(run.tx_offset_sec), 3),
        "window_sec": run.window_sec,
        "transaction_time": run.transaction_time.isoformat(),
        "sample_fps": run.sample_fps,
        "tracker": run.tracker,
        "out_dir": str(out_dir_abs),
        "progress_cb": progress_cb,
    }
    if clip.zone_polygon_norm is not None:
        candidate_kwargs["zone_polygon_norm"] = clip.zone_polygon_norm
    if known_atm is not None:
        candidate_kwargs["atm_id"] = known_atm

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
        else PipelineResult.model_validate(_sanitize_raw_warnings(raw_result))
    )
    sampling_meta = _extract_sampling_meta(raw_result, result)
    served_from_demo_pack = bool(getattr(result, "served_from_demo_pack", False))

    if settings.use_fake_pipeline and not served_from_demo_pack:
        result = materialize_fake_assets(
            result,
            clip_id=clip.id,
            run_id=run.id,
            original_filename=clip.original_filename,
            data_dir=data_root,
            embed_dim=settings.embed_dim,
        )

    normalized = _normalize_result_paths(result, settings, dest_dir=out_dir_abs)
    result_dump = normalized.model_dump(mode="json")
    result_dump["served_from_demo_pack"] = served_from_demo_pack
    result_dump["requested_sample_fps"] = sampling_meta["requested_sample_fps"]
    result_dump["effective_sample_fps"] = sampling_meta["effective_sample_fps"]
    result_dump["warnings"] = sampling_meta["warnings"]
    result_dump["coverage_start_sec"] = sampling_meta["coverage_start_sec"]
    result_dump["coverage_end_sec"] = sampling_meta["coverage_end_sec"]
    for idx, scores in enumerate(raw_flag_scores):
        if scores is not None and idx < len(result_dump.get("best_frames", [])):
            result_dump["best_frames"][idx]["flag_scores"] = scores

    run.served_from_demo_pack = served_from_demo_pack
    run.link_low_margin = bool(normalized.link_low_margin)
    run.requested_sample_fps = sampling_meta["requested_sample_fps"]
    run.effective_sample_fps = sampling_meta["effective_sample_fps"]
    run.warnings = sampling_meta["warnings"]
    run.coverage_start_sec = sampling_meta["coverage_start_sec"]
    run.coverage_end_sec = sampling_meta["coverage_end_sec"]
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
    """Invoke pipeline.adapter.get_index_clip(), ingest assets, and persist track/face rows."""
    _sync_pipeline_env(settings)
    from pipeline.adapter import get_index_clip

    index_fn = get_index_clip()
    data_root = settings.resolved_data_dir
    clip_abs_path = from_rel(clip.stored_path, data_root, allowed_roots=("uploads",))
    out_dir_abs = (data_root / "outputs" / clip.id / f"index_{index_job.id}").resolve()
    out_dir_abs.mkdir(parents=True, exist_ok=True)

    known_atm = _known_atm_id(index_job.atm_id, clip.atm_id)
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
    if known_atm is not None:
        candidate_kwargs["atm_id"] = known_atm

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
        else IndexResult.model_validate(_sanitize_raw_warnings(raw_result))
    )
    sampling_meta = _extract_sampling_meta(raw_result, result)
    served_from_demo_pack = bool(getattr(result, "served_from_demo_pack", False))
    seen_dests: dict[Path, Path] = {}

    npz_rel = _ingest_asset_path(
        result.index_npz_path,
        dest_dir=out_dir_abs,
        data_root=data_root,
        label=f"index {index_job.id} npz",
        prefix="idx",
        seen_dests=seen_dests,
    )
    json_rel = _ingest_asset_path(
        result.index_json_path,
        dest_dir=out_dir_abs,
        data_root=data_root,
        label=f"index {index_job.id} json",
        prefix="idx",
        seen_dests=seen_dests,
    )

    index_job.served_from_demo_pack = served_from_demo_pack
    index_job.requested_sample_fps = sampling_meta["requested_sample_fps"]
    index_job.effective_sample_fps = sampling_meta["effective_sample_fps"]
    index_job.warnings = sampling_meta["warnings"]
    index_job.coverage_start_sec = sampling_meta["coverage_start_sec"]
    index_job.coverage_end_sec = sampling_meta["coverage_end_sec"]
    index_job.npz_rel = npz_rel
    index_job.json_rel = json_rel
    index_job.total_embeddings = int(result.total_embeddings)
    index_job.timings_ms = dict(result.timings_ms) if result.timings_ms is not None else None

    normalized_tracks = []
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
        norm_faces = []
        for f_idx, face in enumerate(track.faces):
            f_scores = track_scores[f_idx] if f_idx < len(track_scores) else None
            tag = f"t{track.track_id}_f{f_idx}"
            crop_rel = _ingest_asset_path(
                face.crop_path,
                dest_dir=out_dir_abs,
                data_root=data_root,
                label=f"index {index_job.id} {tag} crop",
                prefix=f"crop_{tag}",
                seen_dests=seen_dests,
            )
            frame_rel = _ingest_asset_path(
                face.frame_path,
                dest_dir=out_dir_abs,
                data_root=data_root,
                label=f"index {index_job.id} {tag} frame",
                prefix=f"frame_{tag}",
                seen_dests=seen_dests,
            )
            emb_rel = _ingest_asset_path(
                face.embedding_path,
                dest_dir=out_dir_abs,
                data_root=data_root,
                label=f"index {index_job.id} {tag} embedding",
                prefix=f"emb_{tag}",
                seen_dests=seen_dests,
            )
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
                    crop_rel=crop_rel,
                    frame_rel=frame_rel,
                    embedding_rel=emb_rel,
                    short_track=bool(track.short_track),
                )
            )
            norm_faces.append(
                face.model_copy(
                    update={
                        "crop_path": crop_rel,
                        "frame_path": frame_rel,
                        "embedding_path": emb_rel,
                    }
                )
            )
        normalized_tracks.append(track.model_copy(update={"faces": norm_faces}))

    db.commit()
    return result.model_copy(
        update={
            "tracks": normalized_tracks,
            "index_npz_path": npz_rel,
            "index_json_path": json_rel,
            "served_from_demo_pack": served_from_demo_pack,
        }
    )
