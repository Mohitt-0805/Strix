"""Render a per-track contact sheet JPG for an indexed clip directory."""

import argparse
from pathlib import Path
import sys

from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.contract import IndexResult


def _fit_crop(path: Path, size: int) -> Image.Image:
    if not path.exists():
        img = Image.new("RGB", (size, size), color=(50, 50, 50))
        ImageDraw.Draw(img).text((8, size // 2 - 6), "missing", fill=(200, 100, 100))
        return img
    with Image.open(path) as raw:
        rgb = raw.convert("RGB")
        rgb.thumbnail((size, size), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (size, size), color=(30, 30, 30))
        canvas.paste(rgb, ((size - rgb.width) // 2, (size - rgb.height) // 2))
        return canvas


def build_index_sheet(index_dir: Path, crop_size: int = 128) -> Path:
    """Build index_sheet.jpg in index_dir with one row per track."""
    index_json = index_dir / "index.json"
    if not index_json.exists():
        raise FileNotFoundError(f"index.json not found in {index_dir}")

    idx_res = IndexResult.model_validate_json(index_json.read_text(encoding="utf-8"))
    left_w = 220
    label_h = 28
    row_h = max(crop_size + label_h + 12, 100)
    max_cols = max(1, max((len(tr.faces) for tr in idx_res.tracks), default=1))
    sheet_w = left_w + max_cols * (crop_size + 8) + 12
    sheet_h = max(1, len(idx_res.tracks)) * row_h

    sheet = Image.new("RGB", (sheet_w, sheet_h), color=(22, 22, 26))
    draw = ImageDraw.Draw(sheet)

    for r_idx, tr in enumerate(idx_res.tracks):
        y0 = r_idx * row_h
        draw.line([(0, y0), (sheet_w, y0)], fill=(55, 55, 65), width=1)

        draw.text((10, y0 + 10), f"Track {tr.track_id}", fill=(255, 255, 120))
        draw.text((10, y0 + 30), f"t: {tr.first_t:.2f} .. {tr.last_t:.2f}s", fill=(220, 220, 220))
        draw.text((10, y0 + 50), f"n_obs={tr.n_observations}", fill=(200, 200, 200))
        draw.text((10, y0 + 70), f"short_track={tr.short_track}", fill=(200, 200, 200))

        if not tr.faces:
            reason_txt = tr.reason or "No faces"
            draw.text((left_w + 12, y0 + row_h // 2 - 8), f"[{reason_txt}]", fill=(230, 140, 120))
            continue

        for c_idx, face in enumerate(tr.faces):
            x0 = left_w + c_idx * (crop_size + 8)
            thumb = _fit_crop(Path(face.crop_path), crop_size)
            sheet.paste(thumb, (x0, y0 + 6))
            draw.text((x0 + 2, y0 + crop_size + 10), f"t={face.t:.2f}s ({face.reliability})", fill=(180, 235, 255))

    out_path = index_dir / "index_sheet.jpg"
    sheet.save(out_path, format="JPEG", quality=92)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Create index_sheet.jpg for an index directory.")
    parser.add_argument("index_dir", type=Path, help="Directory containing index.json")
    args = parser.parse_args()

    out = build_index_sheet(args.index_dir)
    print(f"Saved index contact sheet: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
