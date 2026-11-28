"""Video metadata inspection and sequential frame sampling utilities.

Heavy/external imports (cv2, subprocess) live inside functions so teammates
without OpenCV can still import lightweight pipeline modules.
"""

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Iterator


MAX_SAMPLED_FRAMES = 200
_PTS_CACHE_DIR = Path("data/outputs/.pts_cache")


def _pts_cache_path(video_path: Path) -> Path:
    """Build deterministic PTS cache path keyed by resolved path, size, and mtime_ns."""
    resolved = str(video_path.resolve())
    st = video_path.stat()
    key = f"{resolved}:{st.st_size}:{st.st_mtime_ns}".encode("utf-8")
    digest = hashlib.sha256(key).hexdigest()[:24]
    return _PTS_CACHE_DIR / f"{digest}.json"


def _extract_float(record: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for k in keys:
        val = record.get(k)
        if val is not None and val != "N/A":
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None


def _load_frame_pts(video_path: Path) -> list[float] | None:
    """Return display-ordered per-frame PTS list via cache + ffprobe, or None on failure."""
    try:
        cache_path = _pts_cache_path(video_path)
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cached, list) and cached:
                return [float(x) for x in cached]
    except Exception:
        cache_path = None  # type: ignore[assignment]

    try:
        cmd_frames = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_frames",
            "-show_entries",
            "frame=pts_time,pkt_pts_time,best_effort_timestamp_time",
            "-of",
            "json",
            str(video_path),
        ]
        proc = subprocess.run(cmd_frames, capture_output=True, text=True, check=True)
        payload = json.loads(proc.stdout)
        pts_list = [
            v
            for fr in payload.get("frames", [])
            if (v := _extract_float(fr, ("pts_time", "best_effort_timestamp_time", "pkt_pts_time"))) is not None
        ]

        if not pts_list:
            cmd_pkts = [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_packets",
                "-show_entries",
                "packet=pts_time,dts_time",
                "-of",
                "json",
                str(video_path),
            ]
            proc_p = subprocess.run(cmd_pkts, capture_output=True, text=True, check=True)
            payload_p = json.loads(proc_p.stdout)
            pts_list = [
                v
                for pkt in payload_p.get("packets", [])
                if (v := _extract_float(pkt, ("pts_time", "dts_time"))) is not None
            ]

        if not pts_list:
            return None
        pts_list.sort()
    except Exception:
        return None

    try:
        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(pts_list), encoding="utf-8")
    except OSError:
        pass
    return pts_list


def _parse_fps(rate_str: str) -> float:
    """Parse an ffprobe rational frame-rate string like '25/1' or '30000/1001'."""
    if "/" in rate_str:
        num_str, den_str = rate_str.split("/", 1)
        den = float(den_str)
        return float(num_str) / den if den != 0 else 0.0
    return float(rate_str)


def _extract_rotation(stream: dict[str, Any]) -> int:
    """Extract rotation in degrees from ffprobe stream side_data_list or tags."""
    for side_data in stream.get("side_data_list", []):
        if "rotation" in side_data:
            return int(round(float(side_data["rotation"])))
    rotate_tag = stream.get("tags", {}).get("rotate")
    if rotate_tag is not None:
        return int(round(float(rotate_tag)))
    return 0


