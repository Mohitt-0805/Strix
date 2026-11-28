"""Shared Pydantic v2 output contract for the Strix pipeline."""

from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field


RELIABILITY_VALUES: tuple[str, ...] = ("High", "Medium", "Low")

FLAG_VOCAB: dict[str, tuple[str, ...]] = {
    "current": (
        "low light",
        "blur",
        "partial face",
        "small face",
        "profile view",
        "looking down",
        "overlapping person",
        "cap",
        "mask",
        "helmet",
    ),
    "planned": (),
}


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

    frame_id: int | str
    frame_path: str
    timestamp_sec: float
    quality_score: float = Field(ge=0.0, le=1.0)
    reliability: Literal["High", "Medium", "Low"]
    flags: list[str]
    enhanced: bool
    enhancement: Optional[Enhancement] = None
    metrics: Metrics
    embedding_path: str
    # Proposed additions (optional with defaults for backward compatibility).
    match_ready: Optional[bool] = None
    rank_reason: Optional[str] = None
    crop_path: Optional[str] = None
    face_box: Optional[list[int]] = None
    flag_scores: Optional[dict[str, float]] = None


class PipelineResult(BaseModel):
    """Top-level pipeline output contract matching docs/sample_result.json."""

    clip_id: str
    transaction_time: str
    person_track_id: Optional[int] = None
    best_frames: list[Frame]
    # Proposed additions (optional with defaults for backward compatibility).
    link_confidence: Optional[str] = None
    link_reason: Optional[str] = None
    link_low_margin: Optional[bool] = False
    selection_reason: Optional[str] = None
    timings_ms: Optional[dict[str, float]] = None
    served_from_demo_pack: Optional[bool] = False


class IndexFace(BaseModel):
    """Single indexed face observation for a tracked person."""

    t: float
    quality_score: float = Field(ge=0.0, le=1.0)
    reliability: Literal["High", "Medium", "Low"]
    match_ready: bool
    flags: list[str]
    face_box: list[float]
    crop_path: str
    frame_path: str
    embedding_path: str
    flag_scores: Optional[dict[str, float]] = None


class IndexTrack(BaseModel):
    """Single tracked person in an indexed clip range."""

    track_id: int
    first_t: float
    last_t: float
    n_observations: int = 0
    short_track: bool = False
    dwell_sec_in_zone: Optional[float] = None
    faces: list[IndexFace] = Field(default_factory=list)
    reason: Optional[str] = None


class IndexResult(BaseModel):
    """Top-level output for index_clip() search indexing."""

    clip_id: str
    start_sec: float
    end_sec: float
    tracks: list[IndexTrack] = Field(default_factory=list)
    index_npz_path: str
    index_json_path: str
    total_embeddings: int = 0
    timings_ms: Optional[dict[str, float]] = None
    served_from_demo_pack: Optional[bool] = False


class SearchMatch(BaseModel):
    """Single ranked lead from search_with_enhancement()."""

    track_id: int
    t: float
    similarity: float
    similarity_secondary: Optional[float] = None
    delta: Optional[float] = None
    warning: Optional[str] = None
    crop_path: str = ""
    reliability: Optional[str] = None
    match_ready: Optional[bool] = None


class SearchResult(BaseModel):
    """Top-level result from search_with_enhancement()."""

    basis: Literal["original", "enhanced", "none"] = "original"
    banner: str = "Possible leads only. A person must verify."
    reliability_note: Optional[str] = None
    top_level_warning: Optional[str] = None
    reason: Optional[str] = None
    matches: list[SearchMatch] = Field(default_factory=list)
    served_from_demo_pack: Optional[bool] = False


def load_result(path: str | Path) -> PipelineResult:
    """Load and validate a PipelineResult JSON file from disk."""
    raw_json = Path(path).read_text(encoding="utf-8")
    return PipelineResult.model_validate_json(raw_json)
