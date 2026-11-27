"""Evidence PDF export route."""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.audit import record_audit
from backend.app.config import Settings
from backend.app.db import get_db
from backend.app.deps import get_app_settings, get_client_ip, get_current_user
from backend.app.errors import AppError
from backend.app.models import Clip, FrameRecord, Run, Search, User
from backend.app.services.evidence_pdf import build_evidence_pdf

router = APIRouter(tags=["evidence"])


@router.get("/runs/{run_id}/evidence.pdf")
def download_evidence_pdf(
    run_id: int,
    request: Request,
    search_id: int | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> Response:
    """Render and return the ReportLab evidence PDF, logging its SHA-256."""
    run = db.get(Run, run_id)
    if run is None:
        raise AppError(status_code=404, code="RUN_NOT_FOUND", detail="Run not found.")
    if run.status in {"queued", "running"}:
        raise AppError(
            status_code=409,
            code="RUN_NOT_DONE",
            detail=f"Run {run.id} is still '{run.status}'.",
        )
    if run.status == "failed":
        raise AppError(
            status_code=422,
            code=run.error_code or "PIPELINE_FAILED",
            detail=run.error_message or "Failed run cannot generate an evidence sheet.",
        )

    clip = db.get(Clip, run.clip_id)
    if clip is None:
        raise AppError(status_code=404, code="CLIP_NOT_FOUND", detail="Clip not found.")

    search_row: Search | None = None
    if search_id is not None:
        search_row = db.get(Search, search_id)
        if search_row is None or search_row.run_id != run.id:
            raise AppError(
                status_code=404,
                code="SEARCH_NOT_FOUND",
                detail=f"Search {search_id} not found for run {run.id}.",
            )

    frames = (
        db.execute(
            select(FrameRecord)
            .where(FrameRecord.run_id == run.id)
            .order_by(FrameRecord.id.asc())
        )
        .scalars()
        .all()
    )

    pdf_bytes, pdf_sha256, frame_count = build_evidence_pdf(
        run=run,
        clip=clip,
        frames=frames,
        investigator=current_user,
        settings=settings,
        search=search_row,
    )

    record_audit(
        db,
        action="download_evidence",
        user_id=current_user.id,
        username=current_user.username,
        role=current_user.role,
        target_type="run",
        target_id=str(run.id),
        details={
            "pdf_sha256": pdf_sha256,
            "search_id": search_id,
            "frame_count": frame_count,
        },
        ip=get_client_ip(request),
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="evidence_EV-{run.id}.pdf"'
        },
    )
