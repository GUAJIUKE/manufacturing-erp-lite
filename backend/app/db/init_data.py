"""Idempotent seed script for Phase 4 (RBAC bootstrap data).

Seeds (matching docs/database-design.md §2.3 / §3):
- 6 departments (研发部/采购部/生产部/质量部/仓库/行政部)
- 5 roles (ADMIN/APPLICANT/DEPT_MANAGER/BUYER/WAREHOUSE)
- 44 permission points (material:/supplier:/warehouse:/department:/user:/role:
  + role:assign, pr:*, po:*, receipt:*, inventory:*, dashboard:*)
- role -> permission matrix (v1)
- 5 demo users (admin / admin123, 研发人员, 研发主管, 采购员, 仓库管理员)
- department_managers entries (Q12: 研发部 -> 研发主管, primary)

Runnable against BOTH dev and test DBs (choose via ENV=dev|test).

Usage:
    cd backend
    python -m app.db.init_data            # dev (erp_lite)
    ENV=test python -m app.db.init_data   # test (erp_lite_test)

Idempotency: every entity is looked up by its unique business key; existing
records are left untouched, missing ones are inserted. role_permissions only
adds missing links (never removes), so re-running is safe.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running as `python -m app.db.init_data` from the backend directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import select  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Department,
    DepartmentManager,
    Permission,
    Role,
    RolePermission,
    User,
)
from app.utils.enums import (  # noqa: E402
    ActiveStatus,
    DeptStatus,
    RoleCode,
    UserStatus,
)

# ----------------------------------------------------------------------
# Static data (matches docs/database-design.md §2.3)
# ----------------------------------------------------------------------
DEPARTMENTS: list[dict] = [
    {"dept_code": "RD", "dept_name": "研发部", "sort_order": 1},
    {"dept_code": "PUR", "dept_name": "采购部", "sort_order": 2},
    {"dept_code": "MFR", "dept_name": "生产部", "sort_order": 3},
    {"dept_code": "QA", "dept_name": "质量部", "sort_order": 4},
    {"dept_code": "WH", "dept_name": "仓库", "sort_order": 5},
    {"dept_code": "ADM", "dept_name": "行政部", "sort_order": 6},
]

# (perm_code, perm_name, module)
PERMISSIONS: list[tuple[str, str, str]] = [
    # 物料
    ("material:view", "查看物料", "material"),
    ("material:create", "新建物料", "material"),
    ("material:update", "编辑物料", "material"),
    ("material:delete", "停用物料", "material"),
    # 供应商
    ("supplier:view", "查看供应商", "supplier"),
    ("supplier:create", "新建供应商", "supplier"),
    ("supplier:update", "编辑供应商", "supplier"),
    ("supplier:delete", "停用供应商", "supplier"),
    # 仓库
    ("warehouse:view", "查看仓库", "warehouse"),
    ("warehouse:create", "新建仓库", "warehouse"),
    ("warehouse:update", "编辑仓库", "warehouse"),
    ("warehouse:delete", "停用仓库", "warehouse"),
    # 部门
    ("department:view", "查看部门", "department"),
    ("department:create", "新建部门", "department"),
    ("department:update", "编辑部门", "department"),
    ("department:delete", "停用部门", "department"),
    # 用户
    ("user:view", "查看用户", "user"),
    ("user:create", "新建用户", "user"),
    ("user:update", "编辑用户", "user"),
    ("user:delete", "停用用户", "user"),
    # 角色
    ("role:view", "查看角色", "role"),
    ("role:create", "新建角色", "role"),
    ("role:update", "编辑角色", "role"),
    ("role:delete", "删除角色", "role"),
    ("role:assign", "分配权限", "role"),
    # 采购申请
    ("pr:view", "查看申请", "pr"),
    ("pr:create", "新建申请", "pr"),
    ("pr:update", "编辑申请", "pr"),
    ("pr:delete", "删除草稿申请", "pr"),
    ("pr:submit", "提交审批", "pr"),
    ("pr:approve", "审批申请", "pr"),
    ("pr:reject", "驳回申请", "pr"),
    ("pr:cancel", "撤销申请", "pr"),
    # 采购订单
    ("po:view", "查看订单", "po"),
    ("po:create", "新建订单", "po"),
    ("po:update", "编辑订单", "po"),
    ("po:delete", "删除草稿订单", "po"),
    ("po:confirm", "确认订单", "po"),
    ("po:cancel", "取消订单", "po"),
    # 采购入库（无 receipt:delete，Q6）
    ("receipt:view", "查看入库单", "receipt"),
    ("receipt:create", "入库过账", "receipt"),
    ("receipt:reverse", "入库冲销", "receipt"),
    # 库存
    ("inventory:view", "查看库存", "inventory"),
    ("inventory_txn:view", "查看库存流水", "inventory"),
    # 库存策略（安全库存，Phase 5 新增）
    ("inventory_policy:view", "查看库存策略", "inventory_policy"),
    ("inventory_policy:create", "新建库存策略", "inventory_policy"),
    ("inventory_policy:update", "编辑库存策略", "inventory_policy"),
    # 库存盘点（Reality Hardening Sprint 1 / Implementation A）
    ("reconcile:view", "查看库存盘点", "reconcile"),
    ("reconcile:create", "新建库存盘点", "reconcile"),
    ("reconcile:update", "编辑库存盘点草稿", "reconcile"),
    ("reconcile:submit", "提交库存盘点", "reconcile"),
    ("reconcile:approve", "审批过账库存盘点", "reconcile"),
    ("reconcile:reject", "驳回库存盘点", "reconcile"),
    ("reconcile:self_approve_override", "盘点自审 override（SoD 例外，CR-A-007）", "reconcile"),
    # 首页
    ("dashboard:view", "查看首页", "dashboard"),
]

ROLES: list[dict] = [
    {"role_code": RoleCode.ADMIN, "role_name": "系统管理员", "description": "拥有全部权限", "is_system": True},
    {"role_code": RoleCode.APPLICANT, "role_name": "采购申请人", "description": "研发/生产人员：提采购申请、跟踪进度", "is_system": True},
    {"role_code": RoleCode.DEPT_MANAGER, "role_name": "部门主管", "description": "审批本部门采购申请", "is_system": True},
    {"role_code": RoleCode.BUYER, "role_name": "采购员", "description": "采购订单执行、供应商维护", "is_system": True},
    {"role_code": RoleCode.WAREHOUSE, "role_name": "仓库管理员", "description": "入库过账、库存查询、冲销", "is_system": True},
]

ALL_PERM_CODES = {code for code, _name, _mod in PERMISSIONS}

# role_code -> permission codes (v1 matrix)
ROLE_PERMISSIONS: dict[RoleCode, set[str]] = {
    RoleCode.ADMIN: set(ALL_PERM_CODES),
    RoleCode.APPLICANT: {
        "pr:view", "pr:create", "pr:update", "pr:delete", "pr:submit", "pr:cancel",
        "po:view", "receipt:view",
        "inventory:view", "inventory_txn:view",
        "material:view", "supplier:view", "warehouse:view",
        "dashboard:view",
    },
    RoleCode.DEPT_MANAGER: {
        "pr:view", "pr:create", "pr:update", "pr:delete", "pr:submit",
        "pr:approve", "pr:reject", "pr:cancel",
        "po:view", "receipt:view",
        "inventory:view", "inventory_txn:view",
        "material:view", "supplier:view", "warehouse:view",
        "user:view", "department:view",
        "dashboard:view",
    },
    RoleCode.BUYER: {
        "material:view", "material:update",
        "supplier:view", "supplier:create", "supplier:update", "supplier:delete",
        "warehouse:view",
        "inventory_policy:view", "inventory_policy:create", "inventory_policy:update",
        "pr:view",
        "po:view", "po:create", "po:update", "po:delete", "po:confirm", "po:cancel",
        "receipt:view",
        "inventory:view", "inventory_txn:view",
        "dashboard:view",
    },
    RoleCode.WAREHOUSE: {
        "warehouse:view", "po:view",
        "receipt:view", "receipt:create", "receipt:reverse",
        "inventory:view", "inventory_txn:view",
        "inventory_policy:view",
        "reconcile:view", "reconcile:create", "reconcile:update", "reconcile:submit",
        "dashboard:view",
    },
}

# username -> (password, real_name, dept_code, role_code)
DEMO_USERS: list[tuple[str, str, str, str, RoleCode]] = [
    ("admin", "admin123", "系统管理员", "ADM", RoleCode.ADMIN),
    ("zhangsan", "demo123", "张伟", "RD", RoleCode.APPLICANT),
    ("lisi", "demo123", "李强", "RD", RoleCode.DEPT_MANAGER),
    ("wangwu", "demo123", "王芳", "PUR", RoleCode.BUYER),
    ("zhaoliu", "demo123", "赵敏", "WH", RoleCode.WAREHOUSE),
]

# (dept_code, manager_username, is_primary)  Q12
DEPARTMENT_MANAGERS: list[tuple[str, str, bool]] = [
    ("RD", "lisi", True),
]


def _seed(db) -> dict[str, int]:
    stats = {"departments": 0, "roles": 0, "permissions": 0, "role_permissions": 0,
             "users": 0, "dept_managers": 0}

    # --- departments -----------------------------------------------------
    dept_by_code: dict[str, Department] = {}
    for d in DEPARTMENTS:
        dept = db.execute(
            select(Department).where(Department.dept_code == d["dept_code"])
        ).scalar_one_or_none()
        if dept is None:
            dept = Department(
                dept_code=d["dept_code"],
                dept_name=d["dept_name"],
                sort_order=d["sort_order"],
                status=DeptStatus.ACTIVE,
            )
            db.add(dept)
            db.flush()
            stats["departments"] += 1
        dept_by_code[d["dept_code"]] = dept

    # --- permissions ------------------------------------------------------
    perm_by_code: dict[str, Permission] = {}
    for code, name, module in PERMISSIONS:
        perm = db.execute(
            select(Permission).where(Permission.perm_code == code)
        ).scalar_one_or_none()
        if perm is None:
            perm = Permission(perm_code=code, perm_name=name, module=module)
            db.add(perm)
            db.flush()
            stats["permissions"] += 1
        perm_by_code[code] = perm

    # --- roles -------------------------------------------------------------
    role_by_code: dict[RoleCode, Role] = {}
    for r in ROLES:
        role = db.execute(
            select(Role).where(Role.role_code == r["role_code"])
        ).scalar_one_or_none()
        if role is None:
            role = Role(
                role_code=r["role_code"],
                role_name=r["role_name"],
                description=r["description"],
                is_system=r["is_system"],
                status=ActiveStatus.ACTIVE,
            )
            db.add(role)
            db.flush()
            stats["roles"] += 1
        role_by_code[r["role_code"]] = role

    # --- role -> permission matrix (add-only) ------------------------------
    for role_code, perm_codes in ROLE_PERMISSIONS.items():
        missing = perm_codes - ALL_PERM_CODES
        if missing:
            raise ValueError(f"ROLE_PERMISSIONS 引用了未定义的权限点: {sorted(missing)}")
        role = role_by_code[role_code]
        existing = set(
            db.execute(
                select(RolePermission.permission_id).where(RolePermission.role_id == role.id)
            ).scalars().all()
        )
        for code in perm_codes:
            pid = perm_by_code[code].id
            if pid not in existing:
                db.add(RolePermission(role_id=role.id, permission_id=pid))
                stats["role_permissions"] += 1

    # --- users ---------------------------------------------------------------
    for username, password, real_name, dept_code, role_code in DEMO_USERS:
        user = db.execute(
            select(User).where(User.username == username)
        ).scalar_one_or_none()
        if user is None:
            user = User(
                username=username,
                password_hash=hash_password(password),
                real_name=real_name,
                department_id=dept_by_code[dept_code].id,
                role_id=role_by_code[role_code].id,
                status=UserStatus.ACTIVE,
            )
            db.add(user)
            db.flush()
            stats["users"] += 1

    # --- department managers (Q12) --------------------------------------------
    users_by_username = {
        u.username: u for u in db.execute(select(User)).scalars().all()
    }
    for dept_code, mgr_username, is_primary in DEPARTMENT_MANAGERS:
        dept = dept_by_code[dept_code]
        mgr = users_by_username[mgr_username]
        link = db.execute(
            select(DepartmentManager).where(
                DepartmentManager.dept_id == dept.id,
                DepartmentManager.user_id == mgr.id,
            )
        ).scalar_one_or_none()
        if link is None:
            db.add(DepartmentManager(dept_id=dept.id, user_id=mgr.id, is_primary=is_primary))
            stats["dept_managers"] += 1

    return stats


def run() -> None:
    db = SessionLocal()
    try:
        stats = _seed(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    print(f"[init_data] 完成：{stats}")
    return stats


if __name__ == "__main__":
    run()
