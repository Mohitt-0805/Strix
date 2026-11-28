"""Safe DATA_DIR-relative path normalization, validation, and filename sanitization."""

import re
from pathlib import Path, PurePosixPath

from backend.app.errors import AppError

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _resolve_inside(candidate: Path, data_root: Path) -> str | None:
    """Return forward-slash relative path if candidate resolves inside data_root."""
    resolved = candidate.resolve()
    if resolved == data_root or not resolved.is_relative_to(data_root):
        return None
    return resolved.relative_to(data_root).as_posix()


def to_rel(path: str | Path, data_dir: Path) -> str:
    """Normalize a path to a forward-slash path relative to DATA_DIR.

    Tries: (1) path as given if absolute, (2) relative to CWD, (3) relative to
    DATA_DIR, and (4) with a leading 'data/' prefix stripped. Prefers existing
    files inside DATA_DIR, then paths that resolve inside DATA_DIR.
    Raises AppError if the path resolves outside DATA_DIR.
    """
    raw = str(path).strip().replace("\\", "/")
    if not raw:
        raise AppError(status_code=400, code="INVALID_PATH", detail="Empty path.")

    data_root = data_dir.resolve()
    p = Path(raw)

    if p.is_absolute():
        rel = _resolve_inside(p, data_root)
        if rel is not None:
            return rel
        raise AppError(
            status_code=403,
            code="INVALID_PATH",
            detail="Path lies outside DATA_DIR.",
        )

    if ".." in p.parts:
        raise AppError(
            status_code=403,
            code="INVALID_PATH",
            detail="Path traversal ('..') is not allowed.",
        )

    candidates: list[Path] = [Path.cwd() / p]
    if raw.startswith("data/"):
        # Strip leading 'data/' when fake/real pipeline outputs use 'data/outputs/...'.
        stripped = raw[len("data/") :]
        if stripped:
            candidates.append(data_root / stripped)
    candidates.append(data_root / p)

    # First pass: prefer an existing file/directory inside DATA_DIR.
    for cand in candidates:
        rel = _resolve_inside(cand, data_root)
        if rel is not None and cand.exists():
            return rel

    # Second pass: accept a non-existent path (e.g. fake mode) inside DATA_DIR.
    for cand in candidates:
        rel = _resolve_inside(cand, data_root)
        if rel is not None:
            return rel

    raise AppError(
        status_code=403,
        code="INVALID_PATH",
        detail="Path lies outside DATA_DIR.",
    )


def from_rel(
    rel_path: str | Path,
    data_dir: Path,
    *,
    allowed_roots: tuple[str, ...] | None = None,
) -> Path:
    """Resolve a stored DATA_DIR-relative path safely, rejecting escapes."""
    raw = str(rel_path).strip().replace("\\", "/")
    if not raw:
        raise AppError(status_code=403, code="INVALID_PATH", detail="Empty path.")

    posix = PurePosixPath(raw)
    if posix.is_absolute() or raw.startswith("/"):
        raise AppError(
            status_code=403,
            code="INVALID_PATH",
            detail="Absolute paths are not allowed.",
        )
    if ".." in posix.parts:
        raise AppError(
            status_code=403,
            code="INVALID_PATH",
            detail="Path traversal ('..') is not allowed.",
        )

    data_root = data_dir.resolve()
    resolved = (data_root / raw).resolve()
    if resolved == data_root or not resolved.is_relative_to(data_root):
        raise AppError(
            status_code=403,
            code="INVALID_PATH",
            detail="Resolved path escapes DATA_DIR.",
        )

    if allowed_roots is not None:
        rel_parts = resolved.relative_to(data_root).parts
        if not rel_parts or rel_parts[0] not in allowed_roots:
            raise AppError(
                status_code=403,
                code="INVALID_PATH",
                detail="Path is outside allowed storage directories.",
            )

    return resolved


def sanitize_filename(filename: str | None, fallback: str = "clip.mp4") -> str:
    """Strip directory parts and restrict filename characters safely."""
    if not filename:
        return fallback
    leaf = Path(filename.replace("\\", "/")).name.strip()
    if not leaf or leaf in {".", ".."}:
        return fallback
    stem = Path(leaf).stem
    suffix = Path(leaf).suffix.lower()
    safe_stem = _SAFE_NAME_RE.sub("_", stem).strip("._") or "clip"
    safe_suffix = _SAFE_NAME_RE.sub("", suffix)[:16]
    max_stem = max(1, 120 - len(safe_suffix))
    return f"{safe_stem[:max_stem]}{safe_suffix}"
