"""Non-destructive face crop enhancement baseline (Lanczos + pixel banner).

Heavy libraries (cv2, numpy) are imported inside functions only so lightweight
modules can import pipeline.enhance without them.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Callable

from pipeline.contract import Enhancement, load_result


def _upscale_lanczos(crop_bgr: Any, scale: int) -> Any:
    """Upscale a BGR crop by scale using cv2.INTER_LANCZOS4."""
    import cv2

    h, w = crop_bgr.shape[:2]
    return cv2.resize(crop_bgr, (w * scale, h * scale), interpolation=cv2.INTER_LANCZOS4)


ENHANCE_METHODS: dict[str, tuple[Callable[[Any, int], Any], str]] = {
    "lanczos": (_upscale_lanczos, "lanczos_v1"),
}


def _burn_enhanced_banner(img_bgr: Any, scale: int) -> Any:
    """Draw a solid red top banner with 'ENHANCED x<scale>' sized to image width."""
    import cv2

    out = img_bgr.copy()
    h, w = out.shape[:2]
    label = f"ENHANCED x{scale}"

    # Size font relative to width so it stays legible on small and large crops.
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = max(0.35, min(1.2, w / 280.0))
    thickness = max(1, int(round(font_scale * 2.0)))
    (tw, th), baseline = cv2.getTextSize(label, font, font_scale, thickness)

    banner_h = min(h, th + baseline + max(8, int(round(h * 0.04))))
    cv2.rectangle(out, (0, 0), (w, banner_h), (0, 0, 220), thickness=-1)

    text_x = max(4, min(w - tw - 4, 6))
    text_y = max(th + 2, (banner_h + th) // 2 - 1)
    cv2.putText(out, label, (text_x, text_y), font, font_scale, (255, 255, 255), thickness, cv2.LINE_AA)
    return out


def _clip_crop_box(crop_box: list[int] | tuple[int, int, int, int], img_w: int, img_h: int) -> list[int]:
    """Clip [x, y, w, h] to image bounds and validate minimum 8 px side."""
    if len(crop_box) != 4:
        raise ValueError(f"crop_box must have 4 elements [x, y, w, h], got {crop_box}")
    x, y, w, h = [int(v) for v in crop_box]
    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(img_w, x + w)
    y2 = min(img_h, y + h)
    cw = x2 - x1
    ch = y2 - y1
    if cw < 8 or ch < 8:
        raise ValueError(f"Clipped crop_box [{x1}, {y1}, {cw}, {ch}] is empty or smaller than 8 px on a side")
    return [x1, y1, cw, ch]


def _cache_key(file_sha256: str, crop_box: list[int], method: str, scale: int) -> str:
    payload = f"{file_sha256}:{crop_box[0]},{crop_box[1]},{crop_box[2]},{crop_box[3]}:{method}:{scale}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def enhance_frame(
    frame_path: str | Path,
    crop_box: list[int] | tuple[int, int, int, int],
    method: str = "lanczos",
    scale: int = 4,
    out_dir: str | Path | None = None,
) -> Enhancement:
    """Crop [x, y, w, h], upscale by scale, burn ENHANCED label, and cache result."""
    if scale not in (2, 4):
        raise ValueError(f"scale must be 2 or 4, got {scale}")
    if method not in ENHANCE_METHODS:
        known = ", ".join(sorted(ENHANCE_METHODS.keys()))
        raise ValueError(f"Unknown enhancement method {method!r}. Known methods: {known}")

    src = Path(frame_path)
    if not src.exists():
        raise FileNotFoundError(f"Frame not found: {src}")

    import cv2

    raw_bytes = src.read_bytes()
    file_sha = hashlib.sha256(raw_bytes).hexdigest()

    img = cv2.imread(str(src))
    if img is None or img.size == 0:
        raise ValueError(f"Failed to read image: {src}")

    img_h, img_w = img.shape[:2]
    clipped = _clip_crop_box(crop_box, img_w, img_h)

    target_dir = Path(out_dir) if out_dir is not None else src.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    cache_path = target_dir / "enhance_cache.json"
    key = _cache_key(file_sha, clipped, method, scale)

    cache_data: dict[str, Any] = {}
    if cache_path.exists():
        try:
            cache_data = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            cache_data = {}

    if key in cache_data:
        cached_enh = Enhancement.model_validate(cache_data[key])
        if Path(cached_enh.enhanced_path).exists():
            return cached_enh

    x, y, cw, ch = clipped
    crop = img[y : y + ch, x : x + cw]
    upscale_fn, model_version = ENHANCE_METHODS[method]
    upscaled = upscale_fn(crop, scale)
    labeled = _burn_enhanced_banner(upscaled, scale)

    out_path = target_dir / f"{src.stem}_enh_x{scale}.jpg"
    cv2.imwrite(str(out_path), labeled, [int(cv2.IMWRITE_JPEG_QUALITY), 95])

    enh = Enhancement(
        enhanced_path=str(out_path),
        method=method,
        scale=scale,
        model_version=model_version,
        crop_box=clipped,
        search_embedding_source="original",
    )
    cache_data[key] = enh.model_dump()
    cache_path.write_text(json.dumps(cache_data, indent=2), encoding="utf-8")
    return enh


def _expand_box_with_margin(box_xywh: list[int], margin: float = 0.20) -> list[int]:
    x, y, w, h = [float(v) for v in box_xywh]
    dx = w * margin
    dy = h * margin
    return [
        int(round(x - dx)),
        int(round(y - dy)),
        int(round(w + 2.0 * dx)),
        int(round(h + 2.0 * dy)),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Enhance a face crop from an image or result.json.")
    parser.add_argument("--image", type=Path, default=None, help="Path to source frame/image")
    parser.add_argument("--box", type=int, nargs=4, metavar=("X", "Y", "W", "H"), default=None, help="Crop box")
    parser.add_argument("--result", type=Path, default=None, help="Path to result.json")
    parser.add_argument("--frame", type=str, default=None, help="frame_id inside result.json")
    parser.add_argument("--method", type=str, default="lanczos", help="Enhancement method")
    parser.add_argument("--scale", type=int, default=4, choices=[2, 4], help="Upscale factor (2 or 4)")
    parser.add_argument("--out-dir", type=Path, default=None, help="Optional output directory")
    args = parser.parse_args()

    if args.result is not None:
        if not args.frame:
            parser.error("--frame is required with --result")
        res = load_result(args.result)
        fr = next((f for f in res.best_frames if str(f.frame_id) == str(args.frame)), None)
        if fr is None:
            print(f"Frame {args.frame!r} not found in {args.result}", file=sys.stderr)
            return 1
        if fr.face_box is None:
            print(f"Frame {args.frame!r} has no face_box in {args.result}", file=sys.stderr)
            return 1
        box = _expand_box_with_margin(fr.face_box, margin=0.20)
        enh = enhance_frame(fr.frame_path, box, method=args.method, scale=args.scale, out_dir=args.out_dir)
    elif args.image is not None and args.box is not None:
        enh = enhance_frame(args.image, args.box, method=args.method, scale=args.scale, out_dir=args.out_dir)
    else:
        parser.error("Provide either (--image PATH --box X Y W H) or (--result PATH --frame FRAME_ID).")

    print(enh.enhanced_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
