"""Role & permission management endpoints (require role:* permissions).

Permission assignment uses replace-style semantics (the request carries the
target permission set in full) and triggers a PERMISSION_CHANGE audit inside
the same business transaction (role_service.assign_permissions).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.deps import CurrentUserDep, DbDep, require_perm
from app.core.response import ApiResponse
from app.schemas.role import RoleAssignRequest, RoleCreate, RoleOut, RoleUpdate
from app.services import role_service

router = APIRouter(prefix="/roles", tags=["roles"])
permission_router = APIRouter(prefix="/permissions", tags=["permissions"])


def _to_out(role, permission_ids: list[int] | None = None) -> dict:
    data = RoleOut.model_validate(role).model_dump(mode="json")
    if permission_ids is not None:
        data["permission_ids"] = sorted(permission_ids)
    return data


@router.get("", summary="角色列表")
def list_roles(
    db: DbDep,
    _guard: None = Depends(require_perm("role:view")),
) -> ApiResponse[list[dict]]:
    roles = role_service.list_roles(db)
    return ApiResponse.ok([_to_out(r, role_service.role_permission_ids(db, r.id)) for r in roles])


@router.post("", summary="创建角色")
def create_role(
    payload: RoleCreate,
    db: DbDep,
    _guard: None = Depends(require_perm("role:create")),
) -> ApiResponse[dict]:
    role = role_service.create_role(db, payload)
    db.commit()
    return ApiResponse.ok(
        _to_out(role, role_service.role_permission_ids(db, role.id)), message="创建成功"
    )


@router.get("/{role_id}", summary="角色详情")
def get_role(
    role_id: int,
    db: DbDep,
    _guard: None = Depends(require_perm("role:view")),
) -> ApiResponse[dict]:
    role = role_service.get_role(db, role_id)
    return ApiResponse.ok(_to_out(role, role_service.role_permission_ids(db, role_id)))


@router.put("/{role_id}", summary="更新角色")
def update_role(
    role_id: int,
    payload: RoleUpdate,
    db: DbDep,
    _guard: None = Depends(require_perm("role:update")),
) -> ApiResponse[dict]:
    role = role_service.update_role(db, role_id, payload)
    db.commit()
    return ApiResponse.ok(_to_out(role, role_service.role_permission_ids(db, role_id)), message="更新成功")


@router.delete("/{role_id}", summary="删除角色")
def delete_role(
    role_id: int,
    db: DbDep,
    _guard: None = Depends(require_perm("role:delete")),
) -> ApiResponse[None]:
    role_service.delete_role(db, role_id)
    db.commit()
    return ApiResponse.ok(None, message="已删除")


@router.post("/{role_id}/permissions", summary="分配权限（替换式）")
def assign_permissions(
    role_id: int,
    payload: RoleAssignRequest,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("role:assign")),
) -> ApiResponse[dict]:
    role = role_service.assign_permissions(db, role_id, payload.permission_ids, operator=user)
    db.commit()
    return ApiResponse.ok(
        _to_out(role, role_service.role_permission_ids(db, role.id)), message="权限已更新"
    )


@permission_router.get("", summary="权限点列表")
def list_permissions(
    db: DbDep,
    _guard: None = Depends(require_perm("role:view")),
) -> ApiResponse[list[dict]]:
    perms = role_service.list_permissions(db)
    return ApiResponse.ok(
        [
            {
                "id": p.id,
                "perm_code": p.perm_code,
                "perm_name": p.perm_name,
                "module": p.module,
            }
            for p in perms
        ]
    )
