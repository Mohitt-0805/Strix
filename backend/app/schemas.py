"""Pydantic v2 request and response schemas."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LoginRequest(BaseModel):
    """Credentials payload for POST /auth/login."""

    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=72)


class UserOut(BaseModel):
    """Public user representation (never includes password_hash)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: Literal["admin", "investigator"]
    full_name: str
    active: bool
    created_at: datetime


class LoginResponse(BaseModel):
    """JWT access token and authenticated user summary."""

    access_token: str
    token_type: str = "bearer"
    user: UserOut


class UserCreateRequest(BaseModel):
    """Admin payload for creating a new user."""

    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=8, max_length=72)
    role: Literal["admin", "investigator"]
    full_name: str = Field(..., min_length=1, max_length=128)

    @field_validator("username", "full_name")
    @classmethod
    def strip_non_empty(cls, value: str) -> str:
        """Trim surrounding whitespace and reject blank strings."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Field must not be blank.")
        return cleaned


class AuditEntryOut(BaseModel):
    """Single append-only audit log entry."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    ts_utc: str
    user_id: int | None
    username: str | None
    role: str | None
    action: str
    target_type: str | None
    target_id: str | None
    details: dict[str, Any]
    ip: str | None
    prev_hash: str
    entry_hash: str


class AuditListResponse(BaseModel):
    """Paginated audit log response."""

    items: list[AuditEntryOut]
    total: int
    limit: int
    offset: int


class AuditVerifyResponse(BaseModel):
    """Result of recomputing the audit_log hash chain."""

    ok: bool
    checked_count: int
    first_bad_id: int | None = None
    reason: str | None = None
