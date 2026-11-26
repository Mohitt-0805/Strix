"""FastAPI dependencies for authentication, RBAC, and request metadata."""

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.app.db import get_db
from backend.app.errors import AppError
from backend.app.models import User
from backend.app.security import decode_access_token

_bearer_scheme = HTTPBearer(auto_error=False)


def get_app_settings(request: Request) -> Settings:
    """Return the Settings instance attached to app.state."""
    return request.app.state.settings


def get_client_ip(request: Request) -> str:
    """Return the connecting client IP address."""
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> User:
    """Validate Bearer JWT and return the active User row."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(
            status_code=401,
            code="UNAUTHORIZED",
            detail="Bearer authentication token required.",
        )

    payload = decode_access_token(credentials.credentials, settings)
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AppError(
            status_code=401,
            code="INVALID_TOKEN",
            detail="Invalid token subject.",
        ) from exc

    user = db.get(User, user_id)
    if user is None or not user.active:
        raise AppError(
            status_code=401,
            code="UNAUTHORIZED",
            detail="User account is missing or inactive.",
        )
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Require an authenticated user with the 'admin' role."""
    if current_user.role != "admin":
        raise AppError(
            status_code=403,
            code="FORBIDDEN",
            detail="Admin privileges required.",
        )
    return current_user
