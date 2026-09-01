"""Department management service."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictException, ErrorCode, NotFoundException
from app.models import Department, User
from app.schemas.role import DepartmentCreate, DepartmentUpdate
from app.utils.enums import DeptStatus


def list_departments(db: Session, *, status: ActiveStatus | None = None) -> list[Department]:
    stmt = select(Department).order_by(Department.sort_order, Department.id)
    if status is not None:
        stmt = stmt.where(Department.status == status)
    return list(db.execute(stmt).scalars().all())


def get_department(db: Session, dept_id: int) -> Department:
    dept = db.get(Department, dept_id)
    if dept is None:
        raise NotFoundException("部门不存在", code=ErrorCode.NOT_FOUND)
    return dept


def create_department(db: Session, data: DepartmentCreate) -> Department:
    exists = db.execute(
        select(Department.id).where(Department.dept_code == data.dept_code)
    ).scalar_one_or_none()
    if exists is not None:
        raise ConflictException("部门编码已存在", code=ErrorCode.DEPARTMENT_CODE_EXISTS)
    if data.parent_id is not None:
        get_department(db, data.parent_id)  # raises if missing

    dept = Department(
        dept_code=data.dept_code,
        dept_name=data.dept_name,
        parent_id=data.parent_id,
        sort_order=data.sort_order,
        remark=data.remark,
        status=DeptStatus.ACTIVE,
    )
    db.add(dept)
    db.flush()
    return dept


def update_department(db: Session, dept_id: int, data: DepartmentUpdate) -> Department:
    dept = get_department(db, dept_id)
    if data.dept_name is not None:
        dept.dept_name = data.dept_name
    if data.parent_id is not None:
        if data.parent_id == dept.id:
            raise ConflictException("部门不能作为自己的上级", code=ErrorCode.CONFLICT)
        get_department(db, data.parent_id)
        dept.parent_id = data.parent_id
    if data.sort_order is not None:
        dept.sort_order = data.sort_order
    if data.status is not None:
        dept.status = data.status
    if data.remark is not None:
        dept.remark = data.remark
    db.flush()
    return dept


def disable_department(db: Session, dept_id: int) -> Department:
    """Soft delete: status -> INACTIVE. Users still referencing the dept block it."""
    dept = get_department(db, dept_id)
    in_use = db.execute(
        select(User.id).where(User.department_id == dept_id).limit(1)
    ).scalar_one_or_none()
    if in_use is not None:
        raise ConflictException("该部门下存在用户，不可停用", code=ErrorCode.CONFLICT)
    dept.status = DeptStatus.INACTIVE
    db.flush()
    return dept
