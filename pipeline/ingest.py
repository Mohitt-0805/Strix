"""CCTV video ingestion, format validation, and transcoding for Strix.

This module provides standalone video inspection and transcoding for CCTV footage
without importing heavy ML libraries (torch, cv2, insightface, onnxruntime).
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from typing import Optional, Set

from pydantic import BaseModel, Field

# CCTV video extensions accepted by Strix
ACCEPTED_EXTENSIONS: Set[str] = {
    "mp4",
    "avi",
    "mov",
    "mkv",
    "wmv",
    "flv",
    "mpeg",
    "mpg",
}

# Standard H.264 codec names reported by ffprobe / ffmpeg
H264_CODECS: Set[str] = {"h264", "avc", "avc1"}

# Standard MP4 container names reported by ffprobe
MP4_CONTAINERS: Set[str] = {
    "mp4",
    "mov,mp4,m4a,3gp,3g2,mj2",
    "isom",
    "iso2",
    "mp41",
    "mp42",
    "quicktime,mov,mp4,m4a,3gp,3g2,mj2",
}


class IngestResult(BaseModel):
    """Result schema for CCTV video ingestion, validation, and conversion."""

    ok: bool = Field(description="Whether ingestion and validation succeeded")
    output_path: Optional[Path] = Field(
        default=None,
        description="Path to ready-to-process H.264 MP4 footage (original or converted)",
    )
    codec: Optional[str] = Field(
        default=None,
        description="Primary video codec identified (e.g. 'h264', 'hevc', 'mpeg4')",
    )
    container: Optional[str] = Field(
        default=None,
        description="Container format name from ffprobe (e.g. 'mov,mp4,m4a,3gp,3g2,mj2')",
    )
    width: Optional[int] = Field(default=None, description="Video stream width in pixels")
    height: Optional[int] = Field(default=None, description="Video stream height in pixels")
    fps: Optional[float] = Field(
        default=None,
        description="Normalized video frame rate (rounded to 4 decimal places)",
    )
    duration_sec: Optional[float] = Field(
        default=None,
        description="Total duration in seconds (rounded to 4 decimal places)",
    )
    converted: bool = Field(
        default=False,
        description="True if clip was transcoded to H.264 MP4; False if original was used",
    )
    error_code: Optional[str] = Field(
        default=None,
        description="Machine-readable error code if ok is False",
    )
    advice: Optional[str] = Field(
        default=None,
        description="Clear plain-language guidance or remedy for investigators",
    )


def parse_fps(rate_str: Optional[str]) -> Optional[float]:
    """Parse ffprobe rational frame rate string (e.g. '30/1' or '30000/1001')."""
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


def probe_clip(clip_path: Path, timeout_sec: int = 30) -> dict:
    """Execute ffprobe and return parsed streams and format JSON dictionary.

    Raises:
        FileNotFoundError: If ffprobe binary is not found on system PATH.
        subprocess.TimeoutExpired: If ffprobe execution exceeds timeout_sec.
        subprocess.CalledProcessError: If ffprobe exits with non-zero status.
        json.JSONDecodeError: If ffprobe output cannot be parsed as JSON.
    """
    ffprobe_bin = shutil.which("ffprobe")
    if not ffprobe_bin:
        raise FileNotFoundError("ffprobe binary is not found on PATH.")

    cmd = [
        ffprobe_bin,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height,r_frame_rate,avg_frame_rate,duration",
        "-show_entries",
        "format=format_name,duration",
        "-of",
        "json",
        str(clip_path),
    ]

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        check=False,
    )

    if proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode, cmd, output=proc.stdout, stderr=proc.stderr
        )

    return json.loads(proc.stdout)


def check_and_convert(src: Path, out_dir: Path) -> IngestResult:
    """Validate CCTV footage and transcode to H.264 MP4 if necessary.

    Rules:
    - Never modifies or replaces the original file.
    - Accepts: mp4, avi, mov, mkv, wmv, flv, mpeg, mpg.
    - If already H.264 in MP4 container, returns ok=True, converted=False, output_path=src.
    - Otherwise, transcodes to <out_dir>/<src.stem>_converted.mp4 with H.264 video,
      preserving variable frame rate timestamps.
    - Returns plain-language advice on validation or conversion failures.
    """
    src_path = Path(src)
    output_directory = Path(out_dir)

    # 1. Validate file extension
    ext = src_path.suffix.lower().lstrip(".")
    if ext not in ACCEPTED_EXTENSIONS:
        return IngestResult(
            ok=False,
            error_code="UNSUPPORTED_EXTENSION",
            advice=(
                f"File extension '.{ext or 'none'}' is not supported. "
                f"Accepted CCTV footage formats: {', '.join(sorted(ACCEPTED_EXTENSIONS))}."
            ),
        )

    # 2. Check existence and file attributes
    if not src_path.exists():
        return IngestResult(
            ok=False,
            error_code="FILE_NOT_FOUND",
            advice="File does not exist or file path is invalid. Verify the storage location and permissions.",
        )

    if not src_path.is_file():
        return IngestResult(
            ok=False,
            error_code="NOT_A_FILE",
            advice="The specified path points to a directory or system node, not a regular video file.",
        )

    if src_path.stat().st_size == 0:
        return IngestResult(
            ok=False,
            error_code="EMPTY_FILE",
            advice="The video file is empty (0 bytes). Check the camera export or transfer status.",
        )

    # 3. Check ffprobe availability
    if not shutil.which("ffprobe"):
        return IngestResult(
            ok=False,
            error_code="FFPROBE_MISSING",
            advice="ffprobe binary is missing from system PATH. Ensure FFmpeg suite is installed.",
        )

    # 4. Probe video streams and container metadata
    try:
        data = probe_clip(src_path, timeout_sec=30)
    except subprocess.TimeoutExpired:
        return IngestResult(
            ok=False,
            error_code="FFPROBE_TIMEOUT",
            advice="Media probe timed out after 30 seconds. Video container or stream header may be corrupt.",
        )
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return IngestResult(
            ok=False,
            error_code="UNREADABLE_FILE",
            advice=(
                "ffprobe could not read the video file. The file may be corrupt, truncated, "
                "or encrypted in a non-standard proprietary DVR container."
            ),
        )
    except Exception as exc:
        return IngestResult(
            ok=False,
            error_code="PROBE_FAILED",
            advice=f"Unexpected error while analyzing video with ffprobe: {exc}",
        )

    streams = data.get("streams", [])
    format_info = data.get("format", {})
    container_name = format_info.get("format_name")

    if not streams:
        return IngestResult(
            ok=False,
            container=container_name,
            error_code="NO_VIDEO_STREAM",
            advice="No video stream detected in media file. Ensure the clip contains an active CCTV video track.",
        )

    video_stream = streams[0]
    codec = video_stream.get("codec_name")
    if not codec:
        return IngestResult(
            ok=False,
            container=container_name,
            error_code="UNKNOWN_CODEC",
            advice=(
                "Proprietary or unrecognized video codec detected (common in bank CCTV/DVR exports "
                "such as DAV, H.265/HEVC, or proprietary MPEG-4). Export footage from DVR/NVR using standard "
                "H.264 MP4 format, or transcode using Handbrake."
            ),
        )

    width = video_stream.get("width")
    height = video_stream.get("height")
    fps = parse_fps(video_stream.get("avg_frame_rate")) or parse_fps(video_stream.get("r_frame_rate"))

    raw_duration = video_stream.get("duration") or format_info.get("duration")
    duration_sec: Optional[float] = None
    if raw_duration is not None:
        try:
            parsed_d = float(raw_duration)
            if parsed_d > 0:
                duration_sec = round(parsed_d, 4)
        except (ValueError, TypeError):
            pass

    if duration_sec is None or duration_sec <= 0:
        return IngestResult(
            ok=False,
            codec=codec,
            container=container_name,
            width=width,
            height=height,
            fps=fps,
            duration_sec=0.0,
            error_code="ZERO_DURATION",
            advice=(
                "Media stream has 0.0s duration or empty timestamp index. The recording may have been "
                "truncated or corrupted during export."
            ),
        )

    # 5. Check if already H.264 in MP4 container
    is_h264 = codec.lower() in H264_CODECS
    is_mp4_container = (
        src_path.suffix.lower() == ".mp4"
        and container_name is not None
        and any(c in container_name.lower() for c in ("mp4", "mov", "isom"))
    )

    if is_h264 and is_mp4_container:
        return IngestResult(
            ok=True,
            output_path=src_path,
            codec=codec,
            container=container_name,
            width=width,
            height=height,
            fps=fps,
            duration_sec=duration_sec,
            converted=False,
        )

    # 6. Transcoding required: check ffmpeg availability
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        return IngestResult(
            ok=False,
            codec=codec,
            container=container_name,
            width=width,
            height=height,
            fps=fps,
            duration_sec=duration_sec,
            converted=False,
            error_code="FFMPEG_MISSING",
            advice=(
                "Conversion to H.264 MP4 required, but ffmpeg binary is not found on PATH. "
                "Install FFmpeg to process non-H.264 clips."
            ),
        )

    output_directory.mkdir(parents=True, exist_ok=True)
    converted_path = output_directory / f"{src_path.stem}_converted.mp4"

    # Transcode preserving variable frame rate timestamps:
    # -vsync 0 passes timestamps through from demuxer to muxer without dropping or duplicating frames.
    # Original file is preserved untouched.
    ffmpeg_cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(src_path),
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "22",
        "-vsync",
        "0",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(converted_path),
    ]

    try:
        conv_proc = subprocess.run(
            ffmpeg_cmd,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired:
        if converted_path.exists():
            converted_path.unlink(missing_ok=True)
        return IngestResult(
            ok=False,
            codec=codec,
            container=container_name,
            width=width,
            height=height,
            fps=fps,
            duration_sec=duration_sec,
            converted=False,
            error_code="FFMPEG_TIMEOUT",
            advice="Transcoding to H.264 MP4 timed out after 120 seconds.",
        )
    except Exception as exc:
        if converted_path.exists():
            converted_path.unlink(missing_ok=True)
        return IngestResult(
            ok=False,
            codec=codec,
            container=container_name,
            width=width,
            height=height,
            fps=fps,
            duration_sec=duration_sec,
            converted=False,
            error_code="CONVERSION_FAILED",
            advice=f"Error executing ffmpeg: {exc}",
        )

    if conv_proc.returncode != 0 or not converted_path.is_file() or converted_path.stat().st_size == 0:
        if converted_path.exists():
            converted_path.unlink(missing_ok=True)
        return IngestResult(
            ok=False,
            codec=codec,
            container=container_name,
            width=width,
            height=height,
            fps=fps,
            duration_sec=duration_sec,
            converted=False,
            error_code="CONVERSION_FAILED",
            advice=(
                "FFmpeg failed to transcode footage to H.264 MP4. The video stream may contain unsupported "
                "proprietary NAL packets or damaged keyframe indices. Consider re-exporting from DVR."
            ),
        )

    # 7. Probe converted file to obtain fresh metadata
    try:
        conv_data = probe_clip(converted_path, timeout_sec=15)
        conv_streams = conv_data.get("streams", [])
        conv_format = conv_data.get("format", {})
        if conv_streams:
            conv_v = conv_streams[0]
            out_codec = conv_v.get("codec_name") or "h264"
            out_container = conv_format.get("format_name") or "mov,mp4,m4a,3gp,3g2,mj2"
            out_width = conv_v.get("width") or width
            out_height = conv_v.get("height") or height
            out_fps = parse_fps(conv_v.get("avg_frame_rate")) or fps
            raw_c_dur = conv_v.get("duration") or conv_format.get("duration")
            out_duration = round(float(raw_c_dur), 4) if raw_c_dur else duration_sec
        else:
            out_codec = "h264"
            out_container = "mp4"
            out_width = width
            out_height = height
            out_fps = fps
            out_duration = duration_sec
    except Exception:
        out_codec = "h264"
        out_container = "mp4"
        out_width = width
        out_height = height
        out_fps = fps
        out_duration = duration_sec

    return IngestResult(
        ok=True,
        output_path=converted_path,
        codec=out_codec,
        container=out_container,
        width=out_width,
        height=out_height,
        fps=out_fps,
        duration_sec=out_duration,
        converted=True,
    )
