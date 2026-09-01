"""User management service (bcrypt hashing, username uniqueness, soft delete)."""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.exceptions import ConflictException, ErrorCode, NotFoundException
from app.core.security import hash_password
from app.models import Department, Role, User
from app.schemas.user import UserCreate, UserUpdate
from app.utils.enums import UserStatus


def _load_user(db: Session, user_id: int) -> User:
    stmt = (
        select(User)
        .options(joinedload(User.role), joinedload(User.department))
        .where(User.id == user_id)
    )
    user = db.execute(stmt).scalar_one_or_none()
    if user is None:
        raise NotFoundException("用户不存在", code=ErrorCode.NOT_FOUND)
    return user


def _validate_refs(db: Session, role_id: int, department_id: int | None) -> None:
    role = db.get(Role, role_id)
    if role is None:
        raise NotFoundException("角色不存在", code=ErrorCode.NOT_FOUND)
    if department_id is not None:
        dept = db.get(Department, department_id)
        if dept is None:
            raise NotFoundException("部门不存在", code=ErrorCode.NOT_FOUND)


def create_user(db: Session, data: UserCreate) -> User:
    exists = db.execute(select(User.id).where(User.username == data.username)).scalar_one_or_none()
    if exists is not None:
        raise ConflictException("用户名已存在", code=ErrorCode.USERNAME_EXISTS)

    _validate_refs(db, data.role_id, data.department_id)

    user = User(
        username=data.username,
        password_hash=hash_password(data.password),
        real_name=data.real_name,
        email=data.email,
        phone=data.phone,
        department_id=data.department_id,
        role_id=data.role_id,
        status=UserStatus.ACTIVE,
    )
    db.add(user)
    db.flush()
    return _load_user(db, user.id)


def update_user(db: Session, user_id: int, data: UserUpdate) -> User:
    user = _load_user(db, user_id)

    if data.role_id is not None and data.role_id != user.role_id:
        _validate_refs(db, data.role_id, None)
        user.role_id = data.role_id
    if data.department_id is not None and data.department_id != user.department_id:
        _validate_refs(db, user.role_id, data.department_id)
        user.department_id = data.department_id
    elif data.department_id is None and "department_id" in data.model_fields_set:
        user.department_id = None

    if data.real_name is not None:
        user.real_name = data.real_name
    if data.email is not None:
        user.email = data.email
    if data.phone is not None:
        user.phone = data.phone
    if data.status is not None:
        user.status = data.status
    if data.password is not None:
        user.password_hash = hash_password(data.password)

    db.flush()
    return _load_user(db, user.id)


def disable_user(db: Session, user_id: int) -> User:
    """Soft delete: status -> DISABLED (business documents must never be
    physically deleted, architecture rule 2)."""
    user = _load_user(db, user_id)
    user.status = UserStatus.DISABLED
    db.flush()
    return user


def list_users(
    db: Session,
    *,
    page: int,
    page_size: int,
    keyword: str | None = None,
    status: UserStatus | None = None,
    department_id: int | None = None,
) -> tuple[list[User], int]:
    stmt = select(User).options(joinedload(User.role), joinedload(User.department))
    count_stmt = select(func.count()).select_from(User)

    if keyword:
        like = f"%{keyword}%"
        cond = or_(User.username.like(like), User.real_name.like(like))
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    if status is not None:
        stmt = stmt.where(User.status == status)
        count_stmt = count_stmt.where(User.status == status)
    if department_id is not None:
        stmt = stmt.where(User.department_id == department_id)
        count_stmt = count_stmt.where(User.department_id == department_id)

    total = db.execute(count_stmt).scalar_one()
    rows = db.execute(
        stmt.order_by(User.id).offset((page - 1) * page_size).limit(page_size)
    ).scalars().all()
    return list(rows), total
