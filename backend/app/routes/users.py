"""Admin-only user management endpoints."""

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.audit import record_audit
from backend.app.db import get_db
from backend.app.deps import get_client_ip, require_admin
from backend.app.errors import AppError
from backend.app.models import User
from backend.app.schemas import UserCreateRequest, UserOut
from backend.app.security import hash_password

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UserOut:
    """Create a new admin or investigator account (admin only)."""
    existing = db.execute(
        select(User).where(User.username == payload.username)
    ).scalar_one_or_none()
    if existing is not None:
        raise AppError(
            status_code=409,
            code="USERNAME_EXISTS",
            detail=f"Username '{payload.username}' already exists.",
        )

    new_user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=payload.role,
        full_name=payload.full_name,
        active=True,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    record_audit(
        db,
        action="user_created",
        user_id=admin.id,
        username=admin.username,
        role=admin.role,
        target_type="user",
        target_id=str(new_user.id),
        details={"created_username": new_user.username, "created_role": new_user.role},
        ip=get_client_ip(request),
    )
    return UserOut.model_validate(new_user)


@router.get("", response_model=list[UserOut])
def list_users(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[UserOut]:
    """List all user accounts ordered by id (admin only)."""
    users = db.execute(select(User).order_by(User.id.asc())).scalars().all()
    return [UserOut.model_validate(user) for user in users]
