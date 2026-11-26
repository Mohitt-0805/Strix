"""Print the cosine similarity matrix between face images in two folders."""

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.embeddings import cosine, embed_crop


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _load_folder_embeddings(folder: Path) -> list[tuple[str, object | None]]:
    import cv2

    paths = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
    results: list[tuple[str, object | None]] = []
    for p in paths:
        img = cv2.imread(str(p))
        emb = embed_crop(img) if img is not None else None
        results.append((p.name, emb))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute cosine similarity matrix between two image folders.")
    parser.add_argument("folder_a", type=Path, help="First folder of face images")
    parser.add_argument("folder_b", type=Path, help="Second folder of face images")
    args = parser.parse_args()

    emb_a = _load_folder_embeddings(args.folder_a)
    emb_b = _load_folder_embeddings(args.folder_b)
    if not emb_a or not emb_b:
        print("One or both folders contain no supported image files.")
        return 1

    col_w = max(10, max(len(name) for name, _ in emb_b) + 2)
    row_w = max(12, max(len(name) for name, _ in emb_a) + 2)

    header = " " * row_w + "".join(f"{name:>{col_w}}" for name, _ in emb_b)
    print(header)
    print("-" * len(header))

    for name_a, vec_a in emb_a:
        cells = []
        for _, vec_b in emb_b:
            if vec_a is None or vec_b is None:
                cells.append(f"{'N/A':>{col_w}}")
            else:
                cells.append(f"{cosine(vec_a, vec_b):>{col_w}.4f}")
        print(f"{name_a:<{row_w}}" + "".join(cells))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
