"""Face embedding extraction, similarity, and persistence helpers.

Heavy ML libraries (cv2, numpy, insightface) are imported inside functions only
so lightweight modules can import pipeline.embeddings without them.
"""

from pathlib import Path
from typing import Any


_MIN_CROP_SIDE = 112


def _upscale_if_small(image_bgr: Any, min_side: int, cv2_mod: Any) -> Any:
    """Upscale image_bgr with INTER_CUBIC if its shorter side is below min_side."""
    h, w = image_bgr.shape[:2]
    cur_min = min(h, w)
    if cur_min >= min_side or cur_min <= 0:
        return image_bgr
    scale = float(min_side) / float(cur_min)
    new_w = max(min_side, int(round(w * scale)))
    new_h = max(min_side, int(round(h * scale)))
    return cv2_mod.resize(image_bgr, (new_w, new_h), interpolation=cv2_mod.INTER_CUBIC)


def embed_crop(
    image_bgr: Any,
    pad: float = 0.5,
    min_side: int = 160,
    info: bool = False,
) -> Any:
    """Return a normalised 512-d float32 embedding for a face crop, or None.

    If direct detection finds no face (common on tight crops), pads the crop with
    BORDER_REPLICATE, upscales so the shorter side >= min_side, and retries.
    When info=True, returns (vec_or_none, {"attempt": ..., "det_score": ...}).
    """
    import cv2
    import numpy as np
    from pipeline.faces import _extract_normed_embedding, get_face_app

    empty_meta = {"attempt": None, "det_score": None}
    if image_bgr is None or getattr(image_bgr, "size", 0) == 0:
        return (None, empty_meta) if info else None

    h, w = image_bgr.shape[:2]
    if h < 2 or w < 2:
        return (None, empty_meta) if info else None

    app = get_face_app()

    # Attempt 1: direct detection (with gentle upscale for tiny crops).
    direct_img = _upscale_if_small(image_bgr, _MIN_CROP_SIDE, cv2)
    faces = app.get(direct_img)
    if faces:
        best = max(faces, key=lambda f: float(getattr(f, "det_score", 0.0) or 0.0))
        vec = _extract_normed_embedding(best, np)
        meta = {"attempt": "direct", "det_score": float(getattr(best, "det_score", 0.0) or 0.0)}
        return (vec, meta) if info else vec

    # Attempt 2: replicate-pad for detector context, upscale to min_side, and retry.
    pad_y = max(1, int(round(h * pad)))
    pad_x = max(1, int(round(w * pad)))
    padded = cv2.copyMakeBorder(
        image_bgr,
        pad_y,
        pad_y,
        pad_x,
        pad_x,
        cv2.BORDER_REPLICATE,
    )
    padded = _upscale_if_small(padded, min_side, cv2)
    faces_padded = app.get(padded)
    if faces_padded:
        best = max(faces_padded, key=lambda f: float(getattr(f, "det_score", 0.0) or 0.0))
        vec = _extract_normed_embedding(best, np)
        meta = {"attempt": "padded", "det_score": float(getattr(best, "det_score", 0.0) or 0.0)}
        return (vec, meta) if info else vec

    return (None, empty_meta) if info else None


def embed_from_landmarks(image_bgr: Any, landmarks_5pts: Any) -> Any | None:
    """Align a face using 5 landmarks and run only the recognition model (no detection)."""
    import numpy as np
    from insightface.utils import face_align
    from pipeline.faces import get_face_app

    if image_bgr is None or getattr(image_bgr, "size", 0) == 0:
        return None
    pts = np.asarray(landmarks_5pts, dtype=np.float32)
    if pts.shape != (5, 2):
        raise ValueError(f"landmarks_5pts must have shape (5, 2), got {pts.shape}")

    app = get_face_app()
    rec_model = app.models.get("recognition")
    if rec_model is None:
        raise RuntimeError("InsightFace recognition model is not loaded")

    aligned = face_align.norm_crop(image_bgr, pts, image_size=112, mode="arcface")
    feat = rec_model.get_feat(aligned)[0]
    vec = np.asarray(feat, dtype=np.float32)
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm > 0.0 else vec


def cosine(a: Any, b: Any) -> float:
    """Compute cosine similarity between two 1-D embedding vectors."""
    import numpy as np

    va = np.asarray(a, dtype=np.float32).ravel()
    vb = np.asarray(b, dtype=np.float32).ravel()
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom == 0.0:
        return 0.0
    return float(np.dot(va, vb) / denom)


def save_embedding(path: str | Path, vec: Any) -> Path:
    """Save a 1-D float32 embedding to disk using numpy."""
    import numpy as np

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(str(out_path), np.asarray(vec, dtype=np.float32))
    return out_path


def load_embedding(path: str | Path) -> Any:
    """Load a float32 embedding from disk using numpy."""
    import numpy as np

    in_path = Path(path)
    return np.load(str(in_path)).astype(np.float32)
