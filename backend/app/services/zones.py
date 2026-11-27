"""Lightweight reader and validator for ATM zone polygons (no heavy imports)."""

import json
import math
from pathlib import Path
from typing import Any

from backend.app.config import REPO_ROOT
from backend.app.errors import AppError

ATM_ZONE_CONFIG_PATH = REPO_ROOT / "pipeline" / "config" / "atm_zone.json"


def load_atm_zones(config_path: Path | None = None) -> list[dict[str, Any]]:
    """Read pipeline/config/atm_zone.json directly as JSON and return sorted entries."""
    path = config_path or ATM_ZONE_CONFIG_PATH
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return []

    zones: list[dict[str, Any]] = []
    for zone_id in sorted(raw.keys()):
        entry = raw[zone_id]
        if not isinstance(entry, dict):
            continue
        zones.append(
            {
                "id": str(zone_id),
                "note": str(entry.get("note") or ""),
                "polygon": entry.get("polygon") or [],
            }
        )
    return zones


def get_valid_zone_ids(config_path: Path | None = None) -> list[str]:
    """Return sorted list of valid atm_id keys from atm_zone.json."""
    return [z["id"] for z in load_atm_zones(config_path)]


def validate_zone_polygon_norm(value: Any) -> list[list[float]] | None:
    """Validate >= 3 [x, y] points with values in [0, 1]; raise 422 ZONE_INVALID."""
    if value is None:
        return None
    if not isinstance(value, list) or len(value) < 3:
        raise AppError(
            status_code=422,
            code="ZONE_INVALID",
            detail="zone_polygon_norm must be a list of at least 3 [x, y] points.",
        )

    cleaned: list[list[float]] = []
    for idx, pt in enumerate(value):
        if not isinstance(pt, (list, tuple)) or len(pt) != 2:
            raise AppError(
                status_code=422,
                code="ZONE_INVALID",
                detail=f"zone_polygon_norm[{idx}] must be [x, y].",
            )
        raw_x, raw_y = pt[0], pt[1]
        if isinstance(raw_x, bool) or isinstance(raw_y, bool):
            raise AppError(
                status_code=422,
                code="ZONE_INVALID",
                detail=f"zone_polygon_norm[{idx}] coordinates must be numbers in [0, 1].",
            )
        try:
            x, y = float(raw_x), float(raw_y)
        except (TypeError, ValueError) as exc:
            raise AppError(
                status_code=422,
                code="ZONE_INVALID",
                detail=f"zone_polygon_norm[{idx}] coordinates must be numbers in [0, 1].",
            ) from exc
        if not (math.isfinite(x) and math.isfinite(y) and 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            raise AppError(
                status_code=422,
                code="ZONE_INVALID",
                detail=f"zone_polygon_norm[{idx}] ({x}, {y}) must be between 0 and 1.",
            )
        cleaned.append([x, y])
    return cleaned
