"""Frame selection endpoint (Phase 6; enhancement added in Phase 7)."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.audit import record_audit
from backend.app.config import Settings
from backend.app.db import get_db
from backend.app.deps import get_app_settings, get_client_ip, get_current_user
from backend.app.errors import AppError
from backend.app.models import FrameRecord, Run, User
from backend.app.schemas import (
    EnhanceRequest,
    EnhanceResponse,
    SelectionRequest,
    SelectionResponse,
)
from backend.app.services.enhance import enhance_frame_crop
from backend.app.signing import make_signed_file_url

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


@router.post("/runs/{run_id}/frames/{frame_id}/enhance", response_model=EnhanceResponse)
def enhance_run_frame(
    run_id: int,
    frame_id: str,
    payload: EnhanceRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> EnhanceResponse:
    """Non-destructively crop and upscale a full-frame evidence image."""
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
            detail=run.error_message or "Failed run cannot enhance frames.",
        )

    frame_row = db.execute(
        select(FrameRecord).where(
            FrameRecord.run_id == run_id,
            FrameRecord.frame_id == str(frame_id),
        )
    ).scalar_one_or_none()
    if frame_row is None:
        raise AppError(
            status_code=404,
            code="FRAME_NOT_FOUND",
            detail=f"Frame '{frame_id}' not found in run {run_id}.",
        )

    enh_dict, cached = enhance_frame_crop(
        frame_rel_path=frame_row.frame_path_rel,
        crop_box=payload.crop_box,
        scale=payload.scale,
        method=payload.method,
        settings=settings,
    )

    frame_row.enhancement = enh_dict
    frame_row.enhanced = True

    if isinstance(run.result_json, dict) and isinstance(run.result_json.get("best_frames"), list):
        updated_res = dict(run.result_json)
        updated_frames = []
        for fr in updated_res["best_frames"]:
            if str(fr.get("frame_id")) == frame_row.frame_id:
                fr = {**fr, "enhanced": True, "enhancement": enh_dict}
            updated_frames.append(fr)
        updated_res["best_frames"] = updated_frames
        run.result_json = updated_res

    db.commit()

    record_audit(
        db,
        action="frame_enhanced",
        user_id=current_user.id,
        username=current_user.username,
        role=current_user.role,
        target_type="frame",
        target_id=f"{run.id}:{frame_row.frame_id}",
        details={
            "run_id": run.id,
            "frame_id": frame_row.frame_id,
            "crop_box": enh_dict["crop_box"],
            "method": enh_dict["method"],
            "scale": enh_dict["scale"],
            "model_version": enh_dict["model_version"],
            "cached": cached,
        },
        ip=get_client_ip(request),
    )

    return EnhanceResponse(
        run_id=run.id,
        frame_id=frame_row.frame_id,
        original_url=make_signed_file_url(
            frame_row.frame_path_rel, current_user.id, settings
        ),
        enhanced_url=make_signed_file_url(
            enh_dict["enhanced_path"], current_user.id, settings
        ),
        method=enh_dict["method"],
        scale=int(enh_dict["scale"]),
        model_version=enh_dict["model_version"],
        crop_box=[int(v) for v in enh_dict["crop_box"]],
        face_box=[int(v) for v in frame_row.face_box] if frame_row.face_box is not None else None,
        search_embedding_source=enh_dict["search_embedding_source"],
        cached=cached,
    )
