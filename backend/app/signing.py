"""HMAC-SHA256 signed URL creation and constant-time verification for /files."""

import hashlib
import hmac
import time
from urllib.parse import urlencode

from backend.app.config import Settings
from backend.app.errors import AppError


def compute_file_signature(rel_path: str, uid: int, exp: int, secret: str) -> str:
    """Compute HMAC-SHA256 hex digest over 'p|uid|exp' using JWT_SECRET."""
    message = f"{rel_path}|{uid}|{exp}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def make_signed_file_url(
    rel_path: str,
    user_id: int,
    settings: Settings,
    *,
    download: bool = False,
) -> str:
    """Build a signed /files URL for images or videos without requiring Auth headers."""
    exp = int(time.time()) + settings.signed_url_ttl_sec
    sig = compute_file_signature(rel_path, user_id, exp, settings.jwt_secret)
    params: dict[str, object] = {
        "p": rel_path,
        "uid": user_id,
        "exp": exp,
        "sig": sig,
    }
    if download:
        params["download"] = 1
    return f"/files?{urlencode(params)}"


def verify_signed_file_params(
    rel_path: str,
    uid: int,
    exp: int,
    sig: str,
    settings: Settings,
    *,
    now: int | None = None,
) -> None:
    """Validate expiration and HMAC signature in constant time, raising 403 on failure."""
    current_ts = int(time.time()) if now is None else now
    if exp < current_ts:
        raise AppError(
            status_code=403,
            code="SIGNED_URL_EXPIRED",
            detail="Signed file URL has expired.",
        )

    expected = compute_file_signature(rel_path, uid, exp, settings.jwt_secret)
    if not hmac.compare_digest(expected, sig):
        raise AppError(
            status_code=403,
            code="INVALID_SIGNATURE",
            detail="Invalid signed file URL signature.",
        )
