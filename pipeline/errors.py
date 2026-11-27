"""Typed exceptions for the Strix pipeline (no heavy imports)."""


class PipelineError(Exception):
    """Base exception for Strix pipeline failures."""

    code: str = "PIPELINE_ERROR"

    def __init__(self, message: str, code: str | None = None) -> None:
        if code is not None:
            self.code = code
        self.message = message
        super().__init__(message)


class VideoNotFoundError(PipelineError):
    """Raised when the input video file does not exist."""

    code = "VIDEO_NOT_FOUND"


class VideoUnreadableError(PipelineError):
    """Raised when ffprobe/OpenCV cannot read the video or find a video stream."""

    code = "VIDEO_UNREADABLE"


class InvalidArgumentError(PipelineError):
    """Raised when caller arguments (tx, window, fps, zone polygon) are invalid."""

    code = "INVALID_ARGUMENT"


class ZoneNotFoundError(PipelineError):
    """Raised when a requested atm_id is not present in atm_zone.json."""

    code = "ZONE_NOT_FOUND"


class ModelLoadError(PipelineError):
    """Raised when a required ML model fails to load."""

    code = "MODEL_LOAD_ERROR"


def validate_zone_polygon(zone_polygon_norm: object) -> list[list[float]]:
    """Validate that zone_polygon_norm has >= 3 [x, y] points in [0, 1]."""
    if not isinstance(zone_polygon_norm, (list, tuple)) or len(zone_polygon_norm) < 3:
        raise InvalidArgumentError("zone_polygon_norm must be a list of at least 3 [x, y] points")

    cleaned: list[list[float]] = []
    for idx, pt in enumerate(zone_polygon_norm):
        if not isinstance(pt, (list, tuple)) or len(pt) != 2:
            raise InvalidArgumentError(f"zone_polygon_norm[{idx}] must be [x, y]")
        try:
            x, y = float(pt[0]), float(pt[1])
        except (TypeError, ValueError) as exc:
            raise InvalidArgumentError(f"zone_polygon_norm[{idx}] coordinates must be numeric") from exc
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            raise InvalidArgumentError(f"zone_polygon_norm[{idx}] ({x}, {y}) must be in [0, 1]")
        cleaned.append([x, y])
    return cleaned

