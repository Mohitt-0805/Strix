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
    # Validated explicitly in PATCH /clips/{id} so invalid polygons return 422 ZONE_INVALID.
    zone_polygon_norm: Any = None
    notes: str | None = None


class ZoneOut(BaseModel):
    """Preconfigured ATM zone entry from pipeline/config/atm_zone.json."""

    id: str
    note: str
    polygon: list[list[float]]


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
    flag_scores: dict[str, float] | None = None
    face_box: list[int] | None = None
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
    link_low_margin: bool = False
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
    progress_message: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    error_advice: str | None = None
    transaction_time: datetime
    tx_offset_sec: float
    window_sec: float
    sample_fps: float
    tracker: str
    atm_id: str | None = None
    pipeline_mode: Literal["fake", "real"]
    link_low_margin: bool = False
    created_by: int
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: RunResultOut | None = None


class SearchRequest(BaseModel):
    """Request body for POST /search."""

    run_id: int
    frame_id: str | int
    top_k: int = Field(default=10, ge=1, le=100)
    best_per_clip: bool = True
    include_short_tracks: bool = False


class SearchMatchOut(BaseModel):
    """Single cross-clip similarity match from a processed run or indexed clip."""

    source: Literal["run", "index"]
    track_id: int | None = None
    short_track: bool = False
    clip_id: str
    filename: str
    run_id: int | None = None
    index_id: int | None = None
    frame_id: str | None = None
    t: float | None = None
    timestamp_sec: float
    score: float
    reliability: Literal["High", "Medium", "Low"]
    flags: list[str]
    flag_scores: dict[str, float] | None = None
    crop_url: str | None = None
    frame_url: str | None = None


class SearchResponse(BaseModel):
    """Search response with mandatory verification notice and uncalibrated score note."""

    search_id: int
    run_id: int
    frame_id: str
    top_k: int
    matches: list[SearchMatchOut]
    notice: str
    score_note: str
    scope: str
    created_at: datetime


class IndexClipRequest(BaseModel):
    """Optional request body for POST /clips/{id}/index."""

    start_sec: float = Field(default=0.0, ge=0.0)
    end_sec: float | None = None
    sample_fps: float = Field(default=1.0, gt=0.0, le=5.0)
    tracker: Literal["iou", "bytetrack"] = "iou"
    faces_per_track: int = Field(default=3, ge=1, le=20)
    atm_id: str | None = Field(default=None, max_length=64)


class IndexAcceptedResponse(BaseModel):
    """202 Accepted response when an index job is queued."""

    index_id: int
    status: Literal["queued", "running", "done", "failed"] = "queued"


class IndexFaceOut(BaseModel):
    """Indexed face row hydrated with signed URLs (null if file missing)."""

    id: int
    track_id: int
    t: float
    quality_score: float
    reliability: Literal["High", "Medium", "Low"]
    match_ready: bool
    flags: list[str]
    flag_scores: dict[str, float] | None = None
    face_box: list[float] | None = None
    short_track: bool
    crop_url: str | None = None
    frame_url: str | None = None


class IndexTrackOut(BaseModel):
    """Tracked person summary in an indexed clip."""

    track_id: int
    first_t: float
    last_t: float
    n_observations: int
    short_track: bool
    confidence_note: str | None = None
    dwell_sec_in_zone: float | None = None
    reason: str | None = None
    face_count: int
    faces: list[IndexFaceOut]


class IndexStatusOut(BaseModel):
    """Summary/status for a clip_indexes job."""

    index_id: int
    clip_id: str
    status: Literal["queued", "running", "done", "failed"]
    stage: str | None = None
    progress: float | None = None
    progress_message: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    error_advice: str | None = None
    start_sec: float
    end_sec: float
    sample_fps: float
    tracker: str
    faces_per_track: int
    atm_id: str | None = None
    total_embeddings: int | None = None
    timings_ms: dict[str, float] | None = None
    pipeline_mode: Literal["fake", "real"]
    created_by: int
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class IndexDetailOut(IndexStatusOut):
    """Full index status plus tracks and hydrated faces."""

    tracks: list[IndexTrackOut] = Field(default_factory=list)


class SelectionRequest(BaseModel):
    """Request body for POST /runs/{run_id}/selection."""

    frame_ids: list[str | int]


class SelectionResponse(BaseModel):
    """Updated frame selection for a run."""

    run_id: int
    selected_frame_ids: list[str]
