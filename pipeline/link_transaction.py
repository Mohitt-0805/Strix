"""Link person tracks to an ATM transaction window using an ATM spatial zone.

Heavy libraries (numpy, cv2) are imported inside functions only.
"""

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Literal

from pipeline.detect_track import Track


DEFAULT_ZONE_CONFIG = Path(__file__).resolve().parent / "config" / "atm_zone.json"
DEFAULT_LINK_CONFIG = Path(__file__).resolve().parent / "config" / "link.json"


def load_link_config(config_path: str | Path | None = None) -> dict[str, float | int]:
    """Load linking thresholds from pipeline/config/link.json."""
    path = Path(config_path) if config_path is not None else DEFAULT_LINK_CONFIG
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class LinkResult:
    """Result of linking person tracks to a transaction window."""

    chosen_track_id: int | None
    reason: str
    ranking: list[dict[str, Any]] = field(default_factory=list)
    low_margin: bool = False
    fallback: bool = False
    confidence: Literal["High", "Medium", "Low"] = "Low"
    track_count_in_window: int = 0


def compute_anchor(
    box: list[float], frame_h: int, cfg: dict[str, float | int] | None = None
) -> tuple[float, float, bool]:
    """Return (ax, ay, anchor_estimated) for a person box.

    Uses bottom-centre unless y2 >= bottom_edge_ratio * frame_h (cut-off feet),
    in which case estimated_anchor_height_ratio of box height is used.
    """
    thresholds = cfg or load_link_config()
    x1, y1, x2, y2 = [float(v) for v in box]
    ax = (x1 + x2) / 2.0
    if y2 >= float(thresholds["bottom_edge_ratio"]) * float(frame_h):
        ay = y1 + float(thresholds["estimated_anchor_height_ratio"]) * (y2 - y1)
        return ax, ay, True
    return ax, y2, False


