"""Clip upload, metadata inspection, editing, and Range-capable video endpoints."""

import hashlib
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.audit import record_audit
from backend.app.config import ACCEPTED_VIDEO_EXTENSIONS, Settings
from backend.app.db import get_db
from backend.app.deps import get_app_settings, get_client_ip, get_current_user
from backend.app.errors import AppError
from backend.app.models import Clip, User
from backend.app.routes.files import stream_file_response
from backend.app.schemas import ClipOut, ClipPatchRequest
from backend.app.services.probe import probe_video
from backend.app.services.storage import from_rel, sanitize_filename, to_rel
from backend.app.signing import make_signed_file_url

router = APIRouter(prefix="/clips", tags=["clips"])

UPLOAD_CHUNK_SIZE = 1024 * 1024


def _normalize_local_datetime(dt: datetime, display_tz: str) -> datetime:
    """Convert a datetime to naive local DISPLAY_TZ."""
    if dt.tzinfo is not None:
        return dt.astimezone(ZoneInfo(display_tz)).replace(tzinfo=None)
    return dt


def _parse_optional_datetime(raw: str | None, display_tz: str) -> datetime | None:
    """Parse an optional ISO-8601 form datetime string into naive local time."""
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise AppError(
            status_code=422,
            code="INVALID_DATETIME",
            detail="clip_start_time must be a valid ISO-8601 datetime.",
        ) from exc
    return _normalize_local_datetime(parsed, display_tz)


def clip_to_out(clip: Clip, user_id: int, settings: Settings) -> ClipOut:
    """Serialize a Clip ORM row with a signed video_url for the requesting user."""
    video_url = make_signed_file_url(clip.stored_path, user_id, settings)
    return ClipOut(
        id=clip.id,
        original_filename=clip.original_filename,
        stored_path=clip.stored_path,
        sha256=clip.sha256,
        size_bytes=clip.size_bytes,
        duration_sec=clip.duration_sec,
        fps=clip.fps,
        width=clip.width,
        height=clip.height,
        codec=clip.codec,
        container=clip.container,
        rotation=clip.rotation,
        clip_start_time=clip.clip_start_time,
        clip_start_source=clip.clip_start_source,
        atm_id=clip.atm_id,
        zone_polygon_norm=clip.zone_polygon_norm,
        notes=clip.notes,
        uploaded_by=clip.uploaded_by,
        created_at=clip.created_at,
        video_url=video_url,
    )


def _cleanup_dir(path: Path) -> None:
    """Remove temporary upload directory on aborted or failed upload."""
    shutil.rmtree(path, ignore_errors=True)


