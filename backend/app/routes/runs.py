"""Clip processing and run result endpoints."""

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import FAKE_BANNER_TEXT, HUMAN_VERIFICATION_NOTICE, Settings
from backend.app.db import get_db
from backend.app.deps import get_app_settings, get_current_user
from backend.app.errors import AppError
from backend.app.models import Clip, FrameRecord, Run, User
from backend.app.schemas import (
    FrameOut,
    ProcessClipRequest,
    RunAcceptedResponse,
    RunResultOut,
    RunStatusOut,
)
from backend.app.services.jobs import JobManager
from backend.app.services.zones import get_valid_zone_ids
from backend.app.signing import make_signed_file_url, signed_url_if_exists

router = APIRouter(tags=["runs"])

MAX_SAMPLED_FRAMES = 200


def _to_naive_local(dt: datetime, display_tz: str) -> datetime:
    """Normalize an incoming datetime to naive local DISPLAY_TZ."""
    if dt.tzinfo is not None:
        return dt.astimezone(ZoneInfo(display_tz)).replace(tzinfo=None)
    return dt


def build_run_result_out(
    db: Session,
    run: Run,
    clip: Clip,
    user_id: int,
    settings: Settings,
) -> RunResultOut:
    """Hydrate a finished run's result_json and FrameRecord rows with signed URLs."""
    raw = run.result_json or {}
    frame_rows = (
        db.execute(
            select(FrameRecord)
            .where(FrameRecord.run_id == run.id)
            .order_by(FrameRecord.id.asc())
        )
        .scalars()
        .all()
    )

    frame_outs: list[FrameOut] = []
    for row in frame_rows:
        enh = row.enhancement
        enhanced_url = (
            signed_url_if_exists(enh["enhanced_path"], user_id, settings)
            if enh and enh.get("enhanced_path")
            else None
        )
        frame_outs.append(
            FrameOut(
                frame_id=row.frame_id,
                frame_path=row.frame_path_rel,
                crop_path=row.crop_path_rel,
                embedding_path=row.embedding_path_rel,
                timestamp_sec=row.timestamp_sec,
                quality_score=row.quality_score,
                reliability=row.reliability,
                flags=list(row.flags or []),
                flag_scores=row.flag_scores,
                face_box=row.face_box,
                enhanced=row.enhanced,
                enhancement=enh,
                metrics=dict(row.metrics or {}),
                match_ready=row.match_ready,
                rank_reason=row.rank_reason,
                selected=row.selected,
                image_url=signed_url_if_exists(row.frame_path_rel, user_id, settings),
                crop_url=signed_url_if_exists(row.crop_path_rel, user_id, settings),
                enhanced_url=enhanced_url,
            )
        )

    show_sel = (len(frame_outs) == 0) or all(
        fr.reliability == "Low" for fr in frame_outs
    )
    return RunResultOut(
        run_id=run.id,
        clip_id=run.clip_id,
        pipeline_mode=run.pipeline_mode,
        served_from_demo_pack=bool(run.served_from_demo_pack),
        banner=FAKE_BANNER_TEXT if run.pipeline_mode == "fake" else None,
        notice=HUMAN_VERIFICATION_NOTICE,
        video_url=make_signed_file_url(clip.stored_path, user_id, settings),
        transaction_time=str(raw.get("transaction_time") or run.transaction_time.isoformat()),
        person_track_id=raw.get("person_track_id"),
        best_frames=frame_outs,
        link_confidence=raw.get("link_confidence"),
        link_reason=raw.get("link_reason"),
        link_low_margin=bool(run.link_low_margin),
        selection_reason=raw.get("selection_reason"),
        show_selection_reason=show_sel,
        timings_ms=raw.get("timings_ms"),
        requested_sample_fps=(
            run.requested_sample_fps
            if run.requested_sample_fps is not None
            else raw.get("requested_sample_fps")
        ),
        effective_sample_fps=(
            run.effective_sample_fps
            if run.effective_sample_fps is not None
            else raw.get("effective_sample_fps")
        ),
        warnings=(
            list(run.warnings)
            if run.warnings is not None
            else raw.get("warnings")
        ),
        coverage_start_sec=(
            run.coverage_start_sec
            if run.coverage_start_sec is not None
            else raw.get("coverage_start_sec")
        ),
        coverage_end_sec=(
            run.coverage_end_sec
            if run.coverage_end_sec is not None
            else raw.get("coverage_end_sec")
        ),
    )


def _run_to_status_out(
    db: Session,
    run: Run,
    clip: Clip | None,
    user_id: int,
    settings: Settings,
) -> RunStatusOut:
    """Serialize a Run row, attaching hydrated result when status is 'done'."""
    hydrated = (
        build_run_result_out(db, run, clip, user_id, settings)
        if run.status == "done" and clip is not None
        else None
    )
    return RunStatusOut(
        run_id=run.id,
        clip_id=run.clip_id,
        status=run.status,
        stage=run.stage,
        progress=run.progress,
        progress_message=run.progress_message,
        error_code=run.error_code,
        error_message=run.error_message,
        error_advice=run.error_advice,
        transaction_time=run.transaction_time,
        tx_offset_sec=run.tx_offset_sec,
        window_sec=run.window_sec,
        sample_fps=run.sample_fps,
        tracker=run.tracker,
        atm_id=run.atm_id,
        pipeline_mode=run.pipeline_mode,
        served_from_demo_pack=bool(run.served_from_demo_pack),
        link_low_margin=bool(run.link_low_margin),
        requested_sample_fps=run.requested_sample_fps,
        effective_sample_fps=run.effective_sample_fps,
        warnings=list(run.warnings) if run.warnings is not None else None,
        coverage_start_sec=run.coverage_start_sec,
        coverage_end_sec=run.coverage_end_sec,
        created_by=run.created_by,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        result=hydrated,
    )


