"""Video metadata extraction via ffprobe with timezone conversion."""

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.app.errors import AppError

UNREADABLE_VIDEO_ADVICE = (
    "Export the clip as MP4 (H.264) from the DVR/NVR software, "
    "or convert it with FFmpeg."
)

# TODO: Optional integration hook for Aditi's pipeline.ingest module once available.
# Detect via try-import at call time; do not assume its API here.


@dataclass(frozen=True)
class ProbeMetadata:
    """Normalized metadata extracted from ffprobe."""

    duration_sec: float
    fps: float | None
    width: int
    height: int
    codec: str | None
    container: str | None
    rotation: int
    creation_time_local: datetime | None


def parse_fps(rate_str: str | None) -> float | None:
    """Parse ffprobe rational frame rates such as '30000/1001' or '25/1'."""
    if not rate_str:
        return None
    raw = rate_str.strip()
    if "/" in raw:
        num_s, den_s = raw.split("/", 1)
        try:
            num = float(num_s)
            den = float(den_s)
        except ValueError:
            return None
        if den <= 0 or num <= 0:
            return None
        return round(num / den, 4)
    try:
        val = float(raw)
        return round(val, 4) if val > 0 else None
    except ValueError:
        return None


def parse_creation_time(raw_value: str | None, display_tz: str) -> datetime | None:
    """Parse ffprobe creation_time (UTC by default) and convert to naive DISPLAY_TZ."""
    if not raw_value:
        return None
    cleaned = raw_value.strip()
    if not cleaned:
        return None
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo(display_tz)).replace(tzinfo=None)


def _extract_tag(tags: dict[str, Any] | None, key: str) -> str | None:
    """Case-insensitive tag lookup on ffprobe format/stream tag dicts."""
    if not tags:
        return None
    target = key.lower()
    for k, v in tags.items():
        if str(k).lower() == target and v is not None:
            return str(v)
    return None


def _extract_rotation(video_stream: dict[str, Any]) -> int:
    """Extract video rotation angle from stream tags or side_data_list."""
    raw_rotate = _extract_tag(video_stream.get("tags"), "rotate")
    if raw_rotate is not None:
        try:
            return int(float(raw_rotate))
        except ValueError:
            pass
    for item in video_stream.get("side_data_list") or []:
        if "rotation" in item:
            try:
                return int(float(item["rotation"]))
            except (TypeError, ValueError):
                pass
    return 0


def probe_video(video_path: Path, display_tz: str, timeout_sec: int = 15) -> ProbeMetadata:
    """Run ffprobe on video_path and return normalized ProbeMetadata."""
    ffprobe_bin = shutil.which("ffprobe")
    if not ffprobe_bin:
        raise AppError(
            status_code=500,
            code="FFPROBE_MISSING",
            detail="ffprobe binary is missing from PATH.",
        )

    cmd = [
        ffprobe_bin,
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(video_path),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AppError(
            status_code=422,
            code="UNREADABLE_VIDEO",
            detail=f"Timed out reading video metadata. {UNREADABLE_VIDEO_ADVICE}",
        ) from exc

    if proc.returncode != 0 or not proc.stdout.strip():
        raise AppError(
            status_code=422,
            code="UNREADABLE_VIDEO",
            detail=f"Unable to read video file. {UNREADABLE_VIDEO_ADVICE}",
        )

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AppError(
            status_code=422,
            code="UNREADABLE_VIDEO",
            detail=f"Corrupt video metadata. {UNREADABLE_VIDEO_ADVICE}",
        ) from exc

    streams = payload.get("streams") or []
    fmt = payload.get("format") or {}
    video_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "video"),
        None,
    )
    if video_stream is None:
        raise AppError(
            status_code=422,
            code="UNREADABLE_VIDEO",
            detail=f"No video stream found in file. {UNREADABLE_VIDEO_ADVICE}",
        )

    raw_duration = video_stream.get("duration") or fmt.get("duration")
    try:
        duration_sec = float(raw_duration)
    except (TypeError, ValueError) as exc:
        raise AppError(
            status_code=422,
            code="UNREADABLE_VIDEO",
            detail=f"Video duration is missing or invalid. {UNREADABLE_VIDEO_ADVICE}",
        ) from exc

    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    if duration_sec <= 0 or width <= 0 or height <= 0:
        raise AppError(
            status_code=422,
            code="UNREADABLE_VIDEO",
            detail=f"Invalid video dimensions or duration. {UNREADABLE_VIDEO_ADVICE}",
        )

    fps = parse_fps(video_stream.get("avg_frame_rate")) or parse_fps(
        video_stream.get("r_frame_rate")
    )
    raw_creation = _extract_tag(fmt.get("tags"), "creation_time") or _extract_tag(
        video_stream.get("tags"), "creation_time"
    )

    return ProbeMetadata(
        duration_sec=duration_sec,
        fps=fps,
        width=width,
        height=height,
        codec=video_stream.get("codec_name"),
        container=fmt.get("format_name"),
        rotation=_extract_rotation(video_stream),
        creation_time_local=parse_creation_time(raw_creation, display_tz),
    )
