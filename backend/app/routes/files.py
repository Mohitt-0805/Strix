"""Signed /files route and shared HTTP Range streaming helper."""

import mimetypes
from collections.abc import Iterator
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy.orm import Session

from backend.app.audit import record_audit
from backend.app.config import ACCEPTED_VIDEO_EXTENSIONS, Settings
from backend.app.db import get_db
from backend.app.deps import get_app_settings, get_client_ip
from backend.app.errors import AppError, error_payload
from backend.app.models import User
from backend.app.services.storage import from_rel
from backend.app.signing import verify_signed_file_params

router = APIRouter(tags=["files"])

CHUNK_SIZE = 64 * 1024
_EXTRA_MIME_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".wmv": "video/x-ms-wmv",
    ".flv": "video/x-flv",
    ".mpeg": "video/mpeg",
    ".mpg": "video/mpeg",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}


def guess_media_type(path: Path) -> str:
    """Return a sensible MIME type for video and image files."""
    ext = path.suffix.lower()
    if ext in _EXTRA_MIME_TYPES:
        return _EXTRA_MIME_TYPES[ext]
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _parse_range_header(range_header: str, file_size: int) -> tuple[int, int] | None:
    """Parse a single HTTP byte Range header; return (start, end) or None if invalid."""
    raw = range_header.strip()
    if not raw.lower().startswith("bytes="):
        return None
    spec = raw[6:].strip()
    if "," in spec or "-" not in spec:
        return None

    start_s, end_s = spec.split("-", 1)
    start_s = start_s.strip()
    end_s = end_s.strip()

    try:
        if not start_s:
            # Suffix byte-range: bytes=-N
            suffix = int(end_s)
            if suffix <= 0 or file_size <= 0:
                return None
            start = max(0, file_size - suffix)
            end = file_size - 1
            return start, end

        start = int(start_s)
        end = int(end_s) if end_s else file_size - 1
    except ValueError:
        return None

    if start < 0 or end < start or start >= file_size:
        return None
    return start, min(end, file_size - 1)


def _iter_file_range(path: Path, start: int, length: int) -> Iterator[bytes]:
    """Yield chunks from path starting at byte offset start for length bytes."""
    remaining = length
    with path.open("rb") as fh:
        fh.seek(start)
        while remaining > 0:
            chunk = fh.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def stream_file_response(
    request: Request,
    file_path: Path,
    *,
    download_filename: str | None = None,
) -> Response:
    """Stream a file with full HTTP 206 Range request support."""
    if not file_path.is_file():
        raise AppError(status_code=404, code="FILE_NOT_FOUND", detail="File not found.")

    file_size = file_path.stat().st_size
    media_type = guess_media_type(file_path)
    headers: dict[str, str] = {"Accept-Ranges": "bytes"}
    if download_filename:
        safe_disp = download_filename.replace('"', "_")
        headers["Content-Disposition"] = f'attachment; filename="{safe_disp}"'

    range_header = request.headers.get("range")
    if range_header:
        parsed = _parse_range_header(range_header, file_size)
        if parsed is None:
            return JSONResponse(
                status_code=416,
                content=error_payload(
                    "Requested byte range is not satisfiable.",
                    "RANGE_NOT_SATISFIABLE",
                ),
                headers={"Content-Range": f"bytes */{file_size}"},
            )
        start, end = parsed
        length = end - start + 1
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        headers["Content-Length"] = str(length)
        return StreamingResponse(
            _iter_file_range(file_path, start, length),
            status_code=206,
            media_type=media_type,
            headers=headers,
        )

    headers["Content-Length"] = str(file_size)
    return StreamingResponse(
        _iter_file_range(file_path, 0, file_size),
        status_code=200,
        media_type=media_type,
        headers=headers,
    )


@router.get("/files")
def get_signed_file(
    request: Request,
    p: str = Query(..., description="DATA_DIR-relative path"),
    uid: int = Query(..., description="User ID encoded in signature"),
    exp: int = Query(..., description="Unix expiry timestamp"),
    sig: str = Query(..., description="HMAC-SHA256 signature"),
    download: int = Query(0, ge=0, le=1),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> Response:
    """Serve an uploaded clip or output image via an HMAC-signed URL."""
    verify_signed_file_params(p, uid, exp, sig, settings)
    data_root = settings.resolved_data_dir
    target = from_rel(p, data_root, allowed_roots=("uploads", "outputs"))
    if not target.is_file():
        raise AppError(status_code=404, code="FILE_NOT_FOUND", detail="File not found.")

    download_filename: str | None = None
    if download == 1:
        user = db.get(User, uid)
        rel_root = target.relative_to(data_root).parts[0]
        is_video = (
            rel_root == "uploads"
            or target.suffix.lower().lstrip(".") in ACCEPTED_VIDEO_EXTENSIONS
        )
        action = "download_video" if is_video else "download_frame"
        record_audit(
            db,
            action=action,
            user_id=uid,
            username=user.username if user is not None else None,
            role=user.role if user is not None else None,
            target_type="file",
            target_id=p,
            details={"filename": target.name},
            ip=get_client_ip(request),
        )
        download_filename = target.name

    return stream_file_response(request, target, download_filename=download_filename)
