"""Frame selection endpoint (Phase 6; enhancement added in Phase 7)."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.audit import record_audit
from backend.app.db import get_db
from backend.app.deps import get_client_ip, get_current_user
from backend.app.errors import AppError
from backend.app.models import FrameRecord, Run, User
from backend.app.schemas import SelectionRequest, SelectionResponse

router = APIRouter(tags=["frames"])


@router.post("/runs/{run_id}/selection", response_model=SelectionResponse)
def replace_run_selection(
    run_id: int,
    payload: SelectionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SelectionResponse:
    """Replace the selected frame set for a completed run."""
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
            detail=run.error_message or "Failed run cannot have frames selected.",
        )

    rows = (
        db.execute(
            select(FrameRecord)
            .where(FrameRecord.run_id == run_id)
            .order_by(FrameRecord.id.asc())
        )
        .scalars()
        .all()
    )
    by_frame_id = {row.frame_id: row for row in rows}

    deduped_ids: list[str] = []
    seen: set[str] = set()
    for raw_id in payload.frame_ids:
        fid = str(raw_id)
        if fid not in seen:
            seen.add(fid)
            deduped_ids.append(fid)

    missing = [fid for fid in deduped_ids if fid not in by_frame_id]
    if missing:
        raise AppError(
            status_code=422,
            code="INVALID_FRAME_SELECTION",
            detail=f"Frame id(s) not found in run {run_id}: {', '.join(missing)}.",
        )

    for row in rows:
        row.selected = row.frame_id in seen
    db.commit()

    selected_ids = [row.frame_id for row in rows if row.selected]
    record_audit(
        db,
        action="frames_selected",
        user_id=current_user.id,
        username=current_user.username,
        role=current_user.role,
        target_type="run",
        target_id=str(run.id),
        details={"frame_ids": selected_ids, "count": len(selected_ids)},
        ip=get_client_ip(request),
    )
    return SelectionResponse(run_id=run.id, selected_frame_ids=selected_ids)
