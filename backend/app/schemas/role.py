"""Role & department management schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.utils.enums import ActiveStatus, DeptStatus, RoleCode


# ----------------------------------------------------------------------
# Role
# ----------------------------------------------------------------------
class RoleCreate(BaseModel):
    role_code: RoleCode
    role_name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=255)
    permission_ids: list[int] = Field(default_factory=list, description="初始权限点 ID 列表")


class RoleUpdate(BaseModel):
    role_name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=255)
    status: ActiveStatus | None = None


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role_code: RoleCode
    role_name: str
    description: str | None = None
    is_system: bool
    status: ActiveStatus
    created_at: datetime


class RoleAssignRequest(BaseModel):
    """Grant/revoke permission set for a role (role:assign → PERMISSION_CHANGE audit)."""

    permission_ids: list[int] = Field(description="目标权限点 ID 全集（替换式赋值）")


# ----------------------------------------------------------------------
# Department
# ----------------------------------------------------------------------
class DepartmentCreate(BaseModel):
    dept_code: str = Field(min_length=1, max_length=32)
    dept_name: str = Field(min_length=1, max_length=64)
    parent_id: int | None = None
    sort_order: int = 0
    remark: str | None = Field(default=None, max_length=255)


class DepartmentUpdate(BaseModel):
    dept_name: str | None = Field(default=None, min_length=1, max_length=64)
    parent_id: int | None = None
    sort_order: int | None = None
    status: DeptStatus | None = None
    remark: str | None = Field(default=None, max_length=255)


class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dept_code: str
    dept_name: str
    parent_id: int | None = None
    sort_order: int
    status: DeptStatus
    remark: str | None = None
    created_at: datetime
