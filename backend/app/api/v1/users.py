"""User management endpoints (require user:* permissions)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import CurrentUserDep, DbDep, require_perm
from app.core.response import ApiResponse, PageResult
from app.schemas.user import UserCreate, UserOut, UserUpdate
from app.services import user_service
from app.utils.enums import UserStatus

router = APIRouter(prefix="/users", tags=["users"])


def _to_out(user) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        real_name=user.real_name,
        email=user.email,
        phone=user.phone,
        department_id=user.department_id,
        department_name=user.department.dept_name if user.department else None,
        role_id=user.role_id,
        role_code=user.role.role_code.value if user.role else None,
        role_name=user.role.role_name if user.role else None,
        status=user.status,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


@router.get("", summary="用户列表（分页）")
def list_users(
    db: DbDep,
    _guard: None = Depends(require_perm("user:view")),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = Query(None, description="账号/姓名模糊搜索"),
    status: UserStatus | None = None,
    department_id: int | None = None,
) -> ApiResponse[PageResult[UserOut]]:
    rows, total = user_service.list_users(
        db,
        page=page,
        page_size=page_size,
        keyword=keyword,
        status=status,
        department_id=department_id,
    )
    return ApiResponse.ok(
        PageResult(items=[_to_out(u) for u in rows], total=total, page=page, page_size=page_size)
    )


@router.post("", summary="创建用户")
def create_user(
    payload: UserCreate,
    db: DbDep,
    _guard: None = Depends(require_perm("user:create")),
) -> ApiResponse[UserOut]:
    user = user_service.create_user(db, payload)
    db.commit()
    return ApiResponse.ok(_to_out(user), message="创建成功")


@router.put("/{user_id}", summary="更新用户")
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: DbDep,
    _guard: None = Depends(require_perm("user:update")),
) -> ApiResponse[UserOut]:
    user = user_service.update_user(db, user_id, payload)
    db.commit()
    return ApiResponse.ok(_to_out(user), message="更新成功")


@router.delete("/{user_id}", summary="停用用户（软删除）")
def disable_user(
    user_id: int,
    db: DbDep,
    _guard: None = Depends(require_perm("user:delete")),
) -> ApiResponse[None]:
    user_service.disable_user(db, user_id)
    db.commit()
    return ApiResponse.ok(None, message="已停用")
