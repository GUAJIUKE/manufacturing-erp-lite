"""Phase 6 purchase-requisition tests.

Covers the acceptance list from the Phase 6 spec (§十六) plus concurrency
guards: daily PR numbering uniqueness, concurrent submit atomicity,
optimistic-lock 409, audit rows, object-level permission rules, and the
server-owned-field invariants (applicant/department snapshot, money
recalculation). The full old suite must keep passing (run via pytest).
"""

from __future__ import annotations

import re
import threading
from datetime import date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db.session import SessionLocal
from app.models import (
    Department,
    OperationLog,
    PurchaseRequisition,
    PurchaseRequisitionItem,
    User,
)
from app.utils.enums import AuditAction

PR_NO_RE = re.compile(r"^PR-\d{8}-\d{4}$")

# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _login(client: TestClient, username: str = "admin", password: str = "admin123") -> str:
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["data"]["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _clean_prs() -> None:
    """API sessions commit outside the test fixture's transaction; wipe the
    PR tables before each test so runs are repeatable (never touch
    number_sequences — daily PR counters are monotonic, Phase 5 lesson)."""
    with SessionLocal() as s:
        s.execute(delete(PurchaseRequisitionItem))
        s.execute(delete(PurchaseRequisition))
        s.commit()


def _create_material(client: TestClient, headers: dict, name: str = "PR测试电阻") -> dict:
    r = client.post("/api/v1/materials", headers=headers, json={"material_name": name, "unit": "pcs"})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _disable_material(client: TestClient, headers: dict, material_id: int) -> None:
    r = client.post(f"/api/v1/materials/{material_id}/disable", headers=headers)
    assert r.status_code == 200, r.text


def _mk_pr(client: TestClient, headers: dict, material_id: int, qty="10", price="12.3456", **kw) -> dict:
    payload = {"items": [{"material_id": material_id, "requested_quantity": qty,
                          "estimated_unit_price": price}], **kw}
    r = client.post("/api/v1/purchase-requisitions", headers=headers, json=payload)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _audit_actions(client: TestClient, pr_no: str) -> set[str]:
    with SessionLocal() as s:
        s.rollback()  # 结束 REPEATABLE READ 快照，看到 API 会话新提交
        rows = s.execute(
            select(OperationLog.action).where(OperationLog.document_no == pr_no)
        ).scalars().all()
    return {a.value for a in rows}


# ----------------------------------------------------------------------
# 创建：编码 / 服务端字段 / 金额
# ----------------------------------------------------------------------
def test_create_pr_success_and_auto_numbering(client: TestClient, db) -> None:
    _clean_prs()
    h = _auth(_login(client, "zhangsan", "demo123"))
    mid = _create_material(client, _auth(_login(client)))["id"]  # 物料需 material:create（admin）
    pr = _mk_pr(client, h, mid)
    assert PR_NO_RE.fullmatch(pr["pr_no"])
    assert pr["status"] == "DRAFT"
    assert pr["version"] == 1
    assert pr["submitted_at"] is None


def test_pr_numbering_unique_across_creations(client: TestClient, db) -> None:
    _clean_prs()
    h = _auth(_login(client, "zhangsan", "demo123"))
    mid = _create_material(client, _auth(_login(client)))["id"]
    nos = {_mk_pr(client, h, mid)["pr_no"] for _ in range(3)}
    assert len(nos) == 3  # 每天 0001 起，单调递增，DB UNIQUE 兜底


def test_applicant_and_department_are_snapshot_not_client_fields(client: TestClient, db) -> None:
    """客户端伪造 applicant_id/department_id 无效；部门为创建时快照。"""
    _clean_prs()
    zhang_token = _auth(_login(client, "zhangsan", "demo123"))
    mid = _create_material(client, _auth(_login(client)))["id"]
    # 客户端塞 applicant_id / department_id / status / pr_no —— schema 无此字段，全部忽略
    r = client.post("/api/v1/purchase-requisitions", headers=zhang_token, json={
        "applicant_id": 999, "department_id": 999, "status": "PENDING", "pr_no": "FAKE-001",
        "items": [{"material_id": mid, "requested_quantity": "1", "estimated_unit_price": "1"}],
    })
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["applicant_id"] == 2  # zhangsan
    assert d["status"] == "DRAFT"
    assert d["pr_no"] != "FAKE-001"
    # 部门快照：改用户当前部门后，历史 PR.department_id 不变
    with SessionLocal() as s:
        u = s.get(User, 2)
        orig_dept = u.department_id
        u.department_id = 4  # 调岗到其他部门
        s.commit()
    try:
        with SessionLocal() as s:
            pr = s.get(PurchaseRequisition, d["id"])
            assert pr.department_id == orig_dept
    finally:
        with SessionLocal() as s:
            u = s.get(User, 2)
            u.department_id = orig_dept
            s.commit()


def test_create_with_disabled_material_fails(client: TestClient, db) -> None:
    _clean_prs()
    h = _auth(_login(client))
    mid = _create_material(client, h)["id"]
    _disable_material(client, h, mid)
    r = client.post("/api/v1/purchase-requisitions", headers=_auth(_login(client, "zhangsan", "demo123")),
                    json={"items": [{"material_id": mid, "requested_quantity": "1", "estimated_unit_price": "1"}]})
    assert r.status_code == 409
    assert r.json()["code"] == 3009  # MASTER_DATA_DISABLED


def test_create_quantity_non_positive_fails(client: TestClient, db) -> None:
    _clean_prs()
    h = _auth(_login(client))
    mid = _create_material(client, h)["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    for qty in ("0", "-1"):
        r = client.post("/api/v1/purchase-requisitions", headers=z,
                        json={"items": [{"material_id": mid, "requested_quantity": qty,
                                         "estimated_unit_price": "1"}]})
        assert r.status_code == 422, (qty, r.text)


def test_create_negative_price_fails(client: TestClient, db) -> None:
    _clean_prs()
    h = _auth(_login(client))
    mid = _create_material(client, h)["id"]
    r = client.post("/api/v1/purchase-requisitions", headers=_auth(_login(client, "zhangsan", "demo123")),
                    json={"items": [{"material_id": mid, "requested_quantity": "1",
                                     "estimated_unit_price": "-0.01"}]})
    assert r.status_code == 422


def test_create_without_items_fails(client: TestClient, db) -> None:
    """至少 1 条明细（Phase 6 §五.3 偏好：业务单据不允许空单创建）。"""
    _clean_prs()
    r = client.post("/api/v1/purchase-requisitions", headers=_auth(_login(client, "zhangsan", "demo123")),
                    json={"items": []})
    assert r.status_code == 422


def test_amounts_server_computed_with_half_up(client: TestClient, db) -> None:
    """金额服务端重算：10 × 12.3456 = 123.456 → ROUND_HALF_UP → 123.46。"""
    _clean_prs()
    h = _auth(_login(client))
    mid = _create_material(client, h)["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pr(client, z, mid, qty="10", price="12.3456")
    assert pr["items"][0]["estimated_amount"] == "123.46"
    assert pr["total_estimated_amount"] == "123.46"
    # 半进位：1 × 0.005 → 0.005 → 0.01
    pr2 = _mk_pr(client, z, mid, qty="1", price="0.005")
    assert pr2["items"][0]["estimated_amount"] == "0.01"
    assert pr2["total_estimated_amount"] == "0.01"
    # 汇总：5×2 + 3×1.5 = 14.50
    r = client.post("/api/v1/purchase-requisitions", headers=z, json={"items": [
        {"material_id": mid, "requested_quantity": "5", "estimated_unit_price": "2"},
        {"material_id": mid, "requested_quantity": "3", "estimated_unit_price": "1.5"}]})
    d = r.json()["data"]
    assert d["total_estimated_amount"] == "14.50"
    assert [i["estimated_amount"] for i in d["items"]] == ["10.00", "4.50"]


def test_decimal_precision_stored_exact(client: TestClient, db) -> None:
    """DB 层 Decimal 精度：18,4 数量/单价 × 18,2 金额，无浮点误差。"""
    _clean_prs()
    h = _auth(_login(client))
    mid = _create_material(client, h)["id"]
    pr = _mk_pr(client, _auth(_login(client, "zhangsan", "demo123")), mid, qty="0.3333", price="9.9999")
    # 0.3333 × 9.9999 = 3.33296667 → 3.33
    assert pr["items"][0]["estimated_amount"] == "3.33"
    assert pr["total_estimated_amount"] == "3.33"


# ----------------------------------------------------------------------
# 编辑
# ----------------------------------------------------------------------
def test_edit_draft_success_recomputes_amounts(client: TestClient, db) -> None:
    _clean_prs()
    z = _auth(_login(client, "zhangsan", "demo123"))
    mid = _create_material(client, _auth(_login(client)))["id"]
    pr = _mk_pr(client, z, mid, qty="10", price="1")
    r = client.put(f"/api/v1/purchase-requisitions/{pr['id']}", headers=z, json={
        "version": 1, "reason": "改后",
        "items": [{"id": pr["items"][0]["id"], "material_id": mid, "requested_quantity": "5",
                   "estimated_unit_price": "2"},
                  {"material_id": mid, "requested_quantity": "3", "estimated_unit_price": "1.5"}],
    })
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["version"] == 2
    assert d["reason"] == "改后"
    assert d["total_estimated_amount"] == "14.50"
    assert len(d["items"]) == 2
    assert [i["line_no"] for i in d["items"]] == [1, 2]
    # 删除：不再引用的明细被移除
    r2 = client.put(f"/api/v1/purchase-requisitions/{pr['id']}", headers=z, json={
        "version": 2,
        "items": [{"id": d["items"][0]["id"], "material_id": mid, "requested_quantity": "2",
                   "estimated_unit_price": "1"}]})
    d2 = r2.json()["data"]
    assert d2["version"] == 3 and len(d2["items"]) == 1
    assert d2["total_estimated_amount"] == "2.00"


def test_edit_pending_fails(client: TestClient, db) -> None:
    _clean_prs()
    z = _auth(_login(client, "zhangsan", "demo123"))
    mid = _create_material(client, _auth(_login(client)))["id"]
    pr = _mk_pr(client, z, mid)
    client.post(f"/api/v1/purchase-requisitions/{pr['id']}/submit", headers=z)
    r = client.put(f"/api/v1/purchase-requisitions/{pr['id']}", headers=z, json={
        "version": 2, "items": [{"material_id": mid, "requested_quantity": "1",
                                 "estimated_unit_price": "1"}]})
    assert r.status_code == 409
    assert r.json()["code"] == 4003  # PR_NOT_EDITABLE


def test_cannot_edit_others_pr(client: TestClient, db) -> None:
    _clean_prs()
    z = _auth(_login(client, "zhangsan", "demo123"))
    mid = _create_material(client, _auth(_login(client)))["id"]
    pr = _mk_pr(client, z, mid)  # zhangsan 创建
    # lisi（DEPT_MANAGER，有 pr:update 权限点）也不能改别人的 PR → 对象级 403
    lisi = _auth(_login(client, "lisi", "demo123"))
    r = client.put(f"/api/v1/purchase-requisitions/{pr['id']}", headers=lisi, json={
        "version": 1, "items": [{"material_id": mid, "requested_quantity": "1",
                                 "estimated_unit_price": "1"}]})
    assert r.status_code == 403
    # admin 有管理能力
    r2 = client.put(f"/api/v1/purchase-requisitions/{pr['id']}", headers=_auth(_login(client)), json={
        "version": 1, "items": [{"id": pr["items"][0]["id"], "material_id": mid,
                                 "requested_quantity": "2", "estimated_unit_price": "1"}]})
    assert r2.status_code == 200


def test_update_rollback_on_invalid_item(client: TestClient, db) -> None:
    """Header + Items 同事务：任一明细非法 → 全部回滚（version/金额不变）。"""
    _clean_prs()
    z = _auth(_login(client, "zhangsan", "demo123"))
    h = _auth(_login(client))
    mid = _create_material(client, h)["id"]
    mid2 = _create_material(client, h, "PR测试电阻B")["id"]
    pr = _mk_pr(client, z, mid, qty="10", price="1")
    _disable_material(client, h, mid2)  # 新增行引用停用物料 → 触发失败
    r = client.put(f"/api/v1/purchase-requisitions/{pr['id']}", headers=z, json={
        "version": 1, "reason": "不应生效",
        "items": [{"id": pr["items"][0]["id"], "material_id": mid, "requested_quantity": "5",
                   "estimated_unit_price": "2"},
                  {"material_id": mid2, "requested_quantity": "1", "estimated_unit_price": "1"}]})
    assert r.status_code == 409
    assert r.json()["code"] == 3009
    with SessionLocal() as s:
        s.rollback()
        pr_db = s.get(PurchaseRequisition, pr["id"])
        assert pr_db.version == 1
        assert pr_db.reason != "不应生效"
        assert pr_db.total_estimated_amount == Decimal("10.00")
        assert len(list(pr_db.items)) == 1  # 第二条未插入


def test_update_stale_version_conflict_409(client: TestClient, db) -> None:
    _clean_prs()
    z = _auth(_login(client, "zhangsan", "demo123"))
    mid = _create_material(client, _auth(_login(client)))["id"]
    pr = _mk_pr(client, z, mid)
    # 第一次更新 version 1 → 2
    r1 = client.put(f"/api/v1/purchase-requisitions/{pr['id']}", headers=z, json={
        "version": 1, "items": [{"id": pr["items"][0]["id"], "material_id": mid,
                                 "requested_quantity": "2", "estimated_unit_price": "1"}]})
    assert r1.status_code == 200
    # 再拿旧 version=1 更新 → 409（模拟两个页面同时编辑）
    r2 = client.put(f"/api/v1/purchase-requisitions/{pr['id']}", headers=z, json={
        "version": 1, "items": [{"id": pr["items"][0]["id"], "material_id": mid,
                                 "requested_quantity": "9", "estimated_unit_price": "9"}]})
    assert r2.status_code == 409
    assert "已" in r2.json()["message"]  # "单据已被其他操作修改，请刷新后重试"


# ----------------------------------------------------------------------
# 提交 / 取消 / 状态机
# ----------------------------------------------------------------------
def test_submit_draft_to_pending(client: TestClient, db) -> None:
    _clean_prs()
    z = _auth(_login(client, "zhangsan", "demo123"))
    mid = _create_material(client, _auth(_login(client)))["id"]
    pr = _mk_pr(client, z, mid)
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/submit", headers=z)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["status"] == "PENDING"
    assert d["submitted_at"] is not None
    assert d["version"] == 2
    assert d["total_estimated_amount"] == "123.46"  # 提交前重算金额


def test_submit_empty_items_fails(client: TestClient, db) -> None:
    _clean_prs()
    z = _auth(_login(client, "zhangsan", "demo123"))
    # 绕过 schema（min_length=1）直接造空单，验证 Service 层兜底
    with SessionLocal() as s:
        s.add(PurchaseRequisition(pr_no="PR-20990101-9999", applicant_id=2, department_id=1,
                                  apply_date=date(2099, 1, 1), status="DRAFT",
                                  total_estimated_amount=Decimal("0"), version=1))
        s.commit()
        pr_id = s.execute(
            select(PurchaseRequisition).where(PurchaseRequisition.pr_no == "PR-20990101-9999")
        ).scalar_one().id
    r = client.post(f"/api/v1/purchase-requisitions/{pr_id}/submit", headers=z)
    assert r.status_code == 409
    assert r.json()["code"] == 4004  # PR_EMPTY_ITEMS


def test_submit_with_disabled_material_fails(client: TestClient, db) -> None:
    _clean_prs()
    z = _auth(_login(client, "zhangsan", "demo123"))
    h = _auth(_login(client))
    mid = _create_material(client, h)["id"]
    pr = _mk_pr(client, z, mid)
    _disable_material(client, h, mid)  # 创建后停用物料
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/submit", headers=z)
    assert r.status_code == 409
    assert r.json()["code"] == 3009
    with SessionLocal() as s:
        s.rollback()
        assert s.get(PurchaseRequisition, pr["id"]).status.value == "DRAFT"  # 仍为 DRAFT


def test_resubmit_fails(client: TestClient, db) -> None:
    _clean_prs()
    z = _auth(_login(client, "zhangsan", "demo123"))
    mid = _create_material(client, _auth(_login(client)))["id"]
    pr = _mk_pr(client, z, mid)
    client.post(f"/api/v1/purchase-requisitions/{pr['id']}/submit", headers=z)
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/submit", headers=z)
    assert r.status_code == 409
    assert r.json()["code"] == 4002  # PR_INVALID_STATUS_TRANSITION


def test_cancel_draft(client: TestClient, db) -> None:
    _clean_prs()
    z = _auth(_login(client, "zhangsan", "demo123"))
    mid = _create_material(client, _auth(_login(client)))["id"]
    pr = _mk_pr(client, z, mid)
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/cancel", headers=z)
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "CANCELLED"
    assert r.json()["data"]["version"] == 2


def test_cancelled_cannot_submit_or_edit(client: TestClient, db) -> None:
    _clean_prs()
    z = _auth(_login(client, "zhangsan", "demo123"))
    mid = _create_material(client, _auth(_login(client)))["id"]
    pr = _mk_pr(client, z, mid)
    client.post(f"/api/v1/purchase-requisitions/{pr['id']}/cancel", headers=z)
    s1 = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/submit", headers=z)
    assert s1.status_code == 409 and s1.json()["code"] == 4002
    e1 = client.put(f"/api/v1/purchase-requisitions/{pr['id']}", headers=z, json={
        "version": 2, "items": [{"material_id": mid, "requested_quantity": "1",
                                 "estimated_unit_price": "1"}]})
    assert e1.status_code == 409 and e1.json()["code"] == 4003


def test_invalid_transition_rejected(client: TestClient, db) -> None:
    """PENDING -> CANCELLED 不在 Phase 6 转换表内 → 409（Phase 7 才支持审批后取消）。"""
    _clean_prs()
    z = _auth(_login(client, "zhangsan", "demo123"))
    mid = _create_material(client, _auth(_login(client)))["id"]
    pr = _mk_pr(client, z, mid)
    client.post(f"/api/v1/purchase-requisitions/{pr['id']}/submit", headers=z)
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/cancel", headers=z)
    assert r.status_code == 409
    assert r.json()["code"] == 4002


def test_concurrent_submit_single_success(client: TestClient, db) -> None:
    """并发 submit：恰好 1 个成功，其余 409（原子状态条件更新）。"""
    _clean_prs()
    z = _auth(_login(client, "zhangsan", "demo123"))
    mid = _create_material(client, _auth(_login(client)))["id"]
    pr = _mk_pr(client, z, mid)
    results: list[int] = []

    def _submit() -> None:
        r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/submit", headers=z)
        results.append(r.status_code)

    threads = [threading.Thread(target=_submit) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(200) == 1, results
    assert results.count(409) == 7, results


def test_concurrent_pr_numbering_unique(client: TestClient, db) -> None:
    """8 线程 × 5 并发创建 → 40 个 PR 编号无重复（DB 级并发安全）。"""
    _clean_prs()
    z = _auth(_login(client, "zhangsan", "demo123"))
    mid = _create_material(client, _auth(_login(client)))["id"]
    nos: list[str] = []
    lock = threading.Lock()

    def _create() -> None:
        for _ in range(5):  # 8 线程 × 5 次 = 40 个 PR
            r = client.post("/api/v1/purchase-requisitions", headers=z, json={
                "items": [{"material_id": mid, "requested_quantity": "1", "estimated_unit_price": "1"}]})
            assert r.status_code == 200, r.text
            with lock:
                nos.append(r.json()["data"]["pr_no"])

    threads = [threading.Thread(target=_create) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(nos) == 40
    assert len(set(nos)) == 40
    assert all(PR_NO_RE.fullmatch(n) for n in nos)


# ----------------------------------------------------------------------
# 权限（RBAC 第一层 + 对象级第二层）
# ----------------------------------------------------------------------
def test_rbac_forbidden_for_buyer_and_warehouse(client: TestClient, db) -> None:
    _clean_prs()
    buyer = _auth(_login(client, "wangwu", "demo123"))   # BUYER：无 pr:create
    wh = _auth(_login(client, "zhaoliu", "demo123"))     # WAREHOUSE：无 pr:view/create
    mid = _create_material(client, _auth(_login(client)))["id"]
    r = client.post("/api/v1/purchase-requisitions", headers=buyer, json={
        "items": [{"material_id": mid, "requested_quantity": "1", "estimated_unit_price": "1"}]})
    assert r.status_code == 403
    r2 = client.post("/api/v1/purchase-requisitions", headers=wh, json={
        "items": [{"material_id": mid, "requested_quantity": "1", "estimated_unit_price": "1"}]})
    assert r2.status_code == 403
    r3 = client.get("/api/v1/purchase-requisitions", headers=wh)
    assert r3.status_code == 403  # WAREHOUSE 无 pr:view
    r4 = client.get("/api/v1/purchase-requisitions", headers=buyer)
    assert r4.status_code == 200  # BUYER 有 pr:view


def test_applicant_list_isolation_and_admin_all(client: TestClient, db) -> None:
    _clean_prs()
    z = _auth(_login(client, "zhangsan", "demo123"))
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    _mk_pr(client, z, mid)
    _mk_pr(client, z, mid)
    _mk_pr(client, admin, mid)  # admin 创建 1 单
    lsz = client.get("/api/v1/purchase-requisitions", headers=z)
    lsa = client.get("/api/v1/purchase-requisitions", headers=admin)
    assert lsz.json()["data"]["total"] == 2  # 申请人只看自己的
    assert lsa.json()["data"]["total"] == 3  # 管理员看全部


# ----------------------------------------------------------------------
# 列表筛选
# ----------------------------------------------------------------------
def test_list_filters(client: TestClient, db) -> None:
    _clean_prs()
    z = _auth(_login(client, "zhangsan", "demo123"))
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    p1 = _mk_pr(client, z, mid, qty="1", price="1")
    _mk_pr(client, z, mid, qty="2", price="2")
    r = client.get("/api/v1/purchase-requisitions", headers=admin, params={"pr_no": p1["pr_no"]})
    assert r.status_code == 200 and r.json()["data"]["total"] == 1
    r = client.get("/api/v1/purchase-requisitions", headers=admin, params={"applicant": "张伟"})
    assert r.json()["data"]["total"] == 2  # real_name 模糊
    r = client.get("/api/v1/purchase-requisitions", headers=admin, params={"applicant": "zhangsan"})
    assert r.json()["data"]["total"] == 2  # username 模糊
    r = client.get("/api/v1/purchase-requisitions", headers=admin, params={"status": "DRAFT"})
    assert r.json()["data"]["total"] == 2
    r = client.get("/api/v1/purchase-requisitions", headers=admin, params={"status": "PENDING"})
    assert r.json()["data"]["total"] == 0
    r = client.get("/api/v1/purchase-requisitions", headers=admin,
                   params={"apply_date_from": "2026-01-01", "apply_date_to": "2026-12-31"})
    assert r.json()["data"]["total"] == 2


# ----------------------------------------------------------------------
# 审计
# ----------------------------------------------------------------------
def test_audit_create_update_submit_cancel(client: TestClient, db) -> None:
    _clean_prs()
    z = _auth(_login(client, "zhangsan", "demo123"))
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    pr = _mk_pr(client, z, mid)
    actions = _audit_actions(client, pr["pr_no"])
    assert AuditAction.PR_CREATE.value in actions

    client.put(f"/api/v1/purchase-requisitions/{pr['id']}", headers=z, json={
        "version": 1, "items": [{"id": pr["items"][0]["id"], "material_id": mid,
                                 "requested_quantity": "2", "estimated_unit_price": "1"}]})
    assert AuditAction.PR_UPDATE.value in _audit_actions(client, pr["pr_no"])

    client.post(f"/api/v1/purchase-requisitions/{pr['id']}/submit", headers=z)
    assert AuditAction.PR_SUBMIT.value in _audit_actions(client, pr["pr_no"])

    pr2 = _mk_pr(client, z, mid)
    client.post(f"/api/v1/purchase-requisitions/{pr2['id']}/cancel", headers=z)
    assert AuditAction.PR_CANCEL.value in _audit_actions(client, pr2["pr_no"])

    # GET 不审计
    with SessionLocal() as s:
        s.rollback()
        cnt = s.execute(
            select(OperationLog).where(
                OperationLog.document_no == pr["pr_no"],
                OperationLog.action.in_([AuditAction.PR_CREATE, AuditAction.PR_UPDATE,
                                         AuditAction.PR_SUBMIT]),
            )
        ).scalars().all()
    assert len(cnt) == 3
