"""Non-destructive frame enhancement service with caching and SHA-256 verification."""

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from backend.app.config import Settings
from backend.app.errors import AppError
from backend.app.services.storage import from_rel, to_rel
from pipeline.contract import Enhancement

logger = logging.getLogger(__name__)

ALLOWED_SCALES = (2, 4)
ALLOWED_METHODS = ("lanczos",)


def _sha256_file(path: Path) -> str:
    """Compute hex SHA-256 digest of a file on disk."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _cache_key(
    frame_sha256: str,
    crop_box: list[int],
    method: str,
    scale: int,
) -> str:
    """Build deterministic cache key for (frame_sha256, crop_box, method, scale)."""
    payload = f"{frame_sha256}:{crop_box[0]},{crop_box[1]},{crop_box[2]},{crop_box[3]}:{method}:{scale}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_cache(cache_file: Path) -> dict[str, Any]:
    if not cache_file.is_file():
        return {}
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cache(cache_file: Path, data: dict[str, Any]) -> None:
    cache_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def enhance_frame_crop(
    *,
    frame_rel_path: str,
    crop_box: list[int],
    scale: int,
    method: str,
    settings: Settings,
) -> tuple[dict[str, Any], bool]:
    """Crop and upscale a full-frame image, caching by (frame, crop_box, method, scale).

    Returns (enhancement_dict_with_rel_path, cached_hit).
    """
    if scale not in ALLOWED_SCALES:
        raise AppError(
            status_code=422,
            code="ENHANCE_INVALID",
            detail=f"scale must be 2 or 4, got {scale}.",
        )
    if method not in ALLOWED_METHODS:
        raise AppError(
            status_code=422,
            code="ENHANCE_INVALID",
            detail=f"Unknown enhancement method {method!r}. Known methods: {', '.join(ALLOWED_METHODS)}.",
        )
    if len(crop_box) != 4:
        raise AppError(
            status_code=422,
            code="ENHANCE_INVALID",
            detail=f"crop_box must have 4 integers [x, y, w, h], got {crop_box}.",
        )

    data_root = settings.resolved_data_dir
    frame_abs = from_rel(frame_rel_path, data_root, allowed_roots=("outputs", "uploads"))
    if not frame_abs.is_file():
        raise AppError(
            status_code=404,
            code="FILE_NOT_FOUND",
            detail="Source frame image file is missing on disk.",
        )

    orig_sha_before = _sha256_file(frame_abs)
    clean_box = [int(v) for v in crop_box]
    cache_file = frame_abs.parent / "backend_enhance_cache.json"
    key = _cache_key(orig_sha_before, clean_box, method, scale)
    out_dir = frame_abs.parent / f"enh_{key[:10]}"

    cache_data = _load_cache(cache_file)
    if key in cache_data:
        try:
            cached_enh = Enhancement.model_validate(cache_data[key])
            cached_abs = from_rel(
                cached_enh.enhanced_path, data_root, allowed_roots=("outputs",)
            )
            if cached_abs.is_file():
                return cached_enh.model_dump(mode="json"), True
        except Exception:
            pass

    try:
        enh = _run_enhancer(
            frame_abs=frame_abs,
            crop_box=clean_box,
            scale=scale,
            method=method,
            out_dir=out_dir,
            use_fake=settings.use_fake_pipeline,
        )
    except ValueError as exc:
        raise AppError(
            status_code=422,
            code="ENHANCE_INVALID",
            detail=str(exc),
        ) from exc

    # Verify original image bytes were never modified.
    orig_sha_after = _sha256_file(frame_abs)
    if orig_sha_after != orig_sha_before:
        raise AppError(
            status_code=500,
            code="ORIGINAL_MODIFIED",
            detail="Original frame file checksum changed unexpectedly during enhancement.",
        )

    rel_enhanced = to_rel(enh.enhanced_path, data_root)
    enh_abs = from_rel(rel_enhanced, data_root, allowed_roots=("outputs", "uploads"))
    if not enh_abs.is_file():
        raise AppError(
            status_code=500,
            code="ENHANCE_FAILED",
            detail="Enhanced output file was not created.",
        )

    normalized = enh.model_copy(update={"enhanced_path": rel_enhanced})
    enh_dict = normalized.model_dump(mode="json")

    cache_data[key] = enh_dict
    _save_cache(cache_file, cache_data)
    return enh_dict, False


def _run_enhancer(
    *,
    frame_abs: Path,
    crop_box: list[int],
    scale: int,
    method: str,
    out_dir: Path,
    use_fake: bool,
) -> Enhancement:
    """Call fake_enhance in fake mode, or pipeline.enhance.enhance_frame with fallback."""
    from pipeline.fake_pipeline import fake_enhance

    if use_fake:
        res = fake_enhance(frame_abs, crop_box, scale=scale, out_dir=out_dir)
        return _coerce_enhancement(res, crop_box=crop_box, scale=scale, method=method)

    try:
        from pipeline.enhance import enhance_frame

        res = enhance_frame(
            frame_abs,
            crop_box,
            method=method,
            scale=scale,
            out_dir=out_dir,
        )
        return _coerce_enhancement(res, crop_box=crop_box, scale=scale, method=method)
    except ImportError as exc:
        logger.warning(
            "pipeline.enhance.enhance_frame unavailable (%s); falling back to fake_enhance.",
            exc,
        )
        res = fake_enhance(frame_abs, crop_box, scale=scale, out_dir=out_dir)
        return _coerce_enhancement(res, crop_box=crop_box, scale=scale, method=method)


def _coerce_enhancement(
    raw: Enhancement | Path | str,
    *,
    crop_box: list[int],
    scale: int,
    method: str,
) -> Enhancement:
    """Normalize Enhancement or Path return values into an Enhancement contract model."""
    if isinstance(raw, Enhancement):
        return raw
    return Enhancement(
        enhanced_path=str(raw),
        method=method,
        scale=scale,
        model_version="lanczos_v1",
        crop_box=crop_box,
        search_embedding_source="original",
    )
