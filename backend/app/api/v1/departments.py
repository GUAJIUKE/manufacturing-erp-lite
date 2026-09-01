"""Department management endpoints (require department:* permissions)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import DbDep, require_perm
from app.core.response import ApiResponse
from app.schemas.role import DepartmentCreate, DepartmentOut, DepartmentUpdate
from app.services import department_service
from app.utils.enums import DeptStatus

router = APIRouter(prefix="/departments", tags=["departments"])


@router.get("", summary="部门列表")
def list_departments(
    db: DbDep,
    _guard: None = Depends(require_perm("department:view")),
    status: DeptStatus | None = Query(None, description="按状态过滤"),
) -> ApiResponse[list[DepartmentOut]]:
    depts = department_service.list_departments(db, status=status)
    return ApiResponse.ok([DepartmentOut.model_validate(d) for d in depts])


@router.post("", summary="创建部门")
def create_department(
    payload: DepartmentCreate,
    db: DbDep,
    _guard: None = Depends(require_perm("department:create")),
) -> ApiResponse[DepartmentOut]:
    dept = department_service.create_department(db, payload)
    db.commit()
    return ApiResponse.ok(DepartmentOut.model_validate(dept), message="创建成功")


@router.get("/{dept_id}", summary="部门详情")
def get_department(
    dept_id: int,
    db: DbDep,
    _guard: None = Depends(require_perm("department:view")),
) -> ApiResponse[DepartmentOut]:
    dept = department_service.get_department(db, dept_id)
    return ApiResponse.ok(DepartmentOut.model_validate(dept))


@router.put("/{dept_id}", summary="更新部门")
def update_department(
    dept_id: int,
    payload: DepartmentUpdate,
    db: DbDep,
    _guard: None = Depends(require_perm("department:update")),
) -> ApiResponse[DepartmentOut]:
    dept = department_service.update_department(db, dept_id, payload)
    db.commit()
    return ApiResponse.ok(DepartmentOut.model_validate(dept), message="更新成功")


@router.delete("/{dept_id}", summary="停用部门（软删除）")
def disable_department(
    dept_id: int,
    db: DbDep,
    _guard: None = Depends(require_perm("department:delete")),
) -> ApiResponse[None]:
    department_service.disable_department(db, dept_id)
    db.commit()
    return ApiResponse.ok(None, message="已停用")
