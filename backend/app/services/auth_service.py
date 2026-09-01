"""Authentication service: login, JWT issuing, audit logging."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.exceptions import (
    InvalidCredentialsException,
    UserDisabledException,
)
from app.core.security import create_access_token, verify_password
from app.models import Department, Role, User
from app.services.audit_service import write_audit
from app.utils.enums import AuditAction, UserStatus


def get_user_by_username(db: Session, username: str) -> User | None:
    stmt = (
        select(User)
        .options(joinedload(User.role), joinedload(User.department))
        .where(User.username == username)
    )
    return db.execute(stmt).scalar_one_or_none()


def login(db: Session, *, username: str, password: str, request: Request) -> tuple[str, int]:
    """Authenticate and return (access_token, expires_in_seconds).

    Audit records use an independent transaction: LOGIN_FAILED is recorded
    even though no valid session exists.
    """
    from app.db.session import SessionLocal

    user = get_user_by_username(db, username)

    # -- failure path (independent audit transaction) --
    if user is None or not verify_password(password, user.password_hash):
        failed_db = SessionLocal()
        try:
            write_audit(
                failed_db,
                action=AuditAction.LOGIN_FAILED,
                module="auth",
                username_snapshot=username,
                description="登录失败：用户名或密码错误",
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
            )
            failed_db.commit()
        finally:
            failed_db.close()
        raise InvalidCredentialsException()

    if user.status != UserStatus.ACTIVE:
        raise UserDisabledException()

    # -- success path --
    token = create_access_token(
        subject=user.username,
        extra={"uid": user.id, "role": user.role.role_code.value if user.role else None},
    )
    user.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)

    write_audit(
        db,
        action=AuditAction.LOGIN,
        module="auth",
        operator=user,
        description=f"用户 {user.username} 登录成功",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()

    from app.core.config import settings

    return token, settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60


def load_current_user(db: Session, user_id: int) -> User | None:
    """Load a user with role and department eager-loaded (for get_current_user)."""
    stmt = (
        select(User)
        .options(joinedload(User.role), joinedload(User.department))
        .where(User.id == user_id)
    )
    return db.execute(stmt).scalar_one_or_none()
