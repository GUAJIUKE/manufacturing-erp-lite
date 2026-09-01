"""Role management service with permission assignment (PERMISSION_CHANGE audit)."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictException, ErrorCode, NotFoundException
from app.models import Permission, Role, RolePermission, User
from app.schemas.role import RoleCreate, RoleUpdate
from app.services.audit_service import write_audit
from app.utils.enums import AuditAction


def list_roles(db: Session) -> list[Role]:
    return list(db.execute(select(Role).order_by(Role.id)).scalars().all())


def get_role(db: Session, role_id: int) -> Role:
    role = db.get(Role, role_id)
    if role is None:
        raise NotFoundException("角色不存在", code=ErrorCode.NOT_FOUND)
    return role


def create_role(db: Session, data: RoleCreate) -> Role:
    exists = db.execute(
        select(Role.id).where(Role.role_code == data.role_code.value)
    ).scalar_one_or_none()
    if exists is not None:
        raise ConflictException("角色编码已存在", code=ErrorCode.ROLE_CODE_EXISTS)

    role = Role(
        role_code=data.role_code,
        role_name=data.role_name,
        description=data.description,
        is_system=False,
    )
    db.add(role)
    db.flush()

    if data.permission_ids:
        _replace_permissions(db, role, data.permission_ids)
    db.flush()
    return role


def update_role(db: Session, role_id: int, data: RoleUpdate) -> Role:
    role = get_role(db, role_id)
    if data.role_name is not None:
        role.role_name = data.role_name
    if data.description is not None:
        role.description = data.description
    if data.status is not None:
        role.status = data.status
    db.flush()
    return role


def delete_role(db: Session, role_id: int) -> None:
    role = get_role(db, role_id)
    if role.is_system:
        raise ConflictException("系统内置角色不可删除", code=ErrorCode.CONFLICT)
    in_use = db.execute(select(User.id).where(User.role_id == role_id).limit(1)).scalar_one_or_none()
    if in_use is not None:
        raise ConflictException("该角色下存在用户，不可删除", code=ErrorCode.CONFLICT)
    db.delete(role)


def _replace_permissions(db: Session, role: Role, permission_ids: list[int]) -> None:
    """Replace the role's permission set (delete + insert in one transaction)."""
    db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))

    ids = set(permission_ids)
    if not ids:
        return
    found = set(
        db.execute(select(Permission.id).where(Permission.id.in_(ids))).scalars().all()
    )
    missing = ids - found
    if missing:
        raise NotFoundException(
            f"权限点不存在：{sorted(missing)}", code=ErrorCode.NOT_FOUND
        )
    for pid in sorted(ids):
        db.add(RolePermission(role_id=role.id, permission_id=pid))


def assign_permissions(
    db: Session, role_id: int, permission_ids: list[int], *, operator: User
) -> Role:
    """Replace permission set; audit PERMISSION_CHANGE in the same transaction."""
    role = get_role(db, role_id)
    _replace_permissions(db, role, permission_ids)
    write_audit(
        db,
        action=AuditAction.PERMISSION_CHANGE,
        module="rbac",
        operator=operator,
        document_type="role",
        document_id=role.id,
        description=f"角色 {role.role_name}({role.role_code.value}) 权限更新为 {len(set(permission_ids))} 项",
    )
    db.flush()
    return role


def list_permissions(db: Session) -> list[Permission]:
    return list(db.execute(select(Permission).order_by(Permission.module, Permission.id)).scalars().all())


def role_permission_ids(db: Session, role_id: int) -> list[int]:
    return list(
        db.execute(
            select(RolePermission.permission_id).where(RolePermission.role_id == role_id)
        ).scalars().all()
    )
