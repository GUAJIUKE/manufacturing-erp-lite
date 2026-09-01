"""Phase 4 RBAC CRUD tests: users / roles / departments / permission assign.

Covers the regression where list_users used ``select(User.id)`` + ``scalar_one()``
(count returned one row per user -> 500 MultipleResultsFound).
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.models import Department, OperationLog, Role, RolePermission, User
from app.utils.enums import AuditAction, RoleCode


def _login(client: TestClient, username: str = "admin", password: str = "admin123") -> str:
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["data"]["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ----------------------------------------------------------------------
# 用户
# ----------------------------------------------------------------------
def test_list_users_pagination(client: TestClient, db) -> None:
    token = _login(client)
    r = client.get("/api/v1/users?page=1&page_size=5", headers=_auth(token))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["total"] >= 5
    assert len(data["items"]) == 5
    assert data["page"] == 1
    assert data["total_pages"] >= 1
    # 反规范化字段
    first = data["items"][0]
    assert first["username"] == "admin"
    assert first["role_code"] == "ADMIN"
    assert first["department_name"] == "行政部"


def test_list_users_keyword_filter(client: TestClient) -> None:
    token = _login(client)
    r = client.get("/api/v1/users?keyword=zhang", headers=_auth(token))
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["username"] == "zhangsan"


def test_user_crud_flow(client: TestClient, db) -> None:
    token = _login(client)
    headers = _auth(token)
    role = db.execute(select(Role).where(Role.role_code == RoleCode.APPLICANT)).scalar_one()
    dept = db.execute(select(Department).where(Department.dept_code == "RD")).scalar_one()

    # 清理历史残留，保证可重复执行
    old = db.execute(select(User).where(User.username == "t_crud_user")).scalar_one_or_none()
    if old is not None:
        db.delete(old)
        db.commit()

    # create
    r = client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "username": "t_crud_user",
            "password": "pass123",
            "real_name": "CRUD测试员",
            "role_id": role.id,
            "department_id": dept.id,
        },
    )
    assert r.status_code == 200, r.text
    created = r.json()["data"]
    assert created["role_code"] == "APPLICANT"
    assert created["department_name"] == "研发部"
    uid = created["id"]

    # duplicate -> 409 USERNAME_EXISTS
    r = client.post(
        "/api/v1/users",
        headers=headers,
        json={"username": "t_crud_user", "password": "pass123", "real_name": "重复", "role_id": role.id},
    )
    assert r.status_code == 409
    assert r.json()["code"] == 3006

    # update
    r = client.put(
        f"/api/v1/users/{uid}",
        headers=headers,
        json={"real_name": "CRUD改名"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["real_name"] == "CRUD改名"

    # disable (soft delete)
    r = client.delete(f"/api/v1/users/{uid}", headers=headers)
    assert r.status_code == 200
    db.rollback()  # 结束 REPEATABLE READ 快照，才能读到 API 会话的提交
    user = db.get(User, uid)
    assert user.status.value == "DISABLED"

    # cleanup
    db.delete(user)
    db.commit()


# ----------------------------------------------------------------------
# 角色 & 权限分配
# ----------------------------------------------------------------------
def test_role_list_and_detail(client: TestClient, db) -> None:
    token = _login(client)
    headers = _auth(token)

    r = client.get("/api/v1/roles", headers=headers)
    assert r.status_code == 200
    roles = r.json()["data"]
    assert {x["role_code"] for x in roles} == {
        RoleCode.ADMIN.value,
        RoleCode.APPLICANT.value,
        RoleCode.DEPT_MANAGER.value,
        RoleCode.BUYER.value,
        RoleCode.WAREHOUSE.value,
    }
    admin_role = next(x for x in roles if x["role_code"] == "ADMIN")
    assert len(admin_role["permission_ids"]) == 48  # 44 (Phase 4) + 3 inventory_policy:* (Phase 5) + pr:reject (Phase 7)

    r = client.get(f"/api/v1/roles/{admin_role['id']}", headers=headers)
    assert r.status_code == 200
    assert r.json()["data"]["is_system"] is True


def test_delete_system_role_forbidden(client: TestClient, db) -> None:
    token = _login(client)
    admin_role = db.execute(select(Role).where(Role.role_code == RoleCode.ADMIN)).scalar_one()
    r = client.delete(f"/api/v1/roles/{admin_role.id}", headers=_auth(token))
    assert r.status_code == 409


def test_assign_permissions_replace_and_audit(client: TestClient, db) -> None:
    """替换式授权：赋相同集合（保持种子数据不变），并断言 PERMISSION_CHANGE 审计落库。"""
    token = _login(client)
    buyer = db.execute(select(Role).where(Role.role_code == RoleCode.BUYER)).scalar_one()
    before_ids = set(
        db.execute(
            select(RolePermission.permission_id).where(RolePermission.role_id == buyer.id)
        ).scalars().all()
    )
    audit_before = db.execute(
        select(func.count()).select_from(OperationLog).where(
            OperationLog.action == AuditAction.PERMISSION_CHANGE,
            OperationLog.document_id == buyer.id,
        )
    ).scalar_one()

    r = client.post(
        f"/api/v1/roles/{buyer.id}/permissions",
        headers=_auth(token),
        json={"permission_ids": sorted(before_ids)},
    )
    assert r.status_code == 200, r.text
    assert set(r.json()["data"]["permission_ids"]) == before_ids

    db.rollback()  # 结束 REPEATABLE READ 快照
    audit_after = db.execute(
        select(func.count()).select_from(OperationLog).where(
            OperationLog.action == AuditAction.PERMISSION_CHANGE,
            OperationLog.document_id == buyer.id,
        )
    ).scalar_one()
    assert audit_after == audit_before + 1


def test_assign_permissions_invalid_id(client: TestClient) -> None:
    token = _login(client)
    r = client.post(
        "/api/v1/roles/99999/permissions",
        headers=_auth(token),
        json={"permission_ids": [1, 999999]},
    )
    # 角色不存在 -> 404
    assert r.status_code == 404


# ----------------------------------------------------------------------
# 部门
# ----------------------------------------------------------------------
def test_department_crud_flow(client: TestClient, db) -> None:
    token = _login(client)
    headers = _auth(token)

    old = db.execute(select(Department).where(Department.dept_code == "TST")).scalar_one_or_none()
    if old is not None:
        db.delete(old)
        db.commit()

    # create
    r = client.post(
        "/api/v1/departments",
        headers=headers,
        json={"dept_code": "TST", "dept_name": "测试部", "sort_order": 99},
    )
    assert r.status_code == 200, r.text
    dept_id = r.json()["data"]["id"]

    # duplicate code -> 409
    r = client.post(
        "/api/v1/departments",
        headers=headers,
        json={"dept_code": "TST", "dept_name": "重复", "sort_order": 1},
    )
    assert r.status_code == 409
    assert r.json()["code"] == 3007

    # update
    r = client.put(f"/api/v1/departments/{dept_id}", headers=headers, json={"dept_name": "测试部改名"})
    assert r.status_code == 200
    assert r.json()["data"]["dept_name"] == "测试部改名"

    # disable (soft delete)
    r = client.delete(f"/api/v1/departments/{dept_id}", headers=headers)
    assert r.status_code == 200

    # cleanup
    db.rollback()  # 结束 REPEATABLE READ 快照
    dept = db.get(Department, dept_id)
    db.delete(dept)
    db.commit()


def test_disable_department_with_users_forbidden(client: TestClient, db) -> None:
    token = _login(client)
    rd = db.execute(select(Department).where(Department.dept_code == "RD")).scalar_one()
    r = client.delete(f"/api/v1/departments/{rd.id}", headers=_auth(token))
    assert r.status_code == 409  # 研发部下有用户，不可停用
