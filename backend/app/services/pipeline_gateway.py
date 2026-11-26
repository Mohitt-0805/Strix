"""Gateway adapting pipeline.adapter.get_run() safely for real and fake modes."""

import inspect
import os
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.app.models import Clip, FrameRecord, Run
from backend.app.services.fake_assets import materialize_fake_assets
from backend.app.services.storage import from_rel, to_rel
from pipeline.contract import PipelineResult


def _build_supported_kwargs(
    run_fn: Callable[..., Any],
    all_kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Filter optional pipeline kwargs using inspect.signature."""
    sig = inspect.signature(run_fn)
    accepts_var_kw = any(
        param.kind == inspect.Parameter.VAR_KEYWORD
        for param in sig.parameters.values()
    )
    if accepts_var_kw:
        return {k: v for k, v in all_kwargs.items() if v is not None or k in {"clip_path", "tx_offset_sec", "window_sec"}}

    required_keys = ("clip_path", "tx_offset_sec", "window_sec")
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
    progress_cb: Callable[[str, float | None], None] | None = None,
) -> PipelineResult:
    """Invoke pipeline.adapter.get_run(), normalize outputs, and persist frame rows."""
    # Ensure pipeline.adapter sees the configured fake/real mode even when loaded from .env.
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
        "atm_id": run.atm_id or "",
        "transaction_time": run.transaction_time.isoformat(),
        "sample_fps": run.sample_fps,
        "tracker": run.tracker,
        "out_dir": str(out_dir_abs),
        "zone_polygon_norm": clip.zone_polygon_norm,
        "progress_cb": progress_cb,
    }
    call_kwargs = _build_supported_kwargs(run_fn, candidate_kwargs)

    raw_result = run_fn(**call_kwargs)
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

    # Persist normalized result JSON and individual frame rows (frame_id as TEXT).
    run.result_json = normalized.model_dump(mode="json")
    for frame in normalized.best_frames:
        db.add(
            FrameRecord(
                run_id=run.id,
                frame_id=str(frame.frame_id),
                timestamp_sec=frame.timestamp_sec,
                quality_score=frame.quality_score,
                reliability=frame.reliability,
                flags=list(frame.flags),
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
