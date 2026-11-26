"""Password hashing (direct bcrypt), JWT handling, and login throttling."""

import time
from collections import deque
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any

import bcrypt
import jwt

from backend.app.config import Settings
from backend.app.errors import AppError

JWT_ALGORITHM = "HS256"
MAX_FAILED_LOGINS = 5
THROTTLE_WINDOW_SEC = 300.0


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt directly."""
    pw_bytes = password.encode("utf-8")
    if len(pw_bytes) > 72:
        raise AppError(
            status_code=422,
            code="PASSWORD_TOO_LONG",
            detail="Password must be at most 72 bytes.",
        )
    hashed = bcrypt.hashpw(pw_bytes, bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash."""
    pw_bytes = password.encode("utf-8")
    if len(pw_bytes) > 72:
        return False
    try:
        return bcrypt.checkpw(pw_bytes, password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(
    user_id: int,
    username: str,
    role: str,
    settings: Settings,
) -> str:
    """Sign a short-lived HS256 JWT carrying user id, username, and role."""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=settings.jwt_expire_min)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "iat": now,
        "exp": exp,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str, settings: Settings) -> dict[str, Any]:
    """Decode and validate an HS256 JWT, raising 401 on any failure."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "exp", "role"]},
        )
    except jwt.PyJWTError as exc:
        raise AppError(
            status_code=401,
            code="INVALID_TOKEN",
            detail="Invalid or expired authentication token.",
        ) from exc
    return payload


class LoginThrottle:
    """In-memory sliding-window throttle keyed by (username, ip)."""

    def __init__(
        self,
        max_attempts: int = MAX_FAILED_LOGINS,
        window_sec: float = THROTTLE_WINDOW_SEC,
    ) -> None:
        self.max_attempts = max_attempts
        self.window_sec = window_sec
        self._attempts: dict[tuple[str, str], deque[float]] = {}
        self._lock = Lock()

    def _prune(self, bucket: deque[float], now: float) -> None:
        cutoff = now - self.window_sec
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

    def check(self, username: str, ip: str) -> None:
        """Raise 429 if failed attempts in the window reached max_attempts."""
        key = (username, ip)
        now = time.monotonic()
        with self._lock:
            bucket = self._attempts.get(key)
            if bucket is None:
                return
            self._prune(bucket, now)
            if len(bucket) >= self.max_attempts:
                raise AppError(
                    status_code=429,
                    code="TOO_MANY_LOGIN_ATTEMPTS",
                    detail="Too many failed login attempts. Try again in 5 minutes.",
                )

    def record_failure(self, username: str, ip: str) -> None:
        """Record a failed login timestamp for (username, ip)."""
        key = (username, ip)
        now = time.monotonic()
        with self._lock:
            bucket = self._attempts.setdefault(key, deque())
            self._prune(bucket, now)
            bucket.append(now)

    def reset(self, username: str, ip: str) -> None:
        """Clear failed login history after a successful login."""
        with self._lock:
            self._attempts.pop((username, ip), None)
