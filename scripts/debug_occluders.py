"""Debug CLIP zero-shot occluder probabilities on an image or directory of crops."""

import argparse
from pathlib import Path
import sys

from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.occluders import load_occluders_config, score_occluders_batch


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def main() -> int:
    import cv2

    parser = argparse.ArgumentParser(description="Print occluder probabilities and save a contact sheet.")
    parser.add_argument("target", type=Path, help="Image file or directory of crop images")
    args = parser.parse_args()

    if args.target.is_file():
        paths = [args.target]
        out_dir = args.target.parent
    elif args.target.is_dir():
        paths = sorted(
            p for p in args.target.iterdir()
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS
            and p.name not in {"occluders_sheet.jpg", "contact_sheet.jpg"}
            and not p.name.startswith("frame_")
        )
        if not paths:
            paths = sorted(p for p in args.target.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
        out_dir = args.target
    else:
        print(f"Not found: {args.target}", file=sys.stderr)
        return 1

    crops = []
    valid_paths = []
    for p in paths:
        img = cv2.imread(str(p))
        if img is not None:
            crops.append(img)
            valid_paths.append(p)

    if not crops:
        print("No readable images found.")
        return 1

    cfg = load_occluders_config()
    flagged_list, scores_list = score_occluders_batch(crops, cfg=cfg)

    print(f"{'image':<28}  {'cap':>6}  {'mask':>6}  {'helmet':>6}  {'flags'}")
    print("-" * 68)
    for p, hits, sc in zip(valid_paths, flagged_list, scores_list):
        fl_str = ", ".join(h["flag"] for h in hits) if hits else "-"
        print(
            f"{p.name:<28}  {sc.get('cap', 0.0):>6.3f}  {sc.get('mask', 0.0):>6.3f}  "
            f"{sc.get('helmet', 0.0):>6.3f}  {fl_str}"
        )

    # Save contact sheet with flags under each image.
    cols = min(6, len(valid_paths))
    rows = (len(valid_paths) + cols - 1) // cols
    cell = 140
    label_h = 34
    sheet = Image.new("RGB", (cols * cell, rows * (cell + label_h)), color=(22, 22, 26))
    draw = ImageDraw.Draw(sheet)

    for idx, (p, hits, sc) in enumerate(zip(valid_paths, flagged_list, scores_list)):
        r, c = divmod(idx, cols)
        x0, y0 = c * cell, r * (cell + label_h)
        with Image.open(p) as raw:
            im = raw.convert("RGB")
            im.thumbnail((cell, cell), Image.Resampling.LANCZOS)
            sheet.paste(im, (x0 + (cell - im.width) // 2, y0 + (cell - im.height) // 2))
        fl_str = ",".join(h["flag"] for h in hits) if hits else "none"
        draw.text((x0 + 4, y0 + cell + 2), p.name[:18], fill=(220, 220, 220))
        draw.text((x0 + 4, y0 + cell + 16), f"flags: {fl_str}", fill=(255, 220, 120))

    sheet_path = out_dir / "occluders_sheet.jpg"
    sheet.save(sheet_path, format="JPEG", quality=92)
    print(f"\nSaved occluders sheet: {sheet_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
