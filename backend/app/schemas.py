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


class ClipOut(BaseModel):
    """Clip metadata plus a ready-made signed video URL."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    original_filename: str
    stored_path: str
    sha256: str
    size_bytes: int
    duration_sec: float
    fps: float | None
    width: int
    height: int
    codec: str | None
    container: str | None
    rotation: int
    clip_start_time: datetime | None
    clip_start_source: Literal["ffprobe_converted", "user", "unknown"]
    atm_id: str | None
    zone_polygon_norm: list[list[float]] | None
    notes: str | None
    uploaded_by: int
    created_at: datetime
    video_url: str


class ClipPatchRequest(BaseModel):
    """Editable clip metadata fields for PATCH /clips/{id}."""

    clip_start_time: datetime | None = None
    atm_id: str | None = Field(default=None, max_length=64)
    zone_polygon_norm: list[list[float]] | None = None
    notes: str | None = None

    @field_validator("zone_polygon_norm")
    @classmethod
    def validate_polygon(cls, value: list[list[float]] | None) -> list[list[float]] | None:
        """Require at least 3 [x, y] points normalized within [0, 1]."""
        if value is None:
            return None
        if len(value) < 3:
            raise ValueError("zone_polygon_norm must have at least 3 points.")
        for point in value:
            if len(point) != 2:
                raise ValueError("Each polygon point must be [x, y].")
            x, y = point
            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                raise ValueError("Polygon coordinates must be between 0 and 1.")
        return value


class ProcessClipRequest(BaseModel):
    """Request body for POST /clips/{id}/process."""

    transaction_time: datetime
    window_sec: float = Field(default=10.0, ge=1.0, le=100.0)
    sample_fps: float = Field(default=2.0, ge=0.5, le=5.0)
    tracker: Literal["iou", "bytetrack"] = "iou"
    atm_id: str | None = Field(default=None, max_length=64)


class RunAcceptedResponse(BaseModel):
    """202 Accepted response when a run is queued."""

    run_id: int
    status: Literal["queued", "running", "done", "failed"]


class FrameOut(BaseModel):
    """Candidate evidence frame hydrated with signed URLs."""

    frame_id: str
    frame_path: str
    crop_path: str | None = None
    embedding_path: str
    timestamp_sec: float
    quality_score: float
    reliability: Literal["High", "Medium", "Low"]
    flags: list[str]
    enhanced: bool
    enhancement: dict[str, Any] | None = None
    metrics: dict[str, Any]
    match_ready: bool | None = None
    rank_reason: str | None = None
    selected: bool = False
    image_url: str
    crop_url: str | None = None
    enhanced_url: str | None = None


class RunResultOut(BaseModel):
    """Full hydrated run result with signed media URLs and verification notice."""

    run_id: int
    clip_id: str
    pipeline_mode: Literal["fake", "real"]
    banner: str | None = None
    notice: str
    video_url: str
    transaction_time: str
    person_track_id: int | None = None
    best_frames: list[FrameOut]
    link_confidence: str | None = None
    link_reason: str | None = None
    selection_reason: str | None = None
    show_selection_reason: bool = False
    timings_ms: dict[str, float] | None = None


class RunStatusOut(BaseModel):
    """Run status and metadata (includes hydrated result when done)."""

    run_id: int
    clip_id: str
    status: Literal["queued", "running", "done", "failed"]
    stage: str | None = None
    progress: float | None = None
    error_code: str | None = None
    error_message: str | None = None
    transaction_time: datetime
    tx_offset_sec: float
    window_sec: float
    sample_fps: float
    tracker: str
    atm_id: str | None = None
    pipeline_mode: Literal["fake", "real"]
    created_by: int
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: RunResultOut | None = None
