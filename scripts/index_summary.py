"""Print an index summary table and optional max cosine similarities vs result.json files."""

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.contract import IndexResult, load_result
from pipeline.embeddings import cosine, load_embedding


_REL_ORDER = {"High": 2, "Medium": 1, "Low": 0}


def _best_reliability(faces: list[object]) -> str:
    if not faces:
        return "-"
    best = max(faces, key=lambda f: _REL_ORDER.get(getattr(f, "reliability", "Low"), 0))
    return str(getattr(best, "reliability", "-"))


def summarize_index(index_dir: Path, compare_paths: list[Path] | None = None) -> str:
    """Build a formatted summary table for an index directory and optional compare results."""
    index_json = index_dir / "index.json"
    if not index_json.exists():
        raise FileNotFoundError(f"index.json not found in {index_dir}")

    idx_res = IndexResult.model_validate_json(index_json.read_text(encoding="utf-8"))

    # Load compare result embeddings.
    compare_entries: list[tuple[str, list[object]]] = []
    for cpath in compare_paths or []:
        res = load_result(cpath)
        label = f"{cpath.parent.name}"
        vecs = []
        for fr in res.best_frames:
            ep = Path(fr.embedding_path)
            if ep.exists():
                vecs.append(load_embedding(ep))
        compare_entries.append((label, vecs))

    # Preload per-track embeddings.
    track_vecs: dict[int, list[object]] = {}
    for tr in idx_res.tracks:
        vecs = []
        for f in tr.faces:
            ep = Path(f.embedding_path)
            if ep.exists():
                vecs.append(load_embedding(ep))
        track_vecs[tr.track_id] = vecs

    cmp_headers = "".join(f"  {lbl:>16}" for lbl, _ in compare_entries)
    header = (
        f"{'track_id':>8}  {'first_t':>7}  {'last_t':>7}  {'n_obs':>5}  "
        f"{'faces':>5}  {'best_rel':>8}  {'ready':>5}  {'reason':<20}{cmp_headers}"
    )
    lines = [
        f"Index: {idx_res.clip_id} [{idx_res.start_sec:.2f}, {idx_res.end_sec:.2f}]s | "
        f"tracks={len(idx_res.tracks)} | total_embeddings={idx_res.total_embeddings}",
        header,
        "-" * len(header),
    ]

    for tr in idx_res.tracks:
        best_rel = _best_reliability(tr.faces)
        ready_cnt = sum(1 for f in tr.faces if f.match_ready)
        reason_str = tr.reason or ("short_track" if tr.short_track else "-")

        cmp_cells = ""
        t_vecs = track_vecs.get(tr.track_id, [])
        for _, c_vecs in compare_entries:
            if not t_vecs or not c_vecs:
                cmp_cells += f"  {'-':>16}"
            else:
                max_sim = max(cosine(tv, cv) for tv in t_vecs for cv in c_vecs)
                cmp_cells += f"  {max_sim:>16.2f}"

        lines.append(
            f"{tr.track_id:>8}  {tr.first_t:>7.2f}  {tr.last_t:>7.2f}  {tr.n_observations:>5}  "
            f"{len(tr.faces):>5}  {best_rel:>8}  {ready_cnt:>5}  {reason_str:<20}{cmp_cells}"
        )

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize an index directory and compare with result.json files.")
    parser.add_argument("index_dir", type=Path, help="Directory containing index.json and index.npz")
    parser.add_argument("--compare", type=Path, nargs="*", default=[], help="result.json paths to compare against")
    args = parser.parse_args()

    print(summarize_index(args.index_dir, args.compare))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
