"""SQLAlchemy 2.0 ORM models for Strix."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db import Base


def utc_now_naive() -> datetime:
    """Return current UTC datetime without tzinfo for consistent SQLite storage."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    """Application user with role-based access control."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    full_name: Mapped[str] = mapped_column(String(128), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive
    )


class AuditLog(Base):
    """Append-only tamper-evident audit log with hash chaining."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts_utc: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class Clip(Base):
    """Uploaded CCTV clip metadata (stored file path is relative to DATA_DIR)."""

    __tablename__ = "clips"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_sec: Mapped[float] = mapped_column(Float, nullable=False)
    fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    codec: Mapped[str | None] = mapped_column(String(64), nullable=True)
    container: Mapped[str | None] = mapped_column(String(128), nullable=True)
    rotation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    clip_start_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    clip_start_source: Mapped[str] = mapped_column(String(32), nullable=False)
    atm_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    zone_polygon_norm: Mapped[list[list[float]] | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive
    )


class Run(Base):
    """Background pipeline execution job for a clip and transaction window."""

    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clip_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clips.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    progress: Mapped[float | None] = mapped_column(Float, nullable=True)
    progress_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_advice: Mapped[str | None] = mapped_column(Text, nullable=True)
    transaction_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    tx_offset_sec: Mapped[float] = mapped_column(Float, nullable=False)
    window_sec: Mapped[float] = mapped_column(Float, nullable=False)
    sample_fps: Mapped[float] = mapped_column(Float, nullable=False)
    tracker: Mapped[str] = mapped_column(String(32), nullable=False)
    atm_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pipeline_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    served_from_demo_pack: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    link_low_margin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class FrameRecord(Base):
    """Per-frame evidence row generated by a pipeline run."""

    __tablename__ = "frames"
    __table_args__ = (
        UniqueConstraint("run_id", "frame_id", name="uq_frames_run_frame"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("runs.id"), nullable=False, index=True
    )
    frame_id: Mapped[str] = mapped_column(String(128), nullable=False)
    timestamp_sec: Mapped[float] = mapped_column(Float, nullable=False)
    quality_score: Mapped[float] = mapped_column(Float, nullable=False)
    reliability: Mapped[str] = mapped_column(String(16), nullable=False)
    flags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    flag_scores: Mapped[dict[str, float] | None] = mapped_column(JSON, nullable=True)
    face_box: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    match_ready: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    rank_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    frame_path_rel: Mapped[str | None] = mapped_column(String(512), nullable=True)
    crop_path_rel: Mapped[str | None] = mapped_column(String(512), nullable=True)
    embedding_path_rel: Mapped[str | None] = mapped_column(String(512), nullable=True)
    enhanced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enhancement: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ClipIndex(Base):
    """Background search-index job over a clip time range."""

    __tablename__ = "clip_indexes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clip_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clips.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    progress: Mapped[float | None] = mapped_column(Float, nullable=True)
    progress_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_advice: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_sec: Mapped[float] = mapped_column(Float, nullable=False)
    end_sec: Mapped[float] = mapped_column(Float, nullable=False)
    sample_fps: Mapped[float] = mapped_column(Float, nullable=False)
    tracker: Mapped[str] = mapped_column(String(32), nullable=False)
    faces_per_track: Mapped[int] = mapped_column(Integer, nullable=False)
    atm_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    npz_rel: Mapped[str | None] = mapped_column(String(512), nullable=True)
    json_rel: Mapped[str | None] = mapped_column(String(512), nullable=True)
    total_embeddings: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timings_ms: Mapped[dict[str, float] | None] = mapped_column(JSON, nullable=True)
    pipeline_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    served_from_demo_pack: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class IndexTrackRecord(Base):
    """Per-track summary row produced by a clip_indexes job."""

    __tablename__ = "index_tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    index_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("clip_indexes.id"), nullable=False, index=True
    )
    track_id: Mapped[int] = mapped_column(Integer, nullable=False)
    first_t: Mapped[float] = mapped_column(Float, nullable=False)
    last_t: Mapped[float] = mapped_column(Float, nullable=False)
    n_observations: Mapped[int] = mapped_column(Integer, nullable=False)
    short_track: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dwell_sec_in_zone: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    face_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class IndexFaceRecord(Base):
    """Indexed face observation belonging to a tracked person in clip_indexes."""

    __tablename__ = "index_faces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    index_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("clip_indexes.id"), nullable=False, index=True
    )
    track_id: Mapped[int] = mapped_column(Integer, nullable=False)
    t: Mapped[float] = mapped_column(Float, nullable=False)
    quality_score: Mapped[float] = mapped_column(Float, nullable=False)
    reliability: Mapped[str] = mapped_column(String(16), nullable=False)
    match_ready: Mapped[bool] = mapped_column(Boolean, nullable=False)
    flags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    flag_scores: Mapped[dict[str, float] | None] = mapped_column(JSON, nullable=True)
    face_box: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    crop_rel: Mapped[str | None] = mapped_column(String(512), nullable=True)
    frame_rel: Mapped[str | None] = mapped_column(String(512), nullable=True)
    embedding_rel: Mapped[str | None] = mapped_column(String(512), nullable=True)
    short_track: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Search(Base):
    """Persisted similarity search query and raw match results."""

    __tablename__ = "searches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("runs.id"), nullable=False, index=True
    )
    frame_pk: Mapped[int] = mapped_column(
        Integer, ForeignKey("frames.id"), nullable=False, index=True
    )
    top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive
    )
