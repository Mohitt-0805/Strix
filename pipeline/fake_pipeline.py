"""Lightweight fake pipeline for teammates without ML libraries installed.

Uses only Python stdlib, Pydantic, and Pillow (no torch, no cv2).
"""

from pathlib import Path

from PIL import Image, ImageDraw

from pipeline.contract import PipelineResult, load_result


SAMPLE_RESULT_PATH = Path(__file__).resolve().parent.parent / "docs" / "sample_result.json"


def run(
    clip_path: str | Path,
    tx_offset_sec: float,
    window_sec: float = 10,
    atm_id: str = "",
    transaction_time: str | None = None,
    sample_fps: float = 2.0,
    tracker: str = "iou",
    out_dir: str | Path = "data/outputs",
) -> PipelineResult:
    """Return a validated PipelineResult from docs/sample_result.json.

    Accepts the same keyword arguments as pipeline.run_pipeline.run().
    """
    _ = (tx_offset_sec, window_sec, atm_id, sample_fps, tracker, out_dir)
    result = load_result(SAMPLE_RESULT_PATH)
    clip_id = Path(clip_path).stem or result.clip_id
    updates: dict[str, object] = {"clip_id": clip_id}
    if transaction_time is not None:
        updates["transaction_time"] = transaction_time
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