@router.post(
    "/clips/{clip_id}/process",
    response_model=RunAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def process_clip(
    clip_id: str,
    payload: ProcessClipRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> RunAcceptedResponse:
    """Validate transaction time and window cap, queue run, and return 202."""
    estimated_frames = (2.0 * payload.window_sec + 2.0) * payload.sample_fps
    if estimated_frames > MAX_SAMPLED_FRAMES:
        raise AppError(
            status_code=422,
            code="WINDOW_CAP_EXCEEDED",
            detail=(
                f"(2 * window_sec + 2) * sample_fps must be <= {MAX_SAMPLED_FRAMES} "
                f"(got {estimated_frames:.1f})."
            ),
        )

    clip = db.get(Clip, clip_id)
    if clip is None:
        raise AppError(status_code=404, code="CLIP_NOT_FOUND", detail="Clip not found.")

    if clip.clip_start_time is None:
        raise AppError(
            status_code=422,
            code="CLIP_START_TIME_REQUIRED",
            detail=(
                "Clip start time is missing. Set clip_start_time via "
                "PATCH /clips/{id} before processing."
            ),
        )

    tx_local = _to_naive_local(payload.transaction_time, settings.display_tz)
    tx_offset_sec = round((tx_local - clip.clip_start_time).total_seconds(), 3)
    if tx_offset_sec < 0.0 or tx_offset_sec > clip.duration_sec:
        raise AppError(
            status_code=422,
            code="TX_OUT_OF_RANGE",
            detail=(
                f"Transaction time ({tx_local.isoformat()}) is outside clip bounds: "
                f"clip_start_time={clip.clip_start_time.isoformat()}, "
                f"duration_sec={clip.duration_sec:.2f}, "
                f"tx_offset_sec={tx_offset_sec:.2f}. "
                f"Check for UTC vs {settings.display_tz} mismatch."
            ),
        )

    effective_atm_id = (
        payload.atm_id.strip()
        if payload.atm_id and payload.atm_id.strip()
        else clip.atm_id
    )
    if clip.zone_polygon_norm is None and effective_atm_id:
        valid_ids = get_valid_zone_ids()
        if effective_atm_id not in valid_ids:
            raise AppError(
                status_code=422,
                code="ZONE_NOT_FOUND",
                detail=(
                    f"ATM zone '{effective_atm_id}' not found. "
                    f"Valid zone ids: {', '.join(valid_ids)}."
                ),
            )

    run = Run(
        clip_id=clip.id,
        status="queued",
        stage="queued",
        progress=None,
        transaction_time=tx_local,
        tx_offset_sec=tx_offset_sec,
        window_sec=payload.window_sec,
        sample_fps=payload.sample_fps,
        tracker=payload.tracker,
        atm_id=effective_atm_id,
        pipeline_mode=settings.pipeline_mode,
        created_by=current_user.id,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    job_manager: JobManager = request.app.state.job_manager
    job_manager.submit_run(run.id)
    return RunAcceptedResponse(run_id=run.id, status=run.status)


@router.get("/runs/{run_id}", response_model=RunStatusOut)
def get_run_status(
    run_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> RunStatusOut:
    """Return run status, progress, error info, and hydrated result when done."""
    run = db.get(Run, run_id)
    if run is None:
        raise AppError(status_code=404, code="RUN_NOT_FOUND", detail="Run not found.")
    clip = db.get(Clip, run.clip_id)
    return _run_to_status_out(db, run, clip, current_user.id, settings)


@router.get("/clips/{clip_id}/runs", response_model=list[RunStatusOut])
def list_clip_runs(
    clip_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> list[RunStatusOut]:
    """List all processing runs for a clip newest-first."""
    clip = db.get(Clip, clip_id)
    if clip is None:
        raise AppError(status_code=404, code="CLIP_NOT_FOUND", detail="Clip not found.")
    runs = (
        db.execute(select(Run).where(Run.clip_id == clip_id).order_by(Run.id.desc()))
        .scalars()
        .all()
    )
    return [_run_to_status_out(db, run, clip, current_user.id, settings) for run in runs]


@router.get("/runs/{run_id}/result", response_model=RunResultOut)
def get_run_result(
    run_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> RunResultOut:
    """Return the hydrated PipelineResult for a completed run."""
    run = db.get(Run, run_id)
    if run is None:
        raise AppError(status_code=404, code="RUN_NOT_FOUND", detail="Run not found.")
    if run.status in {"queued", "running"}:
        raise AppError(
            status_code=409,
            code="RUN_NOT_DONE",
            detail=f"Run {run_id} is still '{run.status}'.",
        )
    if run.status == "failed":
        raise AppError(
            status_code=422,
            code=run.error_code or "PIPELINE_FAILED",
            detail=run.error_message or "Pipeline execution failed.",
        )

    clip = db.get(Clip, run.clip_id)
    if clip is None:
        raise AppError(status_code=404, code="CLIP_NOT_FOUND", detail="Clip not found.")
    return build_run_result_out(db, run, clip, current_user.id, settings)
