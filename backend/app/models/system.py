"""System domain models: departments, roles, permissions, users.

Maps 1:1 to docs/database-design.md §3.1 - §3.6.
FK / UNIQUE / CHECK constraint names match the design document exactly so
Alembic autogenerate produces the documented DDL.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum as SAEnum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mysql import BIGINT as BigInteger, DATETIME

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import PKMixin, TimestampMixin
from app.utils.enums import ActiveStatus, DeptStatus, RoleCode, UserStatus


class Department(PKMixin, TimestampMixin, Base):
    """部门（§3.1）"""

    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("dept_code", name="uk_dept_code"),
        Index("ix_dept_parent", "parent_id"),
        Index("ix_dept_status", "status"),
    )

    dept_code: Mapped[str] = mapped_column(String(32), nullable=False, comment="部门编码，如 RD / PUR")
    dept_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="部门名称")
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("departments.id", name="fk_dept_parent"),
        nullable=True,
        comment="上级部门，自引用",
    )
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False, comment="排序")
    status: Mapped[DeptStatus] = mapped_column(
        SAEnum(DeptStatus, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        server_default=DeptStatus.ACTIVE.value,
        comment="状态",
    )
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注")
    created_by: Mapped[int | None] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("users.id", name="fk_departments_created_by_users"),
        nullable=True,
    )
    updated_by: Mapped[int | None] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("users.id", name="fk_departments_updated_by_users"),
        nullable=True,
    )

    children: Mapped[list["Department"]] = relationship(
        back_populates="parent", remote_side="Department.id"
    )
    parent: Mapped["Department | None"] = relationship(
        back_populates="children", remote_side="Department.parent_id"
    )


class Role(PKMixin, TimestampMixin, Base):
    """角色（§3.2）"""

    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("role_code", name="uk_role_code"),
        Index("ix_role_status", "status"),
    )

    role_code: Mapped[RoleCode] = mapped_column(
        SAEnum(RoleCode, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        comment="ADMIN/APPLICANT/DEPT_MANAGER/BUYER/WAREHOUSE",
    )
    role_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="角色名称")
    description: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="描述")
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="1=系统内置不可删除")
    status: Mapped[ActiveStatus] = mapped_column(
        SAEnum(ActiveStatus, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        server_default=ActiveStatus.ACTIVE.value,
        comment="状态",
    )

    permissions: Mapped[list["Permission"]] = relationship(
        secondary="role_permissions",
        back_populates="roles",
        passive_deletes=True,
    )


class Permission(PKMixin, Base):
    """权限点（§3.3）"""

    __tablename__ = "permissions"
    __table_args__ = (
        UniqueConstraint("perm_code", name="uk_perm_code"),
        Index("ix_perm_module", "module"),
    )

    perm_code: Mapped[str] = mapped_column(String(64), nullable=False, comment="如 pr:approve")
    perm_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="权限名称")
    module: Mapped[str] = mapped_column(String(32), nullable=False, comment="模块分组，前端菜单渲染用")
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )

    roles: Mapped[list["Role"]] = relationship(
        secondary="role_permissions", back_populates="permissions", passive_deletes=True
    )


class RolePermission(PKMixin, Base):
    """角色-权限关联（§3.4）"""

    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uk_role_perm"),
        Index("ix_roleperm_perm", "permission_id"),
    )

    role_id: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("roles.id", name="fk_rp_role", ondelete="CASCADE"),
        nullable=False,
    )
    permission_id: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("permissions.id", name="fk_rp_permission", ondelete="CASCADE"),
        nullable=False,
    )


class User(PKMixin, TimestampMixin, Base):
    """用户（§3.5）"""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username", name="uk_user_username"),
        Index("ix_user_dept", "department_id"),
        Index("ix_user_role", "role_id"),
        Index("ix_user_status", "status"),
    )

    username: Mapped[str] = mapped_column(String(64), nullable=False, comment="登录账号")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, comment="bcrypt 哈希，明文永不落库")
    real_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="姓名")
    email: Mapped[str | None] = mapped_column(String(128), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    department_id: Mapped[int | None] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("departments.id", name="fk_user_dept", ondelete="RESTRICT"),
        nullable=True,
        comment="所属部门",
    )
    role_id: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("roles.id", name="fk_user_role", ondelete="RESTRICT"),
        nullable=False,
        comment="角色（v1 单角色）",
    )
    status: Mapped[UserStatus] = mapped_column(
        SAEnum(UserStatus, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        server_default=UserStatus.ACTIVE.value,
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True, comment="最后登录时间")
    created_by: Mapped[int | None] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("users.id", name="fk_users_created_by_users"),
        nullable=True,
    )
    updated_by: Mapped[int | None] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("users.id", name="fk_users_updated_by_users"),
        nullable=True,
    )

    department: Mapped["Department | None"] = relationship(
        foreign_keys="User.department_id"
    )
    role: Mapped["Role"] = relationship(foreign_keys="User.role_id")


class DepartmentManager(PKMixin, Base):
    """部门主管关系（§3.6，Q12）

    独立关联表而非 departments.manager_user_id，避免 departments ↔ users
    循环外键，且支持一部门多主管。
    """

    __tablename__ = "department_managers"
    __table_args__ = (
        UniqueConstraint("dept_id", "user_id", name="uk_deptmgr"),
        Index("ix_deptmgr_user", "user_id"),
    )

    dept_id: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("departments.id", name="fk_deptmgr_dept", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("users.id", name="fk_deptmgr_user", ondelete="CASCADE"),
        nullable=False,
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="是否主主管")
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )
