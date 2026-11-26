"""Shared Pydantic v2 output contract for the Strix pipeline."""

from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field


class Metrics(BaseModel):
    """Per-frame face quality metrics."""

    sharpness: float
    face_size: float
    pose_yaw: float
    illumination: float
    occlusion: float


class Enhancement(BaseModel):
    """Metadata for a non-destructive enhanced face crop."""

    enhanced_path: str
    method: str
    scale: int = Field(ge=1)
    model_version: str
    crop_box: list[int] = Field(min_length=4, max_length=4)
    search_embedding_source: str


class Frame(BaseModel):
    """Single candidate evidence frame for a tracked person."""

    frame_id: int
    frame_path: str
    timestamp_sec: float
    quality_score: float = Field(ge=0.0, le=1.0)
    reliability: Literal["High", "Medium", "Low"]
    flags: list[str]
    enhanced: bool
    enhancement: Optional[Enhancement] = None
    metrics: Metrics
    embedding_path: str


class PipelineResult(BaseModel):
    """Top-level pipeline output contract matching docs/sample_result.json."""

    clip_id: str
    transaction_time: str
    person_track_id: int
    best_frames: list[Frame]


def load_result(path: str | Path) -> PipelineResult:
    """Load and validate a PipelineResult JSON file from disk."""
    raw_json = Path(path).read_text(encoding="utf-8")
    return PipelineResult.model_validate_json(raw_json)
