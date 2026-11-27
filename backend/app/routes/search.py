"""Cross-clip face embedding similarity search endpoints."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.audit import record_audit
from backend.app.config import HUMAN_VERIFICATION_NOTICE, Settings
from backend.app.db import get_db
from backend.app.deps import get_app_settings, get_client_ip, get_current_user
from backend.app.errors import AppError
from backend.app.models import FrameRecord, Run, Search, User
from backend.app.routes.indexes import _signed_url_if_exists
from backend.app.schemas import SearchMatchOut, SearchRequest, SearchResponse
from backend.app.services.search_index import SearchIndex, load_and_normalize_embedding
from backend.app.services.storage import from_rel

router = APIRouter(tags=["search"])

SCORE_NOTE = "uncalibrated similarity, tune on sample data"
SEARCH_SCOPE = "frames from processed runs and indexed clips"


def _hydrate_matches(
    raw_matches: list[dict],
    user_id: int,
    settings: Settings,
) -> list[SearchMatchOut]:
    """Attach fresh signed crop_url and frame_url (null if missing) to matches."""
    out: list[SearchMatchOut] = []
    for item in raw_matches:
        frame_rel = item.get("frame_path_rel")
        crop_rel = item.get("crop_path_rel")
        out.append(
            SearchMatchOut(
                source=item.get("source", "run"),
                track_id=item.get("track_id"),
                short_track=bool(item.get("short_track", False)),
                clip_id=item["clip_id"],
                filename=item["filename"],
                run_id=item.get("run_id"),
                index_id=item.get("index_id"),
                frame_id=str(item["frame_id"]) if item.get("frame_id") is not None else None,
                t=float(item["t"]) if item.get("t") is not None else None,
                timestamp_sec=float(item["timestamp_sec"]),
                score=float(item["score"]),
                reliability=item["reliability"],
                flags=list(item.get("flags") or []),
                flag_scores=item.get("flag_scores"),
                crop_url=_signed_url_if_exists(crop_rel, user_id, settings),
                frame_url=_signed_url_if_exists(frame_rel, user_id, settings),
            )
        )
    return out


@router.post("/search", response_model=SearchResponse)
def search_similar_faces(
    payload: SearchRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> SearchResponse:
    """Search processed runs and indexed clips from OTHER clips."""
    run = db.get(Run, payload.run_id)
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
            detail=run.error_message or "Run failed and has no searchable frames.",
        )

    frame_id_text = str(payload.frame_id)
    frame_row = db.execute(
        select(FrameRecord).where(
            FrameRecord.run_id == run.id,
            FrameRecord.frame_id == frame_id_text,
        )
    ).scalar_one_or_none()
    if frame_row is None:
        raise AppError(
            status_code=404,
            code="FRAME_NOT_FOUND",
            detail=f"Frame '{frame_id_text}' not found in run {run.id}.",
        )

    emb_path = from_rel(
        frame_row.embedding_path_rel,
        settings.resolved_data_dir,
        allowed_roots=("outputs",),
    )
    query_vec = load_and_normalize_embedding(emb_path, settings.embed_dim)
    if query_vec is None:
        raise AppError(
            status_code=422,
            code="INVALID_EMBEDDING",
            detail="Query frame embedding is missing, corrupt, or wrong dimension.",
        )

    search_index: SearchIndex = request.app.state.search_index
    hits = search_index.search(
        query_vec,
        top_k=payload.top_k,
        exclude_clip_id=run.clip_id,
        best_per_clip=payload.best_per_clip,
        include_short_tracks=payload.include_short_tracks,
    )

    stored_results = [
        {
            "source": hit.source,
            "track_id": hit.track_id,
            "short_track": hit.short_track,
            "clip_id": hit.clip_id,
            "filename": hit.filename,
            "run_id": hit.run_id,
            "index_id": hit.index_id,
            "frame_id": hit.frame_id,
            "t": hit.t,
            "timestamp_sec": hit.timestamp_sec,
            "score": hit.score,
            "reliability": hit.reliability,
            "flags": hit.flags,
            "flag_scores": hit.flag_scores,
            "frame_path_rel": hit.frame_path_rel,
            "crop_path_rel": hit.crop_path_rel,
        }
        for hit in hits
    ]

    search_row = Search(
        run_id=run.id,
        frame_pk=frame_row.id,
        top_k=payload.top_k,
        results=stored_results,
        created_by=current_user.id,
    )
    db.add(search_row)
    db.commit()
    db.refresh(search_row)

    record_audit(
        db,
        action="search",
        user_id=current_user.id,
        username=current_user.username,
        role=current_user.role,
        target_type="search",
        target_id=str(search_row.id),
        details={
            "run_id": run.id,
            "frame_id": frame_id_text,
            "top_k": payload.top_k,
            "best_per_clip": payload.best_per_clip,
            "include_short_tracks": payload.include_short_tracks,
            "match_count": len(stored_results),
        },
        ip=get_client_ip(request),
    )

    return SearchResponse(
        search_id=search_row.id,
        run_id=run.id,
        frame_id=frame_id_text,
        top_k=payload.top_k,
        matches=_hydrate_matches(stored_results, current_user.id, settings),
        notice=HUMAN_VERIFICATION_NOTICE,
        score_note=SCORE_NOTE,
        scope=SEARCH_SCOPE,
        created_at=search_row.created_at,
    )


@router.get("/searches/{search_id}", response_model=SearchResponse)
def get_search(
    search_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> SearchResponse:
    """Retrieve a saved search result with freshly signed media URLs."""
    search_row = db.get(Search, search_id)
    if search_row is None:
        raise AppError(
            status_code=404,
            code="SEARCH_NOT_FOUND",
            detail="Search record not found.",
        )
    frame_row = db.get(FrameRecord, search_row.frame_pk)
    frame_id_text = frame_row.frame_id if frame_row is not None else ""

    return SearchResponse(
        search_id=search_row.id,
        run_id=search_row.run_id,
        frame_id=frame_id_text,
        top_k=search_row.top_k,
        matches=_hydrate_matches(search_row.results or [], current_user.id, settings),
        notice=HUMAN_VERIFICATION_NOTICE,
        score_note=SCORE_NOTE,
        scope=SEARCH_SCOPE,
        created_at=search_row.created_at,
    )
