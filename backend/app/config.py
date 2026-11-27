"""Application configuration loaded from the repo-root .env file."""

import json
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = REPO_ROOT / ".env"

HUMAN_VERIFICATION_NOTICE = (
    "Possible matches only. A human investigator must verify every result."
)
FAKE_BANNER_TEXT = "FAKE PIPELINE, DEMO DATA"
ACCEPTED_VIDEO_EXTENSIONS = (
    "mp4",
    "avi",
    "mov",
    "mkv",
    "wmv",
    "flv",
    "mpeg",
    "mpg",
)
DEFAULT_MODEL_LABELS = (
    "Person detector: torchvision Faster R-CNN MobileNetV3-Large 320 FPN (COCO)",
    "Tracker: IoU / ByteTrack",
    "Faces: InsightFace buffalo_l (SCRFD + ArcFace)",
)


class Settings(BaseSettings):
    """Typed backend settings validated at startup."""

    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    use_fake_pipeline: bool = Field(default=True, alias="USE_FAKE_PIPELINE")
    auto_index_on_upload: bool = Field(default=True, alias="AUTO_INDEX_ON_UPLOAD")
    data_dir: Path = Field(default=Path("./data"), alias="DATA_DIR")
    jwt_secret: str = Field(..., alias="JWT_SECRET")
    jwt_expire_min: int = Field(default=480, ge=1, alias="JWT_EXPIRE_MIN")
    cors_origins: str = Field(
        default="http://localhost:5173,http://localhost:3000",
        alias="CORS_ORIGINS",
    )
    max_upload_mb: int = Field(default=500, ge=1, alias="MAX_UPLOAD_MB")
    signed_url_ttl_sec: int = Field(default=900, ge=1, alias="SIGNED_URL_TTL_SEC")
    display_tz: str = Field(default="Asia/Kolkata", alias="DISPLAY_TZ")
    embed_dim: int = Field(default=512, ge=1, alias="EMBED_DIM")
    model_labels: str = Field(
        default="|".join(DEFAULT_MODEL_LABELS),
        alias="MODEL_LABELS",
    )

    @field_validator("jwt_secret")
    @classmethod
    def validate_jwt_secret(cls, value: str) -> str:
        """Refuse missing, blank, or short JWT secrets."""
        cleaned = value.strip()
        if len(cleaned) < 32:
            raise ValueError(
                "JWT_SECRET is required and must be at least 32 characters long."
            )
        return cleaned

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, value: str) -> str:
        """Reject wildcard CORS origins and require at least one origin."""
        origins = [item.strip() for item in value.split(",") if item.strip()]
        if not origins:
            raise ValueError("CORS_ORIGINS must contain at least one origin.")
        if "*" in origins:
            raise ValueError("CORS_ORIGINS must never contain '*'.")
        return ",".join(origins)

    @property
    def pipeline_mode(self) -> str:
        """Return 'fake' or 'real' matching USE_FAKE_PIPELINE."""
        return "fake" if self.use_fake_pipeline else "real"

    @property
    def cors_origins_list(self) -> list[str]:
        """Return parsed CORS origins as a list."""
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def model_labels_list(self) -> list[str]:
        """Return configured model labels parsed from JSON array or '|'-delimited string."""
        raw = self.model_labels.strip()
        if raw.startswith("["):
            parsed = json.loads(raw)
            return [str(item) for item in parsed]
        return [item.strip() for item in raw.split("|") if item.strip()]

    @property
    def resolved_data_dir(self) -> Path:
        """Return absolute path to DATA_DIR, resolving relative paths from REPO_ROOT."""
        if self.data_dir.is_absolute():
            return self.data_dir.resolve()
        return (REPO_ROOT / self.data_dir).resolve()

    @property
    def db_path(self) -> Path:
        """Return path to the SQLite database file inside DATA_DIR."""
        return self.resolved_data_dir / "strix.db"


def get_settings() -> Settings:
    """Load and validate application settings."""
    return Settings(_env_file=DEFAULT_ENV_FILE)
