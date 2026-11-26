"""In-memory similarity search index (FAISS IndexFlatIP with NumPy fallback)."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Literal

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import Clip, FrameRecord, Run
from backend.app.services.storage import from_rel

logger = logging.getLogger(__name__)


def _try_import_faiss() -> Any | None:
    """Attempt to import faiss; return module or None if unavailable."""
    try:
        import faiss  # type: ignore[import-not-found]

        return faiss
    except Exception as exc:
        logger.info("faiss not available (%s); using numpy search fallback.", exc)
        return None


def validate_and_normalize_vector(
    arr: np.ndarray,
    embed_dim: int,
    *,
    label: str = "vector",
) -> np.ndarray | None:
    """Validate 1D embed_dim float32 vector (finite, non-zero) and L2-normalise."""
    vec = np.asarray(arr, dtype=np.float32)
    if vec.ndim == 2 and vec.shape[0] == 1:
        vec = vec[0]
    if vec.ndim != 1 or vec.shape[0] != embed_dim:
        logger.warning(
            "Skipping %s: expected shape (%d,), got %s.",
            label,
            embed_dim,
            vec.shape,
        )
        return None
    if not np.all(np.isfinite(vec)):
        logger.warning("Skipping %s: contains NaN or Inf values.", label)
        return None
    norm = float(np.linalg.norm(vec))
    if norm <= 1e-12:
        logger.warning("Skipping %s: zero-norm embedding.", label)
        return None
    return (vec / norm).astype(np.float32)


def load_and_normalize_embedding(path: Path, embed_dim: int) -> np.ndarray | None:
    """Load an .npy embedding from disk, validate dimension/finiteness, and L2-normalise."""
    if not path.is_file():
        logger.warning("Skipping missing embedding file: %s", path)
        return None
    try:
        arr = np.load(path, allow_pickle=False)
    except Exception as exc:
        logger.warning("Skipping unreadable embedding %s: %s", path, exc)
        return None
    return validate_and_normalize_vector(arr, embed_dim, label=str(path))


@dataclass(frozen=True)
class IndexItem:
    """Single indexed frame embedding and associated metadata."""

    clip_id: str
    filename: str
    run_id: int
    frame_id: str
    timestamp_sec: float
    reliability: str
    flags: tuple[str, ...]
    frame_path_rel: str
    crop_path_rel: str | None
    vector: np.ndarray


@dataclass(frozen=True)
class SearchHit:
    """Ranked match returned by SearchIndex.search()."""

    clip_id: str
    filename: str
    run_id: int
    frame_id: str
    timestamp_sec: float
    score: float
    reliability: str
    flags: list[str]
    frame_path_rel: str
    crop_path_rel: str | None


class SearchIndex:
    """Thread-safe in-memory inner-product index with FAISS and NumPy backends."""

    def __init__(
        self,
        embed_dim: int = 512,
        backend: Literal["auto", "faiss", "numpy"] = "auto",
    ) -> None:
        self.embed_dim = embed_dim
        self._lock = RLock()
        self._items: list[IndexItem] = []
        self._matrix: np.ndarray = np.empty((0, embed_dim), dtype=np.float32)
        self._faiss_mod = None
        self._faiss_index = None

        if backend == "faiss":
            self._faiss_mod = _try_import_faiss()
            if self._faiss_mod is None:
                raise RuntimeError("faiss backend requested but faiss is not available.")
        elif backend == "auto":
            self._faiss_mod = _try_import_faiss()

    @property
    def backend_name(self) -> str:
        """Return 'faiss' when FAISS IndexFlatIP is active, else 'numpy'."""
        return "faiss" if self._faiss_mod is not None else "numpy"

    def _rebuild_structures(self) -> None:
        """Rebuild dense matrix and optional FAISS IndexFlatIP from self._items."""
        if not self._items:
            self._matrix = np.empty((0, self.embed_dim), dtype=np.float32)
            self._faiss_index = None
            return

        self._matrix = np.ascontiguousarray(
            np.vstack([item.vector for item in self._items]),
            dtype=np.float32,
        )
        if self._faiss_mod is not None:
            index = self._faiss_mod.IndexFlatIP(self.embed_dim)
            index.add(self._matrix)
            self._faiss_index = index
        else:
            self._faiss_index = None

    def count(self) -> int:
        """Return number of valid vectors currently indexed."""
        with self._lock:
            return len(self._items)

    def add(self, items: Sequence[IndexItem]) -> int:
        """Validate, normalise, and add items to the index; return count added."""
        accepted: list[IndexItem] = []
        for item in items:
            normed = validate_and_normalize_vector(
                item.vector,
                self.embed_dim,
                label=f"run={item.run_id}/frame={item.frame_id}",
            )
            if normed is None:
                continue
            accepted.append(
                IndexItem(
                    clip_id=item.clip_id,
                    filename=item.filename,
                    run_id=item.run_id,
                    frame_id=str(item.frame_id),
                    timestamp_sec=item.timestamp_sec,
                    reliability=item.reliability,
                    flags=tuple(item.flags),
                    frame_path_rel=item.frame_path_rel,
                    crop_path_rel=item.crop_path_rel,
                    vector=normed,
                )
            )

        if not accepted:
            return 0

        with self._lock:
            self._items.extend(accepted)
            self._rebuild_structures()
        return len(accepted)

    def remove_run(self, run_id: int) -> int:
        """Remove all vectors belonging to run_id and return how many were removed."""
        with self._lock:
            before = len(self._items)
            self._items = [item for item in self._items if item.run_id != run_id]
            removed = before - len(self._items)
            if removed > 0:
                self._rebuild_structures()
            return removed

    def search(
        self,
        vec: np.ndarray,
        top_k: int,
        exclude_clip_id: str | None = None,
    ) -> list[SearchHit]:
        """Return top_k matches from OTHER clips sorted descending by cosine score."""
        if top_k <= 0:
            return []

        query = validate_and_normalize_vector(vec, self.embed_dim, label="query")
        if query is None:
            raise ValueError("Query embedding is invalid (wrong dimension, NaN, or zero).")

        with self._lock:
            if not self._items:
                return []

            if self._faiss_index is not None:
                q2d = np.ascontiguousarray(query.reshape(1, -1), dtype=np.float32)
                scores_arr, idxs_arr = self._faiss_index.search(q2d, len(self._items))
                scored_pairs = [
                    (int(idx), float(score))
                    for idx, score in zip(idxs_arr[0], scores_arr[0])
                    if idx >= 0
                ]
            else:
                sims = self._matrix @ query
                order = np.argsort(-sims, kind="mergesort")
                scored_pairs = [(int(idx), float(sims[idx])) for idx in order]

            hits: list[SearchHit] = []
            for idx, score in scored_pairs:
                item = self._items[idx]
                if exclude_clip_id is not None and item.clip_id == exclude_clip_id:
                    continue
                hits.append(
                    SearchHit(
                        clip_id=item.clip_id,
                        filename=item.filename,
                        run_id=item.run_id,
                        frame_id=item.frame_id,
                        timestamp_sec=item.timestamp_sec,
                        score=round(score, 6),
                        reliability=item.reliability,
                        flags=list(item.flags),
                        frame_path_rel=item.frame_path_rel,
                        crop_path_rel=item.crop_path_rel,
                    )
                )
                if len(hits) >= top_k:
                    break
            return hits

    def rebuild_from_db(self, db: Session, data_dir: Path) -> int:
        """Clear and rebuild the index from all completed runs in SQLite."""
        rows = db.execute(
            select(FrameRecord, Run, Clip)
            .join(Run, FrameRecord.run_id == Run.id)
            .join(Clip, Run.clip_id == Clip.id)
            .where(Run.status == "done")
            .order_by(Run.id.asc(), FrameRecord.id.asc())
        ).all()

        loaded_items: list[IndexItem] = []
        for frame_row, run_row, clip_row in rows:
            try:
                emb_path = from_rel(
                    frame_row.embedding_path_rel,
                    data_dir,
                    allowed_roots=("outputs",),
                )
            except Exception as exc:
                logger.warning(
                    "Skipping invalid embedding path '%s' (run=%s, frame=%s): %s",
                    frame_row.embedding_path_rel,
                    run_row.id,
                    frame_row.frame_id,
                    exc,
                )
                continue

            vec = load_and_normalize_embedding(emb_path, self.embed_dim)
            if vec is None:
                continue

            loaded_items.append(
                IndexItem(
                    clip_id=clip_row.id,
                    filename=clip_row.original_filename,
                    run_id=run_row.id,
                    frame_id=str(frame_row.frame_id),
                    timestamp_sec=frame_row.timestamp_sec,
                    reliability=frame_row.reliability,
                    flags=tuple(frame_row.flags or []),
                    frame_path_rel=frame_row.frame_path_rel,
                    crop_path_rel=frame_row.crop_path_rel,
                    vector=vec,
                )
            )

        with self._lock:
            self._items = loaded_items
            self._rebuild_structures()
            return len(self._items)
