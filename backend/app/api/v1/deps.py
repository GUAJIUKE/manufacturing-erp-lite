"""Auth dependencies: get_current_user, require_perm.

RBAC model (basic):
- users have exactly one role (v1)
- roles map to permissions via role_permissions
- `require_perm("pr:approve")` guards route-level access (menu/button level)
- Business-level eligibility (e.g. "is this user the department manager of
  the applicant") is checked in the service layer, not here (Q12)
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import (
    ForbiddenException,
    PermissionDeniedException,
    UnauthorizedException,
)
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import Permission, RolePermission, User
from app.schemas.auth import CurrentUser
from app.services.auth_service import load_current_user
from app.utils.enums import UserStatus

# HTTPBearer(auto_error=False): we raise our own UnauthorizedException instead
# of FastAPI's default 403 so the response envelope stays consistent.
_bearer = HTTPBearer(auto_error=False)

DbDep = Annotated[Session, Depends(get_db)]


def _extract_token(credentials: HTTPAuthorizationCredentials | None) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedException("缺少认证信息，请先登录")
    return credentials.credentials


def _principal(db: Session, user: User) -> CurrentUser:
    role = user.role
    return CurrentUser(
        id=user.id,
        username=user.username,
        real_name=user.real_name,
        role_id=user.role_id,
        role_code=role.role_code.value if role else "",
        role_name=role.role_name if role else "",
        department_id=user.department_id,
        department_name=user.department.dept_name if user.department else None,
    )


def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: DbDep,
) -> CurrentUser:
    token = _extract_token(credentials)
    payload = decode_access_token(token)

    sub = payload.get("sub")
    uid = payload.get("uid")
    if not sub or not uid:
        raise UnauthorizedException("登录凭证无效")

    user = load_current_user(db, int(uid))
    if user is None or user.username != sub:
        raise UnauthorizedException("登录凭证无效")
    if user.status != UserStatus.ACTIVE:
        raise ForbiddenException("账号已被禁用")

    return _principal(db, user)


def get_role_permissions(db: Session, role_id: int) -> set[str]:
    """Permission codes held by a role (used by require_perm and /auth/me)."""
    stmt = (
        select(Permission.perm_code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role_id)
    )
    return set(db.execute(stmt).scalars().all())


def require_perm(perm_code: str):
    """Route-level guard: the current user's role must hold ``perm_code``.

    Usage::

        @router.get("/materials")
        def list_materials(user: Annotated[CurrentUser, Depends(get_current_user)],
                           _guard: Annotated[None, Depends(require_perm("material:view"))]):
            ...
    """

    def _dependency(
        user: Annotated[CurrentUser, Depends(get_current_user)],
        db: DbDep,
    ) -> None:
        perms = get_role_permissions(db, user.role_id)
        if perm_code not in perms:
            raise PermissionDeniedException(f"缺少权限：{perm_code}")

    return _dependency


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
