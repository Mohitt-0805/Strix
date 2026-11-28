"""Clip indexing endpoints (POST /clips/{id}/index, GET /clips/{id}/indexes, GET /indexes/{id})."""

from fastapi import APIRouter, Body, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.app.db import get_db
from backend.app.deps import get_app_settings, get_current_user
from backend.app.errors import AppError
from backend.app.models import (
    Clip,
    ClipIndex,
    IndexFaceRecord,
    IndexTrackRecord,
    User,
)
from backend.app.schemas import (
    IndexAcceptedResponse,
    IndexClipRequest,
    IndexDetailOut,
    IndexFaceOut,
    IndexStatusOut,
    IndexTrackOut,
)
from backend.app.services.jobs import JobManager
from backend.app.services.zones import get_valid_zone_ids
from backend.app.signing import signed_url_if_exists

router = APIRouter(tags=["indexes"])

MAX_INDEX_RANGE_SEC = 600.0


def enqueue_clip_index(
    *,
    db: Session,
    clip: Clip,
    user_id: int,
    settings: Settings,
    job_manager: JobManager,
    start_sec: float = 0.0,
    end_sec: float | None = None,
    sample_fps: float = 1.0,
    tracker: str = "iou",
    faces_per_track: int = 3,
    atm_id: str | None = None,
) -> ClipIndex:
    """Validate range/zone, create a ClipIndex row, and enqueue it on JobManager."""
    if end_sec is not None and (float(end_sec) - float(start_sec)) > MAX_INDEX_RANGE_SEC:
        raise AppError(
            status_code=422,
            code="INDEX_RANGE_TOO_LONG",
            detail=(
                f"Requested index range ({float(end_sec) - float(start_sec):.1f}s) "
                f"exceeds maximum {int(MAX_INDEX_RANGE_SEC)}s."
            ),
        )

    effective_end = (
        min(float(clip.duration_sec), float(start_sec) + MAX_INDEX_RANGE_SEC)
        if end_sec is None
        else min(float(end_sec), float(clip.duration_sec))
    )
    if effective_end <= float(start_sec):
        raise AppError(
            status_code=422,
            code="INVALID_ARGUMENT",
            detail=(
                f"end_sec ({effective_end:.2f}) must be greater than "
                f"start_sec ({float(start_sec):.2f})."
            ),
        )

    if clip.zone_polygon_norm is None and atm_id:
        valid_ids = get_valid_zone_ids()
        if atm_id not in valid_ids:
            raise AppError(
                status_code=422,
                code="ZONE_NOT_FOUND",
                detail=(
                    f"ATM zone '{atm_id}' not found. "
                    f"Valid zone ids: {', '.join(valid_ids)}."
                ),
            )

    job = ClipIndex(
        clip_id=clip.id,
        status="queued",
        stage="queued",
        progress=None,
        start_sec=float(start_sec),
        end_sec=effective_end,
        sample_fps=float(sample_fps),
        tracker=tracker,
        faces_per_track=int(faces_per_track),
        atm_id=atm_id,
        pipeline_mode=settings.pipeline_mode,
        created_by=user_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    job_manager.submit_index(job.id)
    return job


def _index_to_status_out(job: ClipIndex) -> IndexStatusOut:
    """Serialize ClipIndex ORM row into IndexStatusOut."""
    return IndexStatusOut(
        index_id=job.id,
        clip_id=job.clip_id,
        status=job.status,
        stage=job.stage,
        progress=job.progress,
        progress_message=job.progress_message,
        error_code=job.error_code,
        error_message=job.error_message,
        error_advice=job.error_advice,
        start_sec=job.start_sec,
        end_sec=job.end_sec,
        sample_fps=job.sample_fps,
        tracker=job.tracker,
        faces_per_track=job.faces_per_track,
        atm_id=job.atm_id,
        total_embeddings=job.total_embeddings,
        timings_ms=job.timings_ms,
        pipeline_mode=job.pipeline_mode,
        served_from_demo_pack=bool(job.served_from_demo_pack),
        requested_sample_fps=job.requested_sample_fps,
        effective_sample_fps=job.effective_sample_fps,
        warnings=list(job.warnings) if job.warnings is not None else None,
        coverage_start_sec=job.coverage_start_sec,
        coverage_end_sec=job.coverage_end_sec,
        created_by=job.created_by,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.post(
    "/clips/{clip_id}/index",
    response_model=IndexAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_clip_index(
    clip_id: str,
    request: Request,
    payload: IndexClipRequest = Body(default_factory=IndexClipRequest),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> IndexAcceptedResponse:
    """Queue a clip-wide face indexing job and return 202 {index_id, status}."""
    clip = db.get(Clip, clip_id)
    if clip is None:
        raise AppError(status_code=404, code="CLIP_NOT_FOUND", detail="Clip not found.")

    effective_atm = (
        payload.atm_id.strip()
        if payload.atm_id and payload.atm_id.strip()
        else clip.atm_id
    )
    job = enqueue_clip_index(
        db=db,
        clip=clip,
        user_id=current_user.id,
        settings=settings,
        job_manager=request.app.state.job_manager,
        start_sec=payload.start_sec,
        end_sec=payload.end_sec,
        sample_fps=payload.sample_fps,
        tracker=payload.tracker,
        faces_per_track=payload.faces_per_track,
        atm_id=effective_atm,
    )
    return IndexAcceptedResponse(index_id=job.id, status=job.status)


@router.get("/clips/{clip_id}/indexes", response_model=list[IndexStatusOut])
def list_clip_indexes(
    clip_id: str,
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[IndexStatusOut]:
    """List all indexing jobs for a clip newest-first."""
    clip = db.get(Clip, clip_id)
    if clip is None:
        raise AppError(status_code=404, code="CLIP_NOT_FOUND", detail="Clip not found.")
    jobs = (
        db.execute(
            select(ClipIndex)
            .where(ClipIndex.clip_id == clip_id)
            .order_by(ClipIndex.id.desc())
        )
        .scalars()
        .all()
    )
    return [_index_to_status_out(job) for job in jobs]


@router.get("/indexes/{index_id}", response_model=IndexDetailOut)
def get_clip_index_detail(
    index_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> IndexDetailOut:
    """Return index job status, progress, tracks (including faceless tracks), and faces."""
    job = db.get(ClipIndex, index_id)
    if job is None:
        raise AppError(status_code=404, code="INDEX_NOT_FOUND", detail="Index job not found.")

    track_rows = (
        db.execute(
            select(IndexTrackRecord)
            .where(IndexTrackRecord.index_id == job.id)
            .order_by(IndexTrackRecord.track_id.asc(), IndexTrackRecord.id.asc())
        )
        .scalars()
        .all()
    )
    face_rows = (
        db.execute(
            select(IndexFaceRecord)
            .where(IndexFaceRecord.index_id == job.id)
            .order_by(IndexFaceRecord.track_id.asc(), IndexFaceRecord.t.asc(), IndexFaceRecord.id.asc())
        )
        .scalars()
        .all()
    )

    faces_by_track: dict[int, list[IndexFaceOut]] = {}
    for row in face_rows:
        faces_by_track.setdefault(row.track_id, []).append(
            IndexFaceOut(
                id=row.id,
                track_id=row.track_id,
                t=row.t,
                quality_score=row.quality_score,
                reliability=row.reliability,
                match_ready=row.match_ready,
                flags=list(row.flags or []),
                flag_scores=row.flag_scores,
                face_box=row.face_box,
                short_track=row.short_track,
                crop_url=signed_url_if_exists(row.crop_rel, current_user.id, settings),
                frame_url=signed_url_if_exists(row.frame_rel, current_user.id, settings),
            )
        )

    track_outs = [
        IndexTrackOut(
            track_id=tr.track_id,
            first_t=tr.first_t,
            last_t=tr.last_t,
            n_observations=tr.n_observations,
            short_track=tr.short_track,
            confidence_note="low confidence (short track)" if tr.short_track else None,
            dwell_sec_in_zone=tr.dwell_sec_in_zone,
            reason=tr.reason,
            face_count=tr.face_count,
            faces=faces_by_track.get(tr.track_id, []),
        )
        for tr in track_rows
    ]

    status_out = _index_to_status_out(job)
    return IndexDetailOut(**status_out.model_dump(), tracks=track_outs)
