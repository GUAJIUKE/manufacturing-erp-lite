"""Phase 12 coverage hardening: RBAC edge branches.

Baseline run showed role_service 55% / department_service 68%. The RoleCode
enum is closed at both API and DB level (native ENUM over the five seeded
codes), so create/delete *success* branches of role_service are unreachable by
design — role set is fixed and extensibility lives in permission assignment.
This file covers every reachable branch that was missing:
  - role create duplicate-code conflict (409) + invalid enum code (422)
  - role update (rename) with restore
  - assign_permissions with a missing permission id -> 404 (+ rollback safety)
  - department parent-child create, self-parent loop (409), missing parent (404)
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import Department, Role
from app.utils.enums import DeptStatus, RoleCode


def _login(client: TestClient, username: str = "admin", password: str = "admin123") -> str:
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["data"]["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _role(client: TestClient, headers: dict, code: RoleCode) -> dict:
    roles = client.get("/api/v1/roles", headers=headers).json()["data"]
    return next(x for x in roles if x["role_code"] == code.value)


# ----------------------------------------------------------------------
# 角色：闭合枚举下的可达分支
# ----------------------------------------------------------------------
def test_role_create_duplicate_code_conflict_and_invalid_enum(client: TestClient) -> None:
    h = _auth(_login(client))

    # 重复编码 -> 409（create_role 的存在性检查分支）
    r = client.post("/api/v1/roles", headers=h, json={
        "role_code": "BUYER", "role_name": "重复采购员", "description": "P12",
    })
    assert r.status_code == 409, r.text

    # 枚举外编码 -> 422（RoleCode 闭合枚举在 schema 层拒绝）
    r = client.post("/api/v1/roles", headers=h, json={
        "role_code": "HACKER", "role_name": "非法角色",
    })
    assert r.status_code == 422


def test_role_update_rename_then_restore(client: TestClient) -> None:
    h = _auth(_login(client))
    buyer = _role(client, h, RoleCode.BUYER)
    original = buyer["role_name"]

    r = client.put(f"/api/v1/roles/{buyer['id']}", headers=h,
                   json={"role_name": f"{original}-P12临时", "description": "P12 覆盖测试"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["role_name"] == f"{original}-P12临时"

    # 还原，避免污染其他测试/演示语义
    r = client.put(f"/api/v1/roles/{buyer['id']}", headers=h, json={"role_name": original})
    assert r.status_code == 200 and r.json()["data"]["role_name"] == original


def test_assign_permissions_missing_permission_id_404_and_rollback(client: TestClient, db) -> None:
    """合法角色 + 不存在权限点 -> 404；且先删后抛的删除必须随事务回滚。"""
    h = _auth(_login(client))
    buyer = _role(client, h, RoleCode.BUYER)
    before = set(buyer["permission_ids"])

    r = client.post(f"/api/v1/roles/{buyer['id']}/permissions", headers=h,
                    json={"permission_ids": sorted(before) + [999999]})
    assert r.status_code == 404, r.text

    db.rollback()
    role = db.execute(select(Role).where(Role.id == buyer["id"])).scalar_one()
    perms = {p.id for p in role.permissions}
    assert perms == before  # _replace_permissions 先 DELETE 后抛 NotFound，事务回滚保住原集合


# ----------------------------------------------------------------------
# 部门：parent / self-loop / missing-parent / status filter
# ----------------------------------------------------------------------
def test_department_parent_child_self_loop_missing_parent_and_filter(client: TestClient, db) -> None:
    h = _auth(_login(client))

    # 清理历史残留，保证可重复执行
    for code in ("P12P", "P12C", "P12X"):
        old = db.execute(select(Department).where(Department.dept_code == code)).scalar_one_or_none()
        if old is not None:
            db.delete(old)
            db.commit()

    # create parent -> create child（覆盖 parent_id 分支）
    r = client.post("/api/v1/departments", headers=h,
                    json={"dept_code": "P12P", "dept_name": "P12 一级部门", "sort_order": 1})
    assert r.status_code == 200, r.text
    parent_id = r.json()["data"]["id"]
    r = client.post("/api/v1/departments", headers=h,
                    json={"dept_code": "P12C", "dept_name": "P12 子部门",
                          "parent_id": parent_id, "sort_order": 2})
    assert r.status_code == 200, r.text
    child_id = r.json()["data"]["id"]
    assert r.json()["data"]["parent_id"] == parent_id

    # self-loop -> 409（部门不能作为自己的上级）
    r = client.put(f"/api/v1/departments/{child_id}", headers=h, json={"parent_id": child_id})
    assert r.status_code == 409, r.text

    # missing parent -> 404（不产生脏行）
    r = client.post("/api/v1/departments", headers=h,
                    json={"dept_code": "P12X", "dept_name": "P12 孤儿部门", "parent_id": 999999})
    assert r.status_code == 404, r.text

    # 软删除（停用）后 status 筛选可见
    r = client.delete(f"/api/v1/departments/{child_id}", headers=h)
    assert r.status_code == 200
    r = client.get("/api/v1/departments?status=INACTIVE", headers=h)
    assert any(x["id"] == child_id for x in r.json()["data"])

    # 直接库删，恢复现场
    db.rollback()
    for code in ("P12C", "P12P"):
        row = db.execute(select(Department).where(Department.dept_code == code)).scalar_one_or_none()
        if row is not None:
            db.delete(row)
            db.commit()
