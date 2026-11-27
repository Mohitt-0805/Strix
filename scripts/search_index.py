"""Search an index.npz/index.json using a query embedding from result.json or .npy."""

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.contract import IndexResult, load_result
from pipeline.embeddings import load_embedding


def _fit_crop(path: Path | None, size: int, placeholder_text: str = "query") -> Image.Image:
    if path is None or not path.exists():
        img = Image.new("RGB", (size, size), color=(45, 45, 55))
        ImageDraw.Draw(img).text((8, size // 2 - 6), placeholder_text, fill=(220, 220, 220))
        return img
    with Image.open(path) as raw:
        rgb = raw.convert("RGB")
        rgb.thumbnail((size, size), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (size, size), color=(30, 30, 30))
        canvas.paste(rgb, ((size - rgb.width) // 2, (size - rgb.height) // 2))
        return canvas


def _load_query(
    result_path: Path | None,
    frame_id: str | None,
    embedding_path: Path | None,
) -> tuple[Any, Path | None, str]:
    import numpy as np

    if embedding_path is not None:
        vec = np.asarray(load_embedding(embedding_path), dtype=np.float32).ravel()
        norm = float(np.linalg.norm(vec))
        return (vec / norm if norm > 0.0 else vec), None, embedding_path.name

    assert result_path is not None and frame_id is not None
    res = load_result(result_path)
    match_fr = next((fr for fr in res.best_frames if str(fr.frame_id) == str(frame_id)), None)
    if match_fr is None:
        raise KeyError(f"Frame ID {frame_id!r} not found in {result_path}")
    vec = np.asarray(load_embedding(Path(match_fr.embedding_path)), dtype=np.float32).ravel()
    norm = float(np.linalg.norm(vec))
    crop_p = Path(match_fr.crop_path) if match_fr.crop_path else None
    return (vec / norm if norm > 0.0 else vec), crop_p, f"{res.clip_id}:{frame_id}"


def search_index(
    index_dir: Path,
    query_vec: Any,
    top_k: int = 5,
    exclude_track: int | None = None,
    query_crop_path: Path | None = None,
    query_label: str = "query",
) -> tuple[list[dict[str, Any]], Path]:
    """Search index.npz by dot product and save search_results.jpg."""
    import numpy as np

    npz_path = index_dir / "index.npz"
    json_path = index_dir / "index.json"
    if not npz_path.exists() or not json_path.exists():
        raise FileNotFoundError(f"index.npz or index.json missing in {index_dir}")

    _ = IndexResult.model_validate_json(json_path.read_text(encoding="utf-8"))
    npz = np.load(npz_path)
    embeddings = np.asarray(npz["embeddings"], dtype=np.float32)
    raw_meta = npz["metadata_json"].item()
    metadata = json.loads(raw_meta.decode("utf-8") if isinstance(raw_meta, bytes) else str(raw_meta))

    q = np.asarray(query_vec, dtype=np.float32).ravel()
    q_norm = float(np.linalg.norm(q))
    if q_norm > 0.0:
        q = q / q_norm

    sims = embeddings @ q if embeddings.shape[0] > 0 else np.zeros((0,), dtype=np.float32)

    candidates: list[dict[str, Any]] = []
    for sim, meta in zip(sims.tolist(), metadata):
        if exclude_track is not None and int(meta["track_id"]) == int(exclude_track):
            continue
        row = dict(meta)
        row["similarity"] = float(sim)
        candidates.append(row)

    candidates.sort(key=lambda r: r["similarity"], reverse=True)
    top_matches = candidates[: max(0, int(top_k))]

    # Render search_results.jpg: query crop on left, matched crops in a row.
    cell = 136
    pad = 10
    label_h = 34
    n_cols = 1 + max(1, len(top_matches))
    sheet = Image.new("RGB", (n_cols * (cell + pad) + pad, cell + label_h + 2 * pad), color=(22, 22, 26))
    draw = ImageDraw.Draw(sheet)

    q_img = _fit_crop(query_crop_path, cell, placeholder_text="query")
    sheet.paste(q_img, (pad, pad))
    draw.text((pad, pad + cell + 6), f"QUERY ({query_label[:16]})", fill=(255, 255, 120))

    for i, m in enumerate(top_matches):
        x0 = (i + 1) * (cell + pad) + pad
        c_img = _fit_crop(Path(m["crop_path"]), cell, placeholder_text=f"tr {m['track_id']}")
        sheet.paste(c_img, (x0, pad))
        draw.text((x0, pad + cell + 4), f"tr={m['track_id']} sim={m['similarity']:.2f}", fill=(180, 240, 255))
        draw.text((x0, pad + cell + 18), f"t={m['t']:.2f}s", fill=(200, 200, 200))

    out_img = index_dir / "search_results.jpg"
    sheet.save(out_img, format="JPEG", quality=92)
    return top_matches, out_img


def main() -> int:
    parser = argparse.ArgumentParser(description="Search an indexed clip for similar face embeddings.")
    parser.add_argument("--index", type=Path, required=True, help="Index directory with index.npz and index.json")
    parser.add_argument("--result", type=Path, default=None, help="Path to result.json for query")
    parser.add_argument("--frame", type=str, default=None, help="frame_id inside result.json")
    parser.add_argument("--embedding", type=Path, default=None, help="Direct .npy embedding path for query")
    parser.add_argument("--top", type=int, default=5, help="Number of top matches to return")
    parser.add_argument("--exclude-track", type=int, default=None, help="Optional track_id to exclude")
    args = parser.parse_args()

    if args.embedding is None and (args.result is None or args.frame is None):
        parser.error("Provide either --embedding NPY_FILE or both --result RESULT_JSON and --frame FRAME_ID.")

    q_vec, q_crop, q_label = _load_query(args.result, args.frame, args.embedding)
    matches, out_img = search_index(
        index_dir=args.index,
        query_vec=q_vec,
        top_k=args.top,
        exclude_track=args.exclude_track,
        query_crop_path=q_crop,
        query_label=q_label,
    )

    print(f"\n{'rank':>4}  {'track_id':>8}  {'t':>7}  {'sim':>5}  {'rel':>6}  {'ready':>5}  {'crop_path'}")
    print("-" * 80)
    for rank, m in enumerate(matches, start=1):
        print(
            f"{rank:>4}  {m['track_id']:>8}  {m['t']:>7.2f}  {m['similarity']:>5.2f}  "
            f"{m['reliability']:>6}  {str(m['match_ready']):>5}  {m['crop_path']}"
        )
    print("\nPossible leads only. A person must verify.")
    print(f"Saved search visual: {out_img}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
