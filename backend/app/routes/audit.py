"""Admin-only append-only audit log query, CSV export, and hash verification."""

import csv
import io
import json

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.audit import record_audit, verify_audit_chain
from backend.app.db import get_db
from backend.app.deps import get_client_ip, require_admin
from backend.app.models import AuditLog, User
from backend.app.schemas import AuditEntryOut, AuditListResponse, AuditVerifyResponse

router = APIRouter(prefix="/audit", tags=["audit"])


def _apply_audit_filters(stmt, action: str | None, username: str | None):
    """Apply optional exact filters for action and username."""
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if username:
        stmt = stmt.where(AuditLog.username == username)
    return stmt


@router.get("", response_model=AuditListResponse)
def list_audit_entries(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    action: str | None = Query(None),
    username: str | None = Query(None),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AuditListResponse:
    """List audit log entries newest-first with optional filters (admin only)."""
    count_stmt = _apply_audit_filters(select(func.count(AuditLog.id)), action, username)
    total = int(db.execute(count_stmt).scalar_one())

    rows_stmt = (
        _apply_audit_filters(select(AuditLog), action, username)
        .order_by(AuditLog.id.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = db.execute(rows_stmt).scalars().all()
    return AuditListResponse(
        items=[AuditEntryOut.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/export.csv")
def export_audit_csv(
    request: Request,
    action: str | None = Query(None),
    username: str | None = Query(None),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    """Export audit log entries as CSV and record an audit_export event (admin only)."""
    record_audit(
        db,
        action="audit_export",
        user_id=admin.id,
        username=admin.username,
        role=admin.role,
        target_type="audit_log",
        target_id=None,
        details={"action_filter": action, "username_filter": username},
        ip=get_client_ip(request),
    )

    rows_stmt = _apply_audit_filters(select(AuditLog), action, username).order_by(
        AuditLog.id.asc()
    )
    rows = db.execute(rows_stmt).scalars().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "id",
            "ts_utc",
            "user_id",
            "username",
            "role",
            "action",
            "target_type",
            "target_id",
            "details",
            "ip",
            "prev_hash",
            "entry_hash",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row.id,
                row.ts_utc,
                row.user_id if row.user_id is not None else "",
                row.username or "",
                row.role or "",
                row.action,
                row.target_type or "",
                row.target_id or "",
                json.dumps(row.details, sort_keys=True, ensure_ascii=False),
                row.ip or "",
                row.prev_hash,
                row.entry_hash,
            ]
        )

    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="audit_log.csv"'},
    )


@router.get("/verify", response_model=AuditVerifyResponse)
def verify_audit_log(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AuditVerifyResponse:
    """Recompute the audit_log SHA-256 hash chain and detect tampering (admin only)."""
    ok, checked_count, first_bad_id, reason = verify_audit_chain(db)
    return AuditVerifyResponse(
        ok=ok,
        checked_count=checked_count,
        first_bad_id=first_bad_id,
        reason=reason,
    )