@router.post("", response_model=ClipOut, status_code=status.HTTP_201_CREATED)
async def upload_clip(
    request: Request,
    file: UploadFile = File(...),
    atm_id: str | None = Form(None),
    clip_start_time: str | None = Form(None),
    notes: str | None = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> ClipOut:
    """Stream, hash, validate, probe, and store an uploaded CCTV clip."""
    safe_name = sanitize_filename(file.filename)
    ext = Path(safe_name).suffix.lower().lstrip(".")
    if ext not in ACCEPTED_VIDEO_EXTENSIONS:
        raise AppError(
            status_code=422,
            code="INVALID_EXTENSION",
            detail=(
                f"Unsupported file extension '.{ext or 'none'}'. "
                f"Accepted: {', '.join(ACCEPTED_VIDEO_EXTENSIONS)}."
            ),
        )

    parsed_start = _parse_optional_datetime(clip_start_time, settings.display_tz)

    clip_id = str(uuid.uuid4())
    data_root = settings.resolved_data_dir
    clip_dir = data_root / "uploads" / clip_id
    clip_dir.mkdir(parents=True, exist_ok=True)
    temp_path = clip_dir / f".uploading_{safe_name}"
    final_path = clip_dir / safe_name

    max_bytes = settings.max_upload_mb * 1024 * 1024
    digest = hashlib.sha256()
    size_bytes = 0

    try:
        with temp_path.open("wb") as out_fh:
            while True:
                chunk = await file.read(UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                size_bytes += len(chunk)
                if size_bytes > max_bytes:
                    raise AppError(
                        status_code=413,
                        code="FILE_TOO_LARGE",
                        detail=f"Upload exceeds MAX_UPLOAD_MB ({settings.max_upload_mb} MB).",
                    )
                digest.update(chunk)
                out_fh.write(chunk)

        if size_bytes == 0:
            raise AppError(
                status_code=422,
                code="UNREADABLE_VIDEO",
                detail=(
                    "Uploaded file is empty. Export the clip as MP4 (H.264) "
                    "from the DVR/NVR software, or convert it with FFmpeg."
                ),
            )

        meta = probe_video(temp_path, settings.display_tz)
        temp_path.replace(final_path)
    except Exception:
        _cleanup_dir(clip_dir)
        raise
    finally:
        await file.close()

    if parsed_start is not None:
        final_start = parsed_start
        start_source = "user"
    elif meta.creation_time_local is not None:
        final_start = meta.creation_time_local
        start_source = "ffprobe_converted"
    else:
        final_start = None
        start_source = "unknown"

    stored_rel = to_rel(final_path, data_root)
    sha256_hex = digest.hexdigest()

    clip = Clip(
        id=clip_id,
        original_filename=safe_name,
        stored_path=stored_rel,
        sha256=sha256_hex,
        size_bytes=size_bytes,
        duration_sec=meta.duration_sec,
        fps=meta.fps,
        width=meta.width,
        height=meta.height,
        codec=meta.codec,
        container=meta.container,
        rotation=meta.rotation,
        clip_start_time=final_start,
        clip_start_source=start_source,
        atm_id=atm_id.strip() if atm_id and atm_id.strip() else None,
        zone_polygon_norm=None,
        notes=notes.strip() if notes and notes.strip() else None,
        uploaded_by=current_user.id,
    )
    db.add(clip)
    db.commit()
    db.refresh(clip)

    record_audit(
        db,
        action="upload",
        user_id=current_user.id,
        username=current_user.username,
        role=current_user.role,
        target_type="clip",
        target_id=clip.id,
        details={
            "filename": clip.original_filename,
            "sha256": clip.sha256,
            "size_bytes": clip.size_bytes,
        },
        ip=get_client_ip(request),
    )
    return clip_to_out(clip, current_user.id, settings)


@router.get("", response_model=list[ClipOut])
def list_clips(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> list[ClipOut]:
    """List uploaded clips newest-first."""
    clips = db.execute(select(Clip).order_by(Clip.created_at.desc())).scalars().all()
    return [clip_to_out(clip, current_user.id, settings) for clip in clips]


@router.get("/{clip_id}", response_model=ClipOut)
def get_clip(
    clip_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> ClipOut:
    """Retrieve metadata and a signed video URL for a single clip."""
    clip = db.get(Clip, clip_id)
    if clip is None:
        raise AppError(status_code=404, code="CLIP_NOT_FOUND", detail="Clip not found.")
    return clip_to_out(clip, current_user.id, settings)


@router.patch("/{clip_id}", response_model=ClipOut)
def patch_clip(
    clip_id: str,
    payload: ClipPatchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> ClipOut:
    """Update editable clip metadata (start time, ATM ID, zone polygon, notes)."""
    clip = db.get(Clip, clip_id)
    if clip is None:
        raise AppError(status_code=404, code="CLIP_NOT_FOUND", detail="Clip not found.")

    fields_set = payload.model_fields_set
    if "clip_start_time" in fields_set:
        if payload.clip_start_time is None:
            clip.clip_start_time = None
            clip.clip_start_source = "unknown"
        else:
            clip.clip_start_time = _normalize_local_datetime(
                payload.clip_start_time, settings.display_tz
            )
            clip.clip_start_source = "user"

    if "atm_id" in fields_set:
        clip.atm_id = payload.atm_id.strip() if payload.atm_id else None
    if "zone_polygon_norm" in fields_set:
        clip.zone_polygon_norm = payload.zone_polygon_norm
    if "notes" in fields_set:
        clip.notes = payload.notes.strip() if payload.notes else None

    db.commit()
    db.refresh(clip)
    return clip_to_out(clip, current_user.id, settings)


@router.get("/{clip_id}/video")
def stream_clip_video(
    clip_id: str,
    request: Request,
    download: int = Query(0, ge=0, le=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> Response:
    """Stream the uploaded clip video with HTTP Range support."""
    clip = db.get(Clip, clip_id)
    if clip is None:
        raise AppError(status_code=404, code="CLIP_NOT_FOUND", detail="Clip not found.")

    target = from_rel(
        clip.stored_path,
        settings.resolved_data_dir,
        allowed_roots=("uploads",),
    )
    if not target.is_file():
        raise AppError(status_code=404, code="FILE_NOT_FOUND", detail="Clip file missing.")

    download_filename: str | None = None
    if download == 1:
        record_audit(
            db,
            action="download_video",
            user_id=current_user.id,
            username=current_user.username,
            role=current_user.role,
            target_type="clip",
            target_id=clip.id,
            details={"filename": clip.original_filename},
            ip=get_client_ip(request),
        )
        download_filename = clip.original_filename

    return stream_file_response(request, target, download_filename=download_filename)
