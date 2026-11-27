"""Evaluate CLIP zero-shot occluder flags on a labeled folder (cap/mask/helmet/none)."""

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.occluders import load_occluders_config, score_occluders_batch


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
FLAGS = ("cap", "mask", "helmet")


def main() -> int:
    import cv2

    parser = argparse.ArgumentParser(description="Evaluate occluder flags on cap/mask/helmet/none subfolders.")
    parser.add_argument("folder", type=Path, help="Folder containing cap/, mask/, helmet/, none/ subfolders")
    args = parser.parse_args()

    cfg = load_occluders_config()
    thresholds = {k: float(v) for k, v in cfg["thresholds"].items()}

    samples: list[tuple[str, str, object]] = []
    for sub in ("cap", "mask", "helmet", "none"):
        sub_dir = args.folder / sub
        if not sub_dir.is_dir():
            continue
        for p in sorted(sub_dir.iterdir()):
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
                img = cv2.imread(str(p))
                if img is not None:
                    samples.append((sub, f"{sub}/{p.name}", img))

    if not samples:
        print(f"No labeled images found under {args.folder}")
        return 1

    _, scores_list = score_occluders_batch([s[2] for s in samples], cfg=cfg)

    print(f"{'image':<32}  {'cap':>6}  {'mask':>6}  {'helmet':>6}")
    print("-" * 56)
    for (_, name, _), sc in zip(samples, scores_list):
        print(f"{name:<32}  {sc.get('cap', 0.0):>6.3f}  {sc.get('mask', 0.0):>6.3f}  {sc.get('helmet', 0.0):>6.3f}")

    print(f"\n{'flag':<8}  {'thresh':>6}  {'TP':>4}  {'FP':>4}  {'FN':>4}  {'prec':>6}  {'rec':>6}  {'best_F1_thresh(info)':>20}")
    print("-" * 70)
    for flag in FLAGS:
        th = thresholds[flag]
        tp = fp = fn = 0
        probs_labels: list[tuple[float, bool]] = []
        for (truth, _, _), sc in zip(samples, scores_list):
            p = float(sc.get(flag, 0.0))
            is_pos = truth == flag
            pred_pos = p >= th
            probs_labels.append((p, is_pos))
            if pred_pos and is_pos:
                tp += 1
            elif pred_pos and not is_pos:
                fp += 1
            elif not pred_pos and is_pos:
                fn += 1

        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0

        best_f1 = -1.0
        best_th = th
        for cand_i in range(50, 96, 5):
            cth = cand_i / 100.0
            ctp = sum(1 for p, pos in probs_labels if p >= cth and pos)
            cfp = sum(1 for p, pos in probs_labels if p >= cth and not pos)
            cfn = sum(1 for p, pos in probs_labels if p < cth and pos)
            denom = 2 * ctp + cfp + cfn
            f1 = (2 * ctp / denom) if denom > 0 else 0.0
            if f1 > best_f1:
                best_f1 = f1
                best_th = cth

        print(f"{flag:<8}  {th:>6.2f}  {tp:>4}  {fp:>4}  {fn:>4}  {prec:>6.3f}  {rec:>6.3f}  {best_th:>10.2f} (F1={best_f1:.2f})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
