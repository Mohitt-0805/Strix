"""Authentication endpoints: login and current user profile."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.audit import record_audit
from backend.app.config import Settings
from backend.app.db import get_db
from backend.app.deps import get_app_settings, get_client_ip, get_current_user
from backend.app.errors import AppError
from backend.app.models import User
from backend.app.schemas import LoginRequest, LoginResponse, UserOut
from backend.app.security import LoginThrottle, create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> LoginResponse:
    """Authenticate a user and issue a signed Bearer JWT."""
    username = payload.username.strip()
    client_ip = get_client_ip(request)
    throttle: LoginThrottle = request.app.state.login_throttle
    throttle.check(username, client_ip)

    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None or not user.active or not verify_password(payload.password, user.password_hash):
        throttle.record_failure(username, client_ip)
        reason = "inactive_user" if (user is not None and not user.active) else "invalid_credentials"
        record_audit(
            db,
            action="login_failed",
            user_id=user.id if user is not None else None,
            username=username,
            role=user.role if user is not None else None,
            target_type="user",
            target_id=str(user.id) if user is not None else None,
            details={"reason": reason},
            ip=client_ip,
        )
        raise AppError(
            status_code=401,
            code="INVALID_CREDENTIALS",
            detail="Invalid username or password.",
        )

    throttle.reset(username, client_ip)
    token = create_access_token(user.id, user.username, user.role, settings)
    record_audit(
        db,
        action="login_success",
        user_id=user.id,
        username=user.username,
        role=user.role,
        target_type="user",
        target_id=str(user.id),
        details={},
        ip=client_ip,
    )
    return LoginResponse(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)) -> UserOut:
    """Return the currently authenticated user profile."""
    return UserOut.model_validate(current_user)
