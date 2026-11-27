"""Lightweight fake pipeline for teammates without ML libraries installed.

Uses only Python stdlib, Pydantic, and Pillow (no torch, no cv2).
"""

from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw

from pipeline.contract import PipelineResult, load_result
from pipeline.errors import InvalidArgumentError, ZoneNotFoundError, validate_zone_polygon
from pipeline.link_transaction import load_zone


SAMPLE_RESULT_PATH = Path(__file__).resolve().parent.parent / "docs" / "sample_result.json"


def _emit(progress_cb: Callable[[dict[str, Any]], None] | None, stage: str, fraction: float, message: str) -> None:
    if progress_cb is None:
        return
    try:
        progress_cb({"stage": stage, "fraction": float(fraction), "message": message})
    except Exception:
        pass


def run(
    clip_path: str | Path,
    tx_offset_sec: float,
    window_sec: float = 10,
    atm_id: str = "",
    transaction_time: str | None = None,
    sample_fps: float = 2.0,
    tracker: str = "iou",
    out_dir: str | Path = "data/outputs",
    zone_polygon_norm: list[list[float]] | None = None,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
) -> PipelineResult:
    """Return a validated PipelineResult from docs/sample_result.json.

    Accepts the same keyword arguments and validates arguments identically to
    pipeline.run_pipeline.run().
    """
    _ = (tracker, out_dir)
    if float(window_sec) <= 0.0:
        raise InvalidArgumentError(f"window_sec must be > 0, got {window_sec}")
    if float(sample_fps) <= 0.0:
        raise InvalidArgumentError(f"sample_fps must be > 0, got {sample_fps}")
    if float(tx_offset_sec) < 0.0:
        raise InvalidArgumentError(f"tx_offset_sec must be >= 0, got {tx_offset_sec}")

    if zone_polygon_norm is not None:
        validate_zone_polygon(zone_polygon_norm)
    elif atm_id:
        try:
            load_zone(atm_id)
        except KeyError as exc:
            raise ZoneNotFoundError(str(exc)) from exc

    _emit(progress_cb, "frames", 0.1, "Sampling frames (fake)")
    _emit(progress_cb, "detect_persons", 0.4, "Detecting persons (fake)")
    _emit(progress_cb, "faces", 0.7, "Detecting faces (fake)")
    _emit(progress_cb, "save", 0.95, "Saving results (fake)")

    result = load_result(SAMPLE_RESULT_PATH)
    clip_id = Path(clip_path).stem or result.clip_id
    updates: dict[str, object] = {"clip_id": clip_id, "link_low_margin": False}
    if transaction_time is not None:
        updates["transaction_time"] = transaction_time

    _emit(progress_cb, "done", 1.0, "Done (fake)")
    return result.model_copy(update=updates)


def fake_enhance(
    image_path: str | Path,
    crop_box: list[int] | tuple[int, int, int, int],
    scale: int,
) -> Path:
    """Crop and Lanczos-upscale an image with Pillow, stamping 'ENHANCED' in pixels.

    Saves next to the original as <name>_enh_x<scale>.jpg without modifying the original.
    """
    src = Path(image_path)
    x, y, w, h = crop_box
    out_path = src.with_name(f"{src.stem}_enh_x{scale}.jpg")

    with Image.open(src) as img:
        cropped = img.convert("RGB").crop((x, y, x + w, y + h))
        upscaled = cropped.resize(
            (w * scale, h * scale),
            resample=Image.Resampling.LANCZOS,
        )
        # Burn visible ENHANCED label into pixels so enhanced crops are unmistakable.
        draw = ImageDraw.Draw(upscaled)
        draw.rectangle([(4, 4), (74, 20)], fill=(0, 0, 0))
        draw.text((8, 7), "ENHANCED", fill=(255, 255, 0))
        upscaled.save(out_path, format="JPEG")

    return out_path