def video_info(path: str | Path) -> dict[str, Any]:
    """Return video metadata using ffprobe JSON output."""
    import subprocess

    video_path = Path(path)
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(video_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    payload = json.loads(proc.stdout)

    video_stream = next(
        (s for s in payload.get("streams", []) if s.get("codec_type") == "video"),
        None,
    )
    if video_stream is None:
        raise ValueError(f"No video stream found in {video_path}")

    width = int(video_stream["width"])
    height = int(video_stream["height"])
    rotation = _extract_rotation(video_stream)

    # Swap display dimensions for 90-degree or 270-degree rotations.
    if abs(rotation) % 180 == 90:
        display_width, display_height = height, width
    else:
        display_width, display_height = width, height

    raw_duration = video_stream.get("duration") or payload.get("format", {}).get("duration") or 0.0
    r_fps = _parse_fps(video_stream.get("r_frame_rate") or "0/1")
    avg_fps = _parse_fps(video_stream.get("avg_frame_rate") or "0/1")
    fps = r_fps or avg_fps
    vfr_suspected = bool(
        r_fps > 0.0 and avg_fps > 0.0 and (abs(avg_fps - r_fps) / max(r_fps, 1e-9)) > 0.01
    )

    return {
        "duration_sec": float(raw_duration),
        "fps": fps,
        "width": width,
        "height": height,
        "codec": str(video_stream.get("codec_name", "")),
        "rotation": rotation,
        "display_width": display_width,
        "display_height": display_height,
        "vfr_suspected": vfr_suspected,
    }


def _apply_rotation(frame: Any, rotation: int, cv2_mod: Any) -> Any:
    """Rotate a BGR frame to upright orientation based on ffprobe Display Matrix."""
    norm = rotation % 360
    if norm == 270:
        # ffprobe Display Matrix -90 (270 mod 360) means rotate 90 deg clockwise.
        return cv2_mod.rotate(frame, cv2_mod.ROTATE_90_CLOCKWISE)
    if norm == 180:
        return cv2_mod.rotate(frame, cv2_mod.ROTATE_180)
    if norm == 90:
        return cv2_mod.rotate(frame, cv2_mod.ROTATE_90_COUNTERCLOCKWISE)
    return frame


def iter_sampled_frames(
    path: str | Path,
    start_sec: float,
    end_sec: float,
    sample_fps: float,
    max_frames: int | None = MAX_SAMPLED_FRAMES,
) -> Iterator[tuple[float, Any]]:
    """Sequentially read frames using cap.grab() and yield (timestamp_sec, bgr_ndarray).

    Never seeks per frame. Enforces max_frames (default 200; pass None for streaming)
    and ensures phone videos with rotation metadata are returned upright.
    """
    import cv2

    if sample_fps <= 0:
        raise ValueError("sample_fps must be positive")
    if end_sec < start_sec:
        raise ValueError("end_sec must be >= start_sec")

    video_path = Path(path)
    info = video_info(video_path)
    source_fps = info["fps"]
    if source_fps <= 0:
        raise ValueError(f"Invalid source FPS ({source_fps}) for {video_path}")

    rotation = info["rotation"]
    pts_table = _load_frame_pts(video_path)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open video: {video_path}")

    try:
        auto_orient = bool(cap.get(cv2.CAP_PROP_ORIENTATION_AUTO))
        step_sec = 1.0 / sample_fps
        next_sample_time = float(start_sec)
        frame_index = 0
        last_timestamp: float | None = None
        yielded = 0

        while max_frames is None or yielded < max_frames:
            if not cap.grab():
                break

            if pts_table is not None and frame_index < len(pts_table):
                timestamp = pts_table[frame_index]
            else:
                pos_msec = cap.get(cv2.CAP_PROP_POS_MSEC)
                pos_sec = float(pos_msec) / 1000.0 if pos_msec is not None else -1.0
                if pos_sec >= 0.0 and (last_timestamp is None or pos_sec > last_timestamp + 1e-6):
                    timestamp = pos_sec
                else:
                    timestamp = frame_index / source_fps
            last_timestamp = timestamp
            frame_index += 1

            if timestamp > end_sec + 1e-9:
                break

            if timestamp + 1e-9 >= next_sample_time:
                ok, frame = cap.retrieve()
                if not ok or frame is None:
                    break
                if not auto_orient and rotation != 0:
                    frame = _apply_rotation(frame, rotation, cv2)

                yield (timestamp, frame)
                yielded += 1

                while next_sample_time <= timestamp + 1e-9:
                    next_sample_time += step_sec
    finally:
        cap.release()