def load_zone(atm_id: str, config_path: str | Path | None = None) -> dict[str, Any]:
    """Load normalized ATM zone polygon config for atm_id, raising KeyError if missing."""
    path = Path(config_path) if config_path is not None else DEFAULT_ZONE_CONFIG
    if not path.exists():
        raise FileNotFoundError(f"ATM zone config not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    if atm_id not in data:
        available = ", ".join(sorted(data.keys())) or "(none)"
        raise KeyError(f"ATM zone '{atm_id}' not found in {path}. Available: {available}")
    return data[atm_id]


def _build_zone_mask(zone_polygon_norm: list[list[float]], frame_w: int, frame_h: int) -> Any:
    """Rasterize a normalized [0, 1] polygon into a uint8 binary mask (H, W)."""
    import cv2
    import numpy as np

    mask = np.zeros((frame_h, frame_w), dtype=np.uint8)
    pts = np.asarray(
        [[int(round(x * frame_w)), int(round(y * frame_h))] for x, y in zone_polygon_norm],
        dtype=np.int32,
    )
    cv2.fillPoly(mask, [pts], 1)
    return mask


def _box_overlap_fraction(box: list[float], mask: Any, frame_w: int, frame_h: int) -> float:
    """Return fraction of the person box area that lies inside the binary zone mask."""
    x1 = max(0, min(frame_w, int(round(box[0]))))
    y1 = max(0, min(frame_h, int(round(box[1]))))
    x2 = max(0, min(frame_w, int(round(box[2]))))
    y2 = max(0, min(frame_h, int(round(box[3]))))

    area = max(0, x2 - x1) * max(0, y2 - y1)
    if area <= 0:
        return 0.0
    inside = int(mask[y1:y2, x1:x2].sum())
    return float(inside) / float(area)


def _observation_steps(
    in_window: list[dict[str, Any]],
    max_step_sec: float = 1.0,
    default_dt: float = 0.5,
    win_end: float | None = None,
) -> list[float]:
    """Compute per-observation time steps (seconds), capped at max_step_sec and win_end."""
    n = len(in_window)
    if n == 0:
        return []
    if n == 1:
        last_dt = min(max_step_sec, default_dt)
        if win_end is not None:
            last_dt = min(last_dt, max(0.0, win_end - float(in_window[0]["t"])))
        return [last_dt]
    steps = [
        min(max_step_sec, max(0.0, float(in_window[i + 1]["t"]) - float(in_window[i]["t"])))
        for i in range(n - 1)
    ]
    last_dt = steps[-1]
    if win_end is not None:
        last_dt = min(last_dt, max(0.0, win_end - float(in_window[-1]["t"])))
    steps.append(last_dt)
    return steps


def _check_low_margin(ranking: list[dict[str, Any]], low_margin_ratio: float) -> bool:
    """Return True if the top two ranked tracks have scores within low_margin_ratio."""
    if len(ranking) < 2:
        return False
    top_score = float(ranking[0]["score"])
    second_score = float(ranking[1]["score"])
    if top_score <= 0.0:
        return False
    return ((top_score - second_score) / top_score) <= low_margin_ratio


def _compute_window_len(
    tx_offset_sec: float, window_sec: float, video_duration_sec: float | None
) -> float:
    """Return 2 * window_sec clipped to [0, video_duration_sec]."""
    win_start = max(0.0, tx_offset_sec - window_sec)
    win_end = (
        min(video_duration_sec, tx_offset_sec + window_sec)
        if video_duration_sec is not None
        else (tx_offset_sec + window_sec)
    )
    return max(1e-6, win_end - win_start)


def _classify_confidence(
    dwell_frac: float,
    anchor_frac: float,
    low_margin: bool,
    cfg: dict[str, float | int],
) -> Literal["High", "Medium", "Low"]:
    """Classify link confidence from dwell_frac, anchor_in_zone_frac, and low_margin."""
    if (
        dwell_frac >= float(cfg["high_dwell_frac"])
        and anchor_frac >= float(cfg["high_anchor_frac"])
        and not low_margin
    ):
        return "High"
    if (
        dwell_frac >= float(cfg["medium_dwell_frac"])
        or anchor_frac >= float(cfg["medium_anchor_frac"])
    ):
        return "Medium"
    return "Low"


def _fallback_no_zone(
    tracks: list[Track],
    frame_w: int,
    frame_h: int,
    tx_offset_sec: float,
    window_sec: float,
    cfg: dict[str, float | int],
) -> LinkResult:
    """Fallback when no zone exists: pick longest in-window track nearest frame centre."""
    import math

    t_min = tx_offset_sec - window_sec
    t_max = tx_offset_sec + window_sec
    cx_frame, cy_frame = frame_w / 2.0, frame_h / 2.0
    diag = math.hypot(frame_w, frame_h) or 1.0
    max_step = float(cfg["max_step_sec"])

    candidates: list[tuple[float, float, dict[str, Any]]] = []
    for tr in tracks:
        in_win = [o for o in tr.observations if t_min <= float(o["t"]) <= t_max]
        if not in_win:
            continue
        steps = _observation_steps(in_win, max_step_sec=max_step)
        in_win_dur = float(sum(steps))
        nearest_tx = min(abs(float(o["t"]) - tx_offset_sec) for o in in_win)
        dists = [
            math.hypot(((o["box"][0] + o["box"][2]) / 2.0) - cx_frame, ((o["box"][1] + o["box"][3]) / 2.0) - cy_frame)
            / diag
            for o in in_win
        ]
        mean_center_dist = sum(dists) / len(dists)
        entry = {
            "track_id": tr.track_id,
            "dwell_sec_in_zone": 0.0,
            "mean_zone_overlap": 0.0,
            "anchor_in_zone_frac": 0.0,
            "nearest_obs_to_tx_sec": round(nearest_tx, 4),
            "score": round(in_win_dur, 4),
        }
        candidates.append((in_win_dur, mean_center_dist, entry))

    track_count = len(candidates)
    if not candidates:
        return LinkResult(
            chosen_track_id=None,
            reason="WARNING: No ATM zone configured (fallback); no person track in this window.",
            ranking=[],
            low_margin=False,
            fallback=True,
            confidence="Low",
            track_count_in_window=0,
        )

    candidates.sort(key=lambda item: (-item[0], item[1], item[2]["track_id"]))
    ranking = [item[2] for item in candidates]
    best_id = int(ranking[0]["track_id"])
    low_margin = _check_low_margin(ranking, float(cfg["low_margin_ratio"]))
    reason = (
        f"WARNING: No ATM zone configured; fallback selected longest track {best_id} "
        f"nearest frame centre (duration={ranking[0]['score']:.1f} s)."
    )
    if low_margin:
        reason += " Low margin: top two tracks are within 20% score."
    if track_count > int(cfg["many_tracks_threshold"]):
        reason += " Warning: many tracks, possible ID splits."

    return LinkResult(
        chosen_track_id=best_id,
        reason=reason,
        ranking=ranking,
        low_margin=low_margin,
        fallback=True,
        confidence="Low",
        track_count_in_window=track_count,
    )


def link_transaction(
    tracks: list[Track],
    zone_polygon_norm: list[list[float]] | None,
    frame_w: int,
    frame_h: int,
    tx_offset_sec: float,
    window_sec: float = 10.0,
    video_duration_sec: float | None = None,
) -> LinkResult:
    """Rank tracks by anchor dwell time inside the ATM zone within [tx - window, tx + window]."""
    import cv2
    import numpy as np

    cfg = load_link_config()
    if not zone_polygon_norm or len(zone_polygon_norm) < 3:
        return _fallback_no_zone(tracks, frame_w, frame_h, tx_offset_sec, window_sec, cfg)

    mask = _build_zone_mask(zone_polygon_norm, frame_w, frame_h)
    poly_px = np.asarray(
        [[int(round(x * frame_w)), int(round(y * frame_h))] for x, y in zone_polygon_norm],
        dtype=np.int32,
    )
    t_min = max(0.0, tx_offset_sec - window_sec)
    t_max = (
        min(video_duration_sec, tx_offset_sec + window_sec)
        if video_duration_sec is not None
        else (tx_offset_sec + window_sec)
    )
    window_len = _compute_window_len(tx_offset_sec, window_sec, video_duration_sec)
    max_step = float(cfg["max_step_sec"])

    ranking: list[dict[str, Any]] = []
    for tr in tracks:
        in_win = [o for o in tr.observations if t_min <= float(o["t"]) <= t_max]
        if not in_win:
            continue

        steps = _observation_steps(in_win, max_step_sec=max_step, win_end=t_max)
        overlaps = [_box_overlap_fraction(o["box"], mask, frame_w, frame_h) for o in in_win]
        in_zones = []
        for o in in_win:
            ax, ay, _ = compute_anchor(o["box"], frame_h, cfg=cfg)
            in_zones.append(cv2.pointPolygonTest(poly_px, (float(ax), float(ay)), False) >= 0)

        dwell_sec = min(window_len, sum(dt for in_z, dt in zip(in_zones, steps) if in_z))
        mean_overlap = sum(overlaps) / len(overlaps)
        anchor_frac = sum(1 for in_z in in_zones if in_z) / len(in_zones)
        nearest_tx = min(abs(float(o["t"]) - tx_offset_sec) for o in in_win)

        ranking.append(
            {
                "track_id": tr.track_id,
                "dwell_sec_in_zone": round(dwell_sec, 4),
                "mean_zone_overlap": round(mean_overlap, 4),
                "anchor_in_zone_frac": round(anchor_frac, 4),
                "nearest_obs_to_tx_sec": round(nearest_tx, 4),
                "score": round(dwell_sec, 4),
            }
        )

    ranking.sort(key=lambda r: (-r["score"], r["nearest_obs_to_tx_sec"], r["track_id"]))
    track_count = len(ranking)

    if not ranking or ranking[0]["dwell_sec_in_zone"] < float(cfg["min_dwell_sec"]):
        return LinkResult(
            chosen_track_id=None,
            reason="No person was in the ATM zone in this window",
            ranking=ranking,
            low_margin=False,
            fallback=False,
            confidence="Low",
            track_count_in_window=track_count,
        )

    best = ranking[0]
    low_margin = _check_low_margin(ranking, float(cfg["low_margin_ratio"]))
    dwell_frac = float(best["dwell_sec_in_zone"]) / window_len
    confidence = _classify_confidence(dwell_frac, float(best["anchor_in_zone_frac"]), low_margin, cfg)

    reason = (
        f"Confidence {confidence}: track {best['track_id']} in zone "
        f"{best['dwell_sec_in_zone']:.1f} s of {window_len:.1f} s "
        f"(anchor_frac={best['anchor_in_zone_frac']:.2f})."
    )
    if low_margin:
        reason += " Low margin: top two tracks are within 20% score."
    if track_count > int(cfg["many_tracks_threshold"]):
        reason += " Warning: many tracks, possible ID splits."

    return LinkResult(
        chosen_track_id=int(best["track_id"]),
        reason=reason,
        ranking=ranking,
        low_margin=low_margin,
        fallback=False,
        confidence=confidence,
        track_count_in_window=track_count,
    )
