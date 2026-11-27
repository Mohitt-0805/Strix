"""Print the cosine similarity matrix between two image folders or result.json files."""

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.contract import load_result
from pipeline.embeddings import cosine, embed_crop, load_embedding


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _load_source_embeddings(source: Path) -> tuple[list[tuple[str, object | None, str]], bool]:
    """Load embeddings from a result.json file or an image folder."""
    if source.is_file() and source.suffix.lower() == ".json":
        result = load_result(source)
        items: list[tuple[str, object | None, str]] = []
        for fr in result.best_frames:
            emb_path = Path(fr.embedding_path)
            vec = load_embedding(emb_path) if emb_path.exists() else None
            items.append((str(fr.frame_id), vec, "npy"))
        return items, False

    if not source.is_dir():
        raise FileNotFoundError(f"Expected image folder or result.json file: {source}")

    import cv2

    paths = sorted(p for p in source.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
    items = []
    for p in paths:
        img = cv2.imread(str(p))
        if img is None:
            items.append((p.name, None, "unreadable"))
            continue
        vec, meta = embed_crop(img, info=True)
        attempt = meta["attempt"] or "none"
        items.append((p.name, vec, attempt))
    return items, True


def _same_source_stats(items: list[tuple[str, object | None, str]]) -> tuple[float, float] | None:
    vecs = [vec for _, vec, _ in items if vec is not None]
    if len(vecs) < 2:
        return None
    sims = [cosine(vecs[i], vecs[j]) for i in range(len(vecs)) for j in range(i + 1, len(vecs))]
    return (sum(sims) / len(sims), min(sims))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute cosine similarity matrix between two image folders or result.json files."
    )
    parser.add_argument("source_a", type=Path, help="First image folder or result.json")
    parser.add_argument("source_b", type=Path, help="Second image folder or result.json")
    args = parser.parse_args()

    items_a, is_img_a = _load_source_embeddings(args.source_a)
    items_b, is_img_b = _load_source_embeddings(args.source_b)
    if not items_a or not items_b:
        print("One or both inputs contain no embeddings/images.")
        return 1

    if is_img_a:
        print(f"Attempts ({args.source_a}):")
        for name, _, attempt in items_a:
            print(f"  {name}: {attempt}")
    if is_img_b:
        print(f"Attempts ({args.source_b}):")
        for name, _, attempt in items_b:
            print(f"  {name}: {attempt}")
    if is_img_a or is_img_b:
        print()

    col_w = max(8, max(len(name) for name, _, _ in items_b) + 2)
    row_w = max(12, max(len(name) for name, _, _ in items_a) + 2)

    header = " " * row_w + "".join(f"{name:>{col_w}}" for name, _, _ in items_b)
    print(header)
    print("-" * len(header))

    cross_sims: list[float] = []
    for name_a, vec_a, _ in items_a:
        cells = []
        for _, vec_b, _ in items_b:
            if vec_a is None or vec_b is None:
                cells.append(f"{'N/A':>{col_w}}")
            else:
                sim = cosine(vec_a, vec_b)
                cross_sims.append(sim)
                cells.append(f"{sim:>{col_w}.2f}")
        print(f"{name_a:<{row_w}}" + "".join(cells))

    print()
    stats_a = _same_source_stats(items_a)
    stats_b = _same_source_stats(items_b)
    if stats_a is not None:
        print(f"Same-folder A ({args.source_a.name}): mean={stats_a[0]:.2f}, min={stats_a[1]:.2f}")
    if stats_b is not None:
        print(f"Same-folder B ({args.source_b.name}): mean={stats_b[0]:.2f}, min={stats_b[1]:.2f}")
    if cross_sims:
        print(f"Cross-folder (A vs B): mean={sum(cross_sims) / len(cross_sims):.2f}, max={max(cross_sims):.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
