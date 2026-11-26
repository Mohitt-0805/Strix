"""Face embedding extraction, similarity, and persistence helpers.

Heavy ML libraries (cv2, numpy, insightface) are imported inside functions only
so lightweight modules can import pipeline.embeddings without them.
"""

from pathlib import Path
from typing import Any


_MIN_CROP_SIDE = 112


def embed_crop(image_bgr: Any) -> Any | None:
    """Return a normalised 512-d float32 embedding for a face crop, or None."""
    import cv2
    import numpy as np
    from pipeline.faces import _extract_normed_embedding, get_face_app

    if image_bgr is None or getattr(image_bgr, "size", 0) == 0:
        return None

    h, w = image_bgr.shape[:2]
    if h < 2 or w < 2:
        return None

    img = image_bgr
    min_side = min(h, w)
    if min_side < _MIN_CROP_SIDE:
        scale = _MIN_CROP_SIDE / float(min_side)
        new_w = max(_MIN_CROP_SIDE, int(round(w * scale)))
        new_h = max(_MIN_CROP_SIDE, int(round(h * scale)))
        img = cv2.resize(image_bgr, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

    app = get_face_app()
    faces = app.get(img)
    if not faces:
        return None

    best = max(faces, key=lambda f: float(getattr(f, "det_score", 0.0) or 0.0))
    return _extract_normed_embedding(best, np)


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
