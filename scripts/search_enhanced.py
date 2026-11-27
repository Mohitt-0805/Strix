"""CLI for search_with_enhancement() saving a visual comparison sheet."""

import argparse
from pathlib import Path
import sys

from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.compare import search_with_enhancement
from pipeline.contract import load_result
from pipeline.enhance import _expand_box_with_margin, enhance_frame


def _fit_crop(path: Path | None, size: int, placeholder: str) -> Image.Image:
    if path is None or not path.exists():
        img = Image.new("RGB", (size, size), color=(45, 45, 55))
        ImageDraw.Draw(img).text((8, size // 2 - 6), placeholder, fill=(220, 220, 220))
        return img
    with Image.open(path) as raw:
        rgb = raw.convert("RGB")
        rgb.thumbnail((size, size), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (size, size), color=(30, 30, 30))
        canvas.paste(rgb, ((size - rgb.width) // 2, (size - rgb.height) // 2))
        return canvas


def _save_search_visual(
    out_path: Path,
    orig_crop: Path | None,
    enh_crop: Path | None,
    matches: list[object],
) -> Path:
    cell = 140
    pad = 10
    label_h = 44
    n_cols = 2 + max(1, len(matches))
    sheet = Image.new("RGB", (n_cols * (cell + pad) + pad, cell + label_h + 2 * pad), color=(22, 22, 26))
    draw = ImageDraw.Draw(sheet)

    sheet.paste(_fit_crop(orig_crop, cell, "orig"), (pad, pad))
    draw.text((pad, pad + cell + 6), "QUERY (original)", fill=(255, 255, 120))

    enh_x = (cell + pad) + pad
    sheet.paste(_fit_crop(enh_crop, cell, "no enh"), (enh_x, pad))
    draw.text((enh_x, pad + cell + 6), "QUERY (enhanced)", fill=(255, 180, 120))

    for i, m in enumerate(matches):
        x0 = (i + 2) * (cell + pad) + pad
        cpath = Path(m.crop_path) if getattr(m, "crop_path", "") else None
        sheet.paste(_fit_crop(cpath, cell, f"tr {m.track_id}"), (x0, pad))
        sim_sec_str = f"{m.similarity_secondary:.2f}" if m.similarity_secondary is not None else "-"
        draw.text((x0, pad + cell + 4), f"tr={m.track_id} sim={m.similarity:.2f}", fill=(180, 240, 255))
        draw.text((x0, pad + cell + 18), f"enh={sim_sec_str} t={m.t:.1f}s", fill=(200, 200, 200))
        if getattr(m, "warning", None):
            draw.text((x0, pad + cell + 32), "WARN delta>0.15", fill=(255, 120, 120))

    sheet.save(out_path, format="JPEG", quality=92)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Search index using original crop and enhanced secondary check.")
    parser.add_argument("--index", type=Path, required=True, help="Index directory with index.npz")
    parser.add_argument("--original", type=Path, default=None, help="Original crop image path")
    parser.add_argument("--enhanced", type=Path, default=None, help="Enhanced crop image path")
    parser.add_argument("--result", type=Path, default=None, help="result.json path")
    parser.add_argument("--frame", type=str, default=None, help="frame_id inside result.json")
    parser.add_argument("--scale", type=int, default=4, choices=[2, 4], help="Scale when enhancing from result.json")
    parser.add_argument("--top", type=int, default=5, help="Top-K matches")
    parser.add_argument("--exclude-track", type=int, default=None, help="Optional track_id to exclude")
    args = parser.parse_args()

    orig_crop = args.original
    enh_crop = args.enhanced
    if args.result is not None:
        if not args.frame:
            parser.error("--frame is required with --result")
        res = load_result(args.result)
        fr = next((f for f in res.best_frames if str(f.frame_id) == str(args.frame)), None)
        if fr is None:
            print(f"Frame {args.frame!r} not found in {args.result}", file=sys.stderr)
            return 1
        orig_crop = Path(fr.crop_path) if fr.crop_path else None
        if enh_crop is None and fr.face_box is not None:
            box = _expand_box_with_margin(fr.face_box, margin=0.20)
            enh = enhance_frame(fr.frame_path, box, method="lanczos", scale=args.scale)
            enh_crop = Path(enh.enhanced_path)
    elif orig_crop is None and enh_crop is None:
        parser.error("Provide (--result and --frame) or --original.")

    sres = search_with_enhancement(
        index_dir=args.index,
        original_crop_path=orig_crop,
        enhanced_crop_path=enh_crop,
        exclude_track=args.exclude_track,
        top_k=args.top,
    )

    print(f"Basis: {sres.basis}")
    if sres.reliability_note:
        print(f"Reliability note: {sres.reliability_note}")
    if sres.top_level_warning:
        print(f"Warning: {sres.top_level_warning}")
    if sres.reason:
        print(f"Reason: {sres.reason}")

    print(f"\n{'rank':>4}  {'track':>5}  {'t':>7}  {'sim':>5}  {'enh_sim':>7}  {'delta':>6}  {'rel':>6}  {'ready':>5}  {'warning'}")
    print("-" * 82)
    for rank, m in enumerate(sres.matches, start=1):
        enh_s = f"{m.similarity_secondary:.2f}" if m.similarity_secondary is not None else "-"
        del_s = f"{m.delta:.2f}" if m.delta is not None else "-"
        warn_s = m.warning or "-"
        print(
            f"{rank:>4}  {m.track_id:>5}  {m.t:>7.2f}  {m.similarity:>5.2f}  {enh_s:>7}  "
            f"{del_s:>6}  {str(m.reliability or '-'):>6}  {str(m.match_ready):>5}  {warn_s}"
        )

    print(f"\n{sres.banner}")
    vis_path = _save_search_visual(args.index / "search_enhanced.jpg", orig_crop, enh_crop, sres.matches)
    print(f"Saved search visual: {vis_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
