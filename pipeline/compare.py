"""Compare original vs. enhanced query embeddings for index search.

Heavy ML libraries (cv2, numpy, insightface, onnxruntime) are imported inside
functions only so lightweight modules can import pipeline.compare without them.
"""

import json
from pathlib import Path
from typing import Any

from pipeline.contract import SearchMatch, SearchResult


_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "compare.json"
_DISAGREEMENT_MSG = "Enhancement changed the result. Treat with caution."
_ENHANCED_BASIS_NOTE = "based on ENHANCED image, low reliability"
_BANNER_MSG = "Possible leads only. A person must verify."


def load_compare_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load comparison thresholds from pipeline/config/compare.json."""
    path = config_path or _CONFIG_PATH
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_vec(vec: Any, np_mod: Any) -> Any:
    arr = np_mod.asarray(vec, dtype=np_mod.float32).ravel()
    norm = float(np_mod.linalg.norm(arr))
    return arr / norm if norm > 0.0 else arr


def _embed_image_path(path: str | Path | None) -> Any | None:
    if path is None:
        return None
    p = Path(path)
    if not p.exists():
        return None
    import cv2
    from pipeline.embeddings import embed_crop

    img = cv2.imread(str(p))
    if img is None:
        return None
    return embed_crop(img)


def search_with_enhancement(
    index_dir: str | Path,
    original_crop_path: str | Path | None,
    enhanced_crop_path: str | Path | None = None,
    exclude_track: int | None = None,
    top_k: int | None = None,
    original_embedding: Any | None = None,
    enhanced_embedding: Any | None = None,
) -> SearchResult:
    """Search index_dir using original embedding primarily and enhanced as secondary."""
    import numpy as np

    cfg = load_compare_config()
    warn_thresh = float(cfg["disagreement_warn"])
    k = int(top_k if top_k is not None else cfg["top_k"])

    orig_vec = (
        _normalize_vec(original_embedding, np)
        if original_embedding is not None
        else _embed_image_path(original_crop_path)
    )
    enh_vec = (
        _normalize_vec(enhanced_embedding, np)
        if enhanced_embedding is not None
        else _embed_image_path(enhanced_crop_path)
    )

    if orig_vec is not None:
        basis = "original"
        basis_vec = _normalize_vec(orig_vec, np)
        sec_vec = _normalize_vec(enh_vec, np) if enh_vec is not None else None
        reliability_note = None
    elif enh_vec is not None:
        basis = "enhanced"
        basis_vec = _normalize_vec(enh_vec, np)
        sec_vec = None
        reliability_note = _ENHANCED_BASIS_NOTE
    else:
        return SearchResult(
            basis="none",
            banner=_BANNER_MSG,
            reliability_note=None,
            top_level_warning=None,
            reason="Could not extract face embedding from original or enhanced crop",
            matches=[],
        )

    idx_path = Path(index_dir)
    npz_path = idx_path / "index.npz"
    if not npz_path.exists():
        raise FileNotFoundError(f"index.npz not found in {idx_path}")

    npz = np.load(npz_path)
    embeddings = np.asarray(npz["embeddings"], dtype=np.float32)
    raw_meta = npz["metadata_json"].item()
    metadata = json.loads(raw_meta.decode("utf-8") if isinstance(raw_meta, bytes) else str(raw_meta))

    if embeddings.shape[0] == 0:
        return SearchResult(
            basis=basis,
            banner=_BANNER_MSG,
            reliability_note=reliability_note,
            top_level_warning=None,
            reason="Index contains 0 embeddings",
            matches=[],
        )

    sims_primary = (embeddings @ basis_vec).tolist()
    sims_secondary = (embeddings @ sec_vec).tolist() if sec_vec is not None else [None] * len(metadata)

    rows: list[tuple[float, float | None, dict[str, Any]]] = []
    for sim_p, sim_s, meta in zip(sims_primary, sims_secondary, metadata):
        if exclude_track is not None and int(meta["track_id"]) == int(exclude_track):
            continue
        rows.append((float(sim_p), float(sim_s) if sim_s is not None else None, meta))

    rows.sort(key=lambda item: item[0], reverse=True)
    top_rows = rows[: max(0, k)]

    matches: list[SearchMatch] = []
    any_warning = False
    for sim_p, sim_s, meta in top_rows:
        delta: float | None = None
        warning: str | None = None
        if sim_s is not None:
            delta = abs(sim_p - sim_s)
            if delta > warn_thresh:
                warning = _DISAGREEMENT_MSG
                any_warning = True

        matches.append(
            SearchMatch(
                track_id=int(meta["track_id"]),
                t=float(meta["t"]),
                similarity=sim_p,
                similarity_secondary=sim_s,
                delta=delta,
                warning=warning,
                crop_path=str(meta.get("crop_path", "")),
                reliability=meta.get("reliability"),
                match_ready=meta.get("match_ready"),
            )
        )

    return SearchResult(
        basis=basis,
        banner=_BANNER_MSG,
        reliability_note=reliability_note,
        top_level_warning=_DISAGREEMENT_MSG if any_warning else None,
        reason=None if matches else "No matching tracks after filtering",
        matches=matches,
    )
