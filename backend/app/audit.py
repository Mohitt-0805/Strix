"""Append-only tamper-evident audit logging and hash-chain verification."""

import hashlib
import json
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import AuditLog

GENESIS_HASH = "0" * 64
_SENSITIVE_KEYS = frozenset({"password", "password_hash", "token", "access_token", "secret"})
_AUDIT_WRITE_LOCK = Lock()


def _sanitize_details(details: dict[str, Any] | None) -> dict[str, Any]:
    """Ensure details is a JSON-serializable dict with no secret fields."""
    if not details:
        return {}
    return {
        str(k): v
        for k, v in details.items()
        if str(k).lower() not in _SENSITIVE_KEYS
    }


def canonical_audit_json(
    *,
    entry_id: int,
    ts_utc: str,
    user_id: int | None,
    username: str | None,
    role: str | None,
    action: str,
    target_type: str | None,
    target_id: str | None,
    details: dict[str, Any] | None,
    ip: str | None,
    prev_hash: str,
) -> str:
    """Serialize an audit row without entry_hash into deterministic canonical JSON."""
    payload = {
        "id": entry_id,
        "ts_utc": ts_utc,
        "user_id": user_id,
        "username": username,
        "role": role,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "details": details if details is not None else {},
        "ip": ip,
        "prev_hash": prev_hash,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_entry_hash(prev_hash: str, canonical_json: str) -> str:
    """Compute SHA-256(prev_hash + canonical_json)."""
    return hashlib.sha256((prev_hash + canonical_json).encode("utf-8")).hexdigest()


def record_audit(
    db: Session,
    *,
    action: str,
    user_id: int | None = None,
    username: str | None = None,
    role: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    details: dict[str, Any] | None = None,
    ip: str | None = None,
) -> AuditLog:
    """Append a hash-chained audit_log entry inside a serialized write lock."""
    clean_details = _sanitize_details(details)
    ts_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    with _AUDIT_WRITE_LOCK:
        last_row = db.execute(
            select(AuditLog).order_by(AuditLog.id.desc()).limit(1)
        ).scalar_one_or_none()
        next_id = (last_row.id + 1) if last_row is not None else 1
        prev_hash = last_row.entry_hash if last_row is not None else GENESIS_HASH

        canonical = canonical_audit_json(
            entry_id=next_id,
            ts_utc=ts_utc,
            user_id=user_id,
            username=username,
            role=role,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=clean_details,
            ip=ip,
            prev_hash=prev_hash,
        )
        entry_hash = compute_entry_hash(prev_hash, canonical)

        entry = AuditLog(
            id=next_id,
            ts_utc=ts_utc,
            user_id=user_id,
            username=username,
            role=role,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=clean_details,
            ip=ip,
            prev_hash=prev_hash,
            entry_hash=entry_hash,
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return entry


def verify_audit_chain(db: Session) -> tuple[bool, int, int | None, str | None]:
    """Recompute the entire audit_log hash chain and return (ok, count, first_bad_id, reason)."""
    rows = db.execute(select(AuditLog).order_by(AuditLog.id.asc())).scalars().all()
    expected_prev = GENESIS_HASH

    for index, row in enumerate(rows):
        if row.prev_hash != expected_prev:
            return (
                False,
                index + 1,
                row.id,
                f"prev_hash mismatch at audit id {row.id}",
            )
        canonical = canonical_audit_json(
            entry_id=row.id,
            ts_utc=row.ts_utc,
            user_id=row.user_id,
            username=row.username,
            role=row.role,
            action=row.action,
            target_type=row.target_type,
            target_id=row.target_id,
            details=row.details,
            ip=row.ip,
            prev_hash=row.prev_hash,
        )
        expected_hash = compute_entry_hash(row.prev_hash, canonical)
        if row.entry_hash != expected_hash:
            return (
                False,
                index + 1,
                row.id,
                f"entry_hash mismatch at audit id {row.id}",
            )
        expected_prev = row.entry_hash

    return True, len(rows), None, None
