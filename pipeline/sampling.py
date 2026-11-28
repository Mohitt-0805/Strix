"""Pure-Python window sampling planning and coverage verification helpers."""

import math

from pipeline.errors import InvalidArgumentError

DEFAULT_WINDOW_MARGIN_SEC = 1.0
DEFAULT_MAX_SAMPLED_FRAMES = 200
DEFAULT_MIN_SAMPLE_FPS = 0.5


def resolve_window_sample_fps(
    window_sec: float,
    requested_fps: float,
    *,
    margin_sec: float = DEFAULT_WINDOW_MARGIN_SEC,
    max_frames: int = DEFAULT_MAX_SAMPLED_FRAMES,
    min_fps: float = DEFAULT_MIN_SAMPLE_FPS,
) -> tuple[float, int, str | None]:
    """Compute effective sample FPS so the whole transaction window fits in max_frames.

    Returns (effective_fps, needed_frames, warning_or_none).
    Raises InvalidArgumentError if covering the window requires < min_fps.
    """
    win = float(window_sec)
    req_fps = float(requested_fps)
    margin = float(margin_sec)
    span_sec = 2.0 * win + 2.0 * margin
    needed_frames = math.ceil(span_sec * req_fps) + 1

    if needed_frames <= int(max_frames):
        return req_fps, needed_frames, None

    raw_eff = float(max_frames) / (span_sec + 1.0)
    # Round down to 2 decimals while avoiding binary float representation underflow on exact steps.
    effective_fps = round(math.floor(raw_eff * 100.0 + 1e-12) / 100.0, 2)

    if effective_fps < float(min_fps):
        max_win_req = max(0.0, ((float(max_frames) - 1.0) / req_fps - 2.0 * margin) / 2.0)
        max_win_min = max(0.0, (float(max_frames) / float(min_fps) - 2.0 * margin - 1.0) / 2.0)
        raise InvalidArgumentError(
            f"window_sec={win:g} cannot be covered within {max_frames} frames "
            f"(effective_fps={effective_fps:.2f} < min_fps={min_fps:g}). "
            f"Max window at {req_fps:g} fps is {max_win_req:.2f} s; "
            f"max window at min_fps={min_fps:g} fps is {max_win_min:.2f} s."
        )

    warning = (
        f"Window too long for {req_fps} fps; "
        f"sampled at {effective_fps} fps so the whole window is covered."
    )
    return effective_fps, needed_frames, warning


def check_coverage_end(
    last_sampled_t: float,
    window_end_sec: float,
    effective_fps: float,
) -> str | None:
    """Warn if last_sampled_t stops more than (1/effective_fps + 0.5)s before window_end_sec."""
    tolerance = (1.0 / float(effective_fps)) + 0.5
    if float(last_sampled_t) < float(window_end_sec) - tolerance - 1e-9:
        return (
            f"Sampled frames ended at {last_sampled_t:.2f}s, "
            f"more than {tolerance:.2f}s before window end {window_end_sec:.2f}s."
        )
    return None
