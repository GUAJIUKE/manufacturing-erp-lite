"""Stock reconciliation tests (Reality Hardening Sprint 1 / Implementation A).

Covers Design v2 core: snapshot creation, DRAFT edit semantics, submit /
approve(=post) / reject state machine, RBAC permission points, SoD with
ADMIN override, version CAS, double-approve concurrency, Snapshot Guard
(quantity AND total_amount staleness, OQ-12), Receipt-vs-reconciliation
staleness, multi-material atomic rollback, zero-difference and zero-balance
posting, ADJUST_IN explicit valuation (DA-002 / T-48 / T-49), inactive master
data completion, signed-ledger / append-only invariants, balance
reconciliation and the audit trail.

Helper users (from init_data):
- zhangsan APPLICANT, lisi DEPT_MANAGER, wangwu BUYER, zhaoliu WAREHOUSE,
  admin ADMIN.
"""

from __future__ import annotations

import re
import threading
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import SessionLocal
from app.models import (
    InventoryBalance,
    InventoryTransaction,
    Material,
    OperationLog,
    StockReconciliation,
    StockReconciliationItem,
    User,
)
from app.utils.enums import AuditAction, TxnSourceType, TxnType

from cleanup_helper import wipe_business_data


# ----------------------------------------------------------------------
# helpers (PR -> Approval -> PO -> Receipt chain to seed stock)
# ----------------------------------------------------------------------
def _login(client: TestClient, username: str = "admin", password: str = "admin123") -> str:
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["data"]["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _clean_all() -> None:
    wipe_business_data()


def _wh_headers(client: TestClient) -> dict[str, str]:
    return _auth(_login(client, "zhaoliu", "demo123"))


def _create_material(client: TestClient, headers: dict, name: str = "盘点测试物料") -> dict:
    r = client.post("/api/v1/materials", headers=headers, json={"material_name": name, "unit": "pcs"})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _create_supplier(client: TestClient, headers: dict, name: str = "盘点测试供应商") -> dict:
    r = client.post("/api/v1/suppliers", headers=headers, json={"supplier_name": name})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _create_warehouse(client: TestClient, headers: dict, name: str = "盘点测试仓") -> dict:
    r = client.post("/api/v1/warehouses", headers=headers, json={"warehouse_name": name})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _mk_pr(client: TestClient, headers: dict, material_id: int, qty: str, price: str) -> dict:
    r = client.post("/api/v1/purchase-requisitions", headers=headers, json={
        "items": [{"material_id": material_id, "requested_quantity": qty,
                   "estimated_unit_price": price}],
    })
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _mk_approved_pr(client: TestClient, material_id: int, qty: str = "100",
                    price: str = "10.0000") -> dict:
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pr(client, z, material_id, qty, price)
    submitted = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/submit",
                            headers=z)
    assert submitted.status_code == 200, submitted.text
    lisi = _auth(_login(client, "lisi", "demo123"))
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/approve",
                    headers=lisi, json={"version": submitted.json()["data"]["version"]})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _mk_confirmed_po(client: TestClient, material_id: int, supplier_id: int,
                     qty: str = "100", price: str = "10.0000") -> dict:
    pr = _mk_approved_pr(client, material_id, qty, price)
    pr_line = pr["items"][0]
    b = _auth(_login(client, "wangwu", "demo123"))
    r = client.post("/api/v1/purchase-orders", headers=b, json={
        "supplier_id": supplier_id,
        "items": [{
            "material_id": material_id,
            "ordered_quantity": qty,
            "unit_price": price,
            "sources": [{"pr_item_id": pr_line["id"], "quantity": qty}],
        }],
    })
    assert r.status_code == 200, r.text
    po = r.json()["data"]
    c = client.post(f"/api/v1/purchase-orders/{po['id']}/confirm", headers=b,
                    json={"version": po["version"]})
    assert c.status_code == 200, c.text
    return c.json()["data"]


def _post_receipt(client: TestClient, wh_h: dict, po_id: int, warehouse_id: int,
                  items: list[dict]):
    return client.post("/api/v1/purchase-receipts", headers=wh_h,
                       json={"po_id": po_id, "warehouse_id": warehouse_id, "items": items})


def _seed_balance(client: TestClient, warehouse_id: int, material_id: int,
                  qty: str = "100", price: str = "10.0000") -> None:
    """Full PR->PO->Receipt chain to put ``qty`` @ ``price`` into the warehouse."""
    po = _mk_confirmed_po(client, material_id, _supplier_of(client), qty, price)
    r = _post_receipt(client, _wh_headers(client), po["id"], warehouse_id,
                      [{"po_item_id": po["items"][0]["id"], "received_quantity": qty}])
    assert r.status_code == 200, r.text


def _supplier_of(client: TestClient) -> int:
    """Reuse/create one supplier shared across seeds within a test."""
    return _create_supplier(client, _auth(_login(client)))["id"]


# ----------------------------------------------------------------------
# reconciliation helpers
# ----------------------------------------------------------------------
def _create_recon(client: TestClient, headers: dict, warehouse_id: int,
                  items: list[dict], **kw):
    return client.post("/api/v1/stock-reconciliations", headers=headers,
                       json={"warehouse_id": warehouse_id, "items": items, **kw})


def _put_recon(client: TestClient, headers: dict, doc_id: int, version: int,
               items: list[dict], **kw):
    return client.put(f"/api/v1/stock-reconciliations/{doc_id}", headers=headers,
                      json={"version": version, "items": items, **kw})


def _submit_recon(client: TestClient, headers: dict, doc_id: int, version: int):
    return client.post(f"/api/v1/stock-reconciliations/{doc_id}/submit",
                       headers=headers, json={"version": version})


def _approve_recon(client: TestClient, headers: dict, doc_id: int, **kw):
    return client.post(f"/api/v1/stock-reconciliations/{doc_id}/approve",
                       headers=headers, json=kw)


def _reject_recon(client: TestClient, headers: dict, doc_id: int, comment: str):
    return client.post(f"/api/v1/stock-reconciliations/{doc_id}/reject",
                       headers=headers, json={"comment": comment})


def _recon_detail(client: TestClient, headers: dict, doc_id: int) -> dict:
    r = client.get(f"/api/v1/stock-reconciliations/{doc_id}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _balance(warehouse_id: int, material_id: int) -> dict | None:
    with SessionLocal() as s:
        s.rollback()
        b = s.execute(
            select(InventoryBalance).where(
                InventoryBalance.warehouse_id == warehouse_id,
                InventoryBalance.material_id == material_id,
            )
        ).scalar_one_or_none()
        if b is None:
            return None
        return {"quantity": b.quantity, "total_amount": b.total_amount,
                "average_unit_cost": b.average_unit_cost}


def _adjust_txns(material_id: int) -> list[InventoryTransaction]:
    with SessionLocal() as s:
        s.rollback()
        rows = s.execute(
            select(InventoryTransaction)
            .where(
                InventoryTransaction.material_id == material_id,
                InventoryTransaction.source_type == TxnSourceType.STOCK_RECONCILIATION,
            )
            .order_by(InventoryTransaction.id)
        ).scalars().all()
        return list(rows)


def _count(model) -> int:
    with SessionLocal() as s:
        s.rollback()
        return len(s.execute(select(model)).scalars().all())


def _audit_actions(document_no: str) -> set[str]:
    with SessionLocal() as s:
        s.rollback()
        rows = s.execute(
            select(OperationLog.action).where(OperationLog.document_no == document_no)
        ).scalars().all()
    return {a.value for a in rows}


def _ok_body(r) -> dict:
    assert r.status_code == 200, r.text
    return r.json()["data"]


# ======================================================================
# Create / snapshot
# ======================================================================
def test_create_draft_captures_snapshots_without_touching_stock(client: TestClient, db) -> None:
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    _seed_balance(client, wh, mid, qty="100", price="10.0000")
    assert f"{_balance(wh, mid)['quantity']}" == "100.0000"

    z = _wh_headers(client)
    r = _create_recon(client, z, wh, [{"material_id": mid, "physical_quantity": "97"}])
    assert r.status_code == 200, r.text
    doc = r.json()["data"]
    assert re.fullmatch(r"CNT-\d{8}-\d{4}", doc["reconciliation_no"]), doc["reconciliation_no"]
    assert doc["status"] == "DRAFT"
    assert doc["counted_by_name"] == "赵敏"          # 服务端确定，不可伪造
    assert doc["version"] == 1
    item = doc["items"][0]
    assert item["book_quantity_snapshot"] == "100.0000"
    assert item["book_total_amount_snapshot"] == "1000.00"
    assert item["book_avg_cost_snapshot"] == "10.0000"
    assert item["physical_quantity"] == "97.0000"
    assert item["difference_quantity"] == "-3.0000"
    # 草稿不产生流水/余额变化
    assert _adjust_txns(mid) == []
    assert f"{_balance(wh, mid)['quantity']}" == "100.0000"


def test_duplicate_material_line_rejected(client: TestClient, db) -> None:
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    z = _wh_headers(client)
    r = _create_recon(client, z, wh, [
        {"material_id": mid, "physical_quantity": "90"},
        {"material_id": mid, "physical_quantity": "80"},
    ])
    assert r.status_code == 409, r.text


def test_negative_physical_rejected(client: TestClient, db) -> None:
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    z = _wh_headers(client)
    r = _create_recon(client, z, wh, [{"material_id": mid, "physical_quantity": "-1"}])
    assert r.status_code == 422, r.text


def test_edit_draft_keeps_snapshot_and_version_cas(client: TestClient, db) -> None:
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    _seed_balance(client, wh, mid, qty="100", price="10.0000")
    z = _wh_headers(client)
    doc = _ok_body(_create_recon(client, z, wh, [{"material_id": mid, "physical_quantity": "97"}]))
    old_snapshot = doc["items"][0]["book_quantity_snapshot"]

    # 合法编辑：physical 97 -> 95（同物料行快照不变）
    r = _put_recon(client, z, doc["id"], version=1,
                   items=[{"material_id": mid, "physical_quantity": "95"}])
    assert r.status_code == 200, r.text
    edited = r.json()["data"]
    assert edited["version"] == 2
    item = edited["items"][0]
    assert item["book_quantity_snapshot"] == old_snapshot      # 快照不刷新
    assert item["physical_quantity"] == "95.0000"
    assert item["difference_quantity"] == "-5.0000"

    # 版本冲突：旧 version 提交被拒
    r = _submit_recon(client, z, doc["id"], version=1)
    assert r.status_code == 409 and r.json()["code"] == 7003, r.text
    r = _submit_recon(client, z, doc["id"], version=2)
    assert r.status_code == 200, r.text


def test_reject_then_revise_and_resubmit(client: TestClient, db) -> None:
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    _seed_balance(client, wh, mid, qty="100", price="10.0000")
    z = _wh_headers(client)
    doc = _ok_body(_create_recon(client, z, wh, [{"material_id": mid, "physical_quantity": "97"}]))
    assert _submit_recon(client, z, doc["id"], 1).status_code == 200

    r = _reject_recon(client, admin, doc["id"], comment="实盘数据请复核")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "REJECTED"

    # REJECTED -> PUT（修订）-> DRAFT -> 再提交
    r = _put_recon(client, z, doc["id"], version=r.json()["data"]["version"],
                   items=[{"material_id": mid, "physical_quantity": "96"}])
    assert r.status_code == 200, r.text
    revised = r.json()["data"]
    assert revised["status"] == "DRAFT"
    assert revised["items"][0]["physical_quantity"] == "96.0000"
    assert _submit_recon(client, z, doc["id"], revised["version"]).status_code == 200


# ======================================================================
# Approve / post
# ======================================================================
def test_approve_adjust_out_example(client: TestClient, db) -> None:
    """100@10 -> physical 97: ADJUST_OUT -3 / -30, balance 97 / 970, avg 10."""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    _seed_balance(client, wh, mid, qty="100", price="10.0000")
    z = _wh_headers(client)
    doc = _ok_body(_create_recon(client, z, wh, [{"material_id": mid, "physical_quantity": "97"}]))
    _ok_body(_submit_recon(client, z, doc["id"], 1))

    r = _approve_recon(client, admin, doc["id"])
    assert r.status_code == 200, r.text
    posted = r.json()["data"]
    assert posted["status"] == "POSTED"
    assert posted["posted_at"] is not None and posted["approved_by_name"] == "系统管理员"

    txns = _adjust_txns(mid)
    assert len(txns) == 1
    t = txns[0]
    assert t.transaction_type == TxnType.ADJUST_OUT
    assert f"{t.quantity}" == "-3.0000"
    assert f"{t.unit_cost}" == "10.0000"
    assert f"{t.amount}" == "-30.00"

    bal = _balance(wh, mid)
    assert f"{bal['quantity']}" == "97.0000"
    assert f"{bal['total_amount']}" == "970.00"
    assert f"{bal['average_unit_cost']}" == "10.0000"


def test_approve_adjust_in_explicit_rate(client: TestClient, db) -> None:
    """100@10 -> physical 103, valuation_rate 12: +3 / +36, total 1036, avg ~10.0583."""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    _seed_balance(client, wh, mid, qty="100", price="10.0000")
    z = _wh_headers(client)
    doc = _ok_body(_create_recon(
        client, z, wh,
        [{"material_id": mid, "physical_quantity": "103", "valuation_rate": "12"}]))
    _ok_body(_submit_recon(client, z, doc["id"], 1))
    posted = _ok_body(_approve_recon(client, admin, doc["id"]))

    assert posted["status"] == "POSTED"
    assert posted["items"][0]["adjustment_amount"] == "36.00"
    txns = _adjust_txns(mid)
    assert len(txns) == 1
    assert txns[0].transaction_type == TxnType.ADJUST_IN
    assert f"{txns[0].quantity}" == "3.0000"
    assert f"{txns[0].unit_cost}" == "12.0000"
    assert f"{txns[0].amount}" == "36.00"

    bal = _balance(wh, mid)
    assert f"{bal['quantity']}" == "103.0000"
    assert f"{bal['total_amount']}" == "1036.00"
    # avg = 1036 / 103 ≈ 10.0583 (4dp, ROUND_HALF_UP via money.unit_cost)
    assert f"{bal['average_unit_cost']}" == "10.0583"


def test_adjust_in_missing_valuation_rate_rejected(client: TestClient, db) -> None:
    """T-48: positive difference without explicit rate -> 7017."""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    _seed_balance(client, wh, mid, qty="100", price="10.0000")
    z = _wh_headers(client)
    r = _create_recon(client, z, wh, [{"material_id": mid, "physical_quantity": "103"}])
    assert r.status_code == 422 and r.json()["code"] == 7017, r.text
    # rate = 0 同样拒绝
    r = _create_recon(client, z, wh,
                      [{"material_id": mid, "physical_quantity": "103", "valuation_rate": "0"}])
    assert r.status_code == 422 and r.json()["code"] == 7017, r.text


def test_zero_balance_positive_count_with_rate(client: TestClient, db) -> None:
    """T-49: book 0 -> physical 5 @ rate 12: ADJUST_IN +5 / +60, balance row created."""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    z = _wh_headers(client)
    assert _balance(wh, mid) is None
    doc = _ok_body(_create_recon(
        client, z, wh,
        [{"material_id": mid, "physical_quantity": "5", "valuation_rate": "12"}]))
    assert doc["items"][0]["book_quantity_snapshot"] == "0.0000"
    _ok_body(_submit_recon(client, z, doc["id"], 1))
    posted = _ok_body(_approve_recon(client, admin, doc["id"]))
    assert posted["status"] == "POSTED"

    txns = _adjust_txns(mid)
    assert len(txns) == 1
    assert txns[0].transaction_type == TxnType.ADJUST_IN
    assert f"{txns[0].quantity}" == "5.0000"
    assert f"{txns[0].amount}" == "60.00"
    bal = _balance(wh, mid)
    assert f"{bal['quantity']}" == "5.0000"
    assert f"{bal['total_amount']}" == "60.00"
    assert f"{bal['average_unit_cost']}" == "12.0000"


def test_zero_difference_posts_without_transaction(client: TestClient, db) -> None:
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    _seed_balance(client, wh, mid, qty="100", price="10.0000")
    z = _wh_headers(client)
    doc = _ok_body(_create_recon(client, z, wh, [{"material_id": mid, "physical_quantity": "100"}]))
    assert doc["items"][0]["difference_quantity"] == "0.0000"
    _ok_body(_submit_recon(client, z, doc["id"], 1))
    posted = _ok_body(_approve_recon(client, admin, doc["id"]))
    assert posted["status"] == "POSTED"
    assert _adjust_txns(mid) == []                       # 0 差异不产生流水
    assert f"{_balance(wh, mid)['quantity']}" == "100.0000"  # 余额不动
    assert "STOCK_COUNT_APPROVE" in _audit_actions(doc["reconciliation_no"])


# ======================================================================
# State machine / validation
# ======================================================================
def test_invalid_state_transitions(client: TestClient, db) -> None:
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    _seed_balance(client, wh, mid, qty="100", price="10.0000")
    z = _wh_headers(client)
    doc = _ok_body(_create_recon(client, z, wh, [{"material_id": mid, "physical_quantity": "97"}]))

    # DRAFT 不能 approve / reject
    assert _approve_recon(client, admin, doc["id"]).status_code == 409
    assert _reject_recon(client, admin, doc["id"], comment="x").status_code == 409

    _ok_body(_submit_recon(client, z, doc["id"], 1))
    # PENDING 不能再 submit / edit；approve 成功一次后不可再 approve
    assert _submit_recon(client, z, doc["id"], 2).status_code == 409
    assert _put_recon(client, z, doc["id"], version=2,
                      items=[{"material_id": mid, "physical_quantity": "95"}]).status_code == 409
    posted = _ok_body(_approve_recon(client, admin, doc["id"]))
    # POSTED 不可再 submit / approve / edit / reject
    assert _approve_recon(client, admin, doc["id"]).status_code == 409
    assert _reject_recon(client, admin, doc["id"], comment="x").status_code == 409
    assert _put_recon(client, z, doc["id"], version=posted["version"],
                      items=[{"material_id": mid, "physical_quantity": "95"}]).status_code == 409


# ======================================================================
# RBAC / SoD
# ======================================================================
def test_rbac_permission_matrix(client: TestClient, db) -> None:
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    _seed_balance(client, wh, mid, qty="100", price="10.0000")

    applicant = _auth(_login(client, "zhangsan", "demo123"))
    buyer = _auth(_login(client, "wangwu", "demo123"))
    manager = _auth(_login(client, "lisi", "demo123"))
    z = _wh_headers(client)

    # 创建：仅 WAREHOUSE / ADMIN（无 reconcile:create 者 403）
    assert _create_recon(client, applicant, wh,
                         [{"material_id": mid, "physical_quantity": "97"}]).status_code == 403
    assert _create_recon(client, buyer, wh,
                         [{"material_id": mid, "physical_quantity": "97"}]).status_code == 403
    doc = _ok_body(_create_recon(client, z, wh, [{"material_id": mid, "physical_quantity": "97"}]))

    # 查看：APPLICANT / BUYER 403；WAREHOUSE / ADMIN 200
    assert client.get(f"/api/v1/stock-reconciliations/{doc['id']}",
                      headers=applicant).status_code == 403
    assert client.get(f"/api/v1/stock-reconciliations/{doc['id']}",
                      headers=buyer).status_code == 403
    assert client.get(f"/api/v1/stock-reconciliations/{doc['id']}", headers=z).status_code == 200

    _ok_body(_submit_recon(client, z, doc["id"], 1))
    # 审批：仅 ADMIN（DEPT_MANAGER / WAREHOUSE / BUYER 403）
    assert _approve_recon(client, manager, doc["id"]).status_code == 403
    assert _approve_recon(client, z, doc["id"]).status_code == 403
    assert _approve_recon(client, buyer, doc["id"]).status_code == 403
    assert _approve_recon(client, admin, doc["id"]).status_code == 200


def test_self_approval_forbidden_and_admin_override(client: TestClient, db) -> None:
    _clean_all()
    admin = _auth(_login(client))  # admin 既盘点又审批 -> SoD 场景
    mid = _create_material(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    _seed_balance(client, wh, mid, qty="100", price="10.0000")
    doc = _ok_body(_create_recon(client, admin, wh,
                                 [{"material_id": mid, "physical_quantity": "97"}]))
    assert _submit_recon(client, admin, doc["id"], 1).status_code == 200

    # 自审默认禁止
    r = _approve_recon(client, admin, doc["id"])
    assert r.status_code == 403 and r.json()["code"] == 7007, r.text
    # override 缺理由
    r = _approve_recon(client, admin, doc["id"], override_self_approval=True)
    assert r.status_code == 422 and r.json()["code"] == 7008, r.text
    # override 带理由 -> 成功 + 落库 + 审计
    r = _approve_recon(client, admin, doc["id"], override_self_approval=True,
                       override_reason="盘点人请假，唯一操作员代为过账")
    assert r.status_code == 200, r.text
    posted = r.json()["data"]
    assert posted["status"] == "POSTED"
    assert posted["override_self_approval"] is True
    assert posted["override_reason"] == "盘点人请假，唯一操作员代为过账"
    assert f"{_balance(wh, mid)['quantity']}" == "97.0000"
    assert "STOCK_COUNT_APPROVE" in _audit_actions(doc["reconciliation_no"])


def test_self_approval_override_requires_permission(client: TestClient, db, monkeypatch) -> None:
    """CR-A-007: SoD override 由显式权限 reconcile:self_approve_override 决定。

    服务层检查权限而非 role == ADMIN：权限缺失时即便带 override 标志 + 理由
    也返回 7007；权限在（seed 授予 ADMIN）时正常放行并落审计。
    """
    _clean_all()
    admin = _auth(_login(client))  # admin 既盘点又审批 -> SoD 场景
    mid = _create_material(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    _seed_balance(client, wh, mid, qty="100", price="10.0000")
    doc = _ok_body(_create_recon(client, admin, wh,
                                 [{"material_id": mid, "physical_quantity": "97"}]))
    assert _submit_recon(client, admin, doc["id"], 1).status_code == 200

    # 模拟无 override 权限：标志 + 理由齐全仍被拒（权限是闸门）
    monkeypatch.setattr(
        "app.services.stock_reconciliation_service._has_permission",
        lambda _db, _role_id, _perm: False,
    )
    r = _approve_recon(client, admin, doc["id"], override_self_approval=True,
                       override_reason="紧急代盘")
    assert r.status_code == 403 and r.json()["code"] == 7007, r.text
    assert _recon_detail(client, admin, doc["id"])["status"] == "PENDING"

    # 恢复真实权限查询 -> 放行（ADMIN 经 seed 持有该权限）
    monkeypatch.undo()
    r = _approve_recon(client, admin, doc["id"], override_self_approval=True,
                       override_reason="紧急代盘")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "POSTED"
    assert f"{_balance(wh, mid)['quantity']}" == "97.0000"
    assert "STOCK_COUNT_APPROVE" in _audit_actions(doc["reconciliation_no"])


# ======================================================================
# Concurrency
# ======================================================================
def test_double_approve_only_one_posts(client: TestClient, db) -> None:
    """两个线程同时 approve 同一 PENDING -> 恰一个成功，只有一组调整流水。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    _seed_balance(client, wh, mid, qty="100", price="10.0000")
    z = _wh_headers(client)
    doc = _ok_body(_create_recon(client, z, wh, [{"material_id": mid, "physical_quantity": "97"}]))
    assert _submit_recon(client, z, doc["id"], 1).status_code == 200

    results: list[int] = []
    lock = threading.Lock()
    barrier = threading.Barrier(2)

    def worker() -> None:
        barrier.wait()
        r = _approve_recon(client, admin, doc["id"])
        with lock:
            results.append(r.status_code)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [200, 409], results
    assert len(_adjust_txns(mid)) == 1                    # 只有一组流水
    assert f"{_balance(wh, mid)['quantity']}" == "97.0000"
    assert _recon_detail(client, z, doc["id"])["status"] == "POSTED"


# ======================================================================
# Snapshot Guard (staleness) / rollback
# ======================================================================
def test_receipt_after_snapshot_makes_reconciliation_stale(client: TestClient, db) -> None:
    """Receipt +20 落在快照与审批之间 -> 7005 stale，零副作用（T-46/T-47）。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    _seed_balance(client, wh, mid, qty="100", price="10.0000")
    z = _wh_headers(client)
    doc = _ok_body(_create_recon(client, z, wh, [{"material_id": mid, "physical_quantity": "97"}]))
    assert _submit_recon(client, z, doc["id"], 1).status_code == 200

    # 快照后另一笔真实入库 +20 -> balance 120
    _seed_balance(client, wh, mid, qty="20", price="10.0000")
    assert f"{_balance(wh, mid)['quantity']}" == "120.0000"

    r = _approve_recon(client, admin, doc["id"])
    assert r.status_code == 409 and r.json()["code"] == 7005, r.text
    # 副作用为零：无 ADJUST 流水、余额保持 120、文档仍 PENDING、无成功 POST 审计
    assert _adjust_txns(mid) == []
    assert f"{_balance(wh, mid)['quantity']}" == "120.0000"
    assert f"{_balance(wh, mid)['total_amount']}" == "1200.00"
    assert _recon_detail(client, z, doc["id"])["status"] == "PENDING"
    assert "STOCK_COUNT_APPROVE" not in _audit_actions(doc["reconciliation_no"])


def test_snapshot_amount_stale_detected(client: TestClient, db) -> None:
    """quantity 相同但 total_amount 漂移 -> 7005（OQ-12：金额也参与守卫）。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    _seed_balance(client, wh, mid, qty="100", price="10.0000")
    z = _wh_headers(client)
    doc = _ok_body(_create_recon(client, z, wh, [{"material_id": mid, "physical_quantity": "97"}]))
    assert _submit_recon(client, z, doc["id"], 1).status_code == 200

    # 模拟异常：数量不变但金额被外部改动（绕过同事务记账，诊断应暴露的场景）
    with SessionLocal() as s:
        s.execute(
            text("UPDATE inventory_balances SET total_amount = total_amount + 5 "
                 "WHERE warehouse_id = :w AND material_id = :m"),
            {"w": wh, "m": mid},
        )
        s.commit()

    r = _approve_recon(client, admin, doc["id"])
    assert r.status_code == 409 and r.json()["code"] == 7005, r.text
    assert _adjust_txns(mid) == []


def test_round_trip_movement_stale_despite_state_unchanged(client: TestClient, db) -> None:
    """CR-A-005: 快照后 +10 → 冲销 -10（真实业务链），state 回到 100/1000 但
    流水水印前移 -> 7005；零 ADJUST / 零余额变化 / 无 POST 审计 / 文档仍 PENDING。

    证明 Event Guard（水印）独立于 State Guard：盘点窗口期内发生过的 movement
    即便被完全对冲，也让"该快照对应哪个时间点"失效。
    """
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    _seed_balance(client, wh, mid, qty="100", price="10.0000")
    z = _wh_headers(client)
    doc = _ok_body(_create_recon(client, z, wh, [{"material_id": mid, "physical_quantity": "97"}]))
    assert _submit_recon(client, z, doc["id"], 1).status_code == 200

    def _max_ledger_id() -> int:
        with SessionLocal() as s:
            s.rollback()
            return s.execute(
                text("SELECT COALESCE(MAX(id), 0) FROM inventory_transactions "
                     "WHERE warehouse_id = :w AND material_id = :m"),
                {"w": wh, "m": mid},
            ).scalar_one()

    wm_at_snapshot = _max_ledger_id()
    assert wm_at_snapshot > 0  # seed 入库至少一笔

    # 盘点窗口内：+10 入库 → 整单冲销（回到 100 / 1000，但流水 +2 行）
    po2 = _mk_confirmed_po(client, mid, _supplier_of(client), qty="10", price="10.0000")
    r2 = _post_receipt(client, z, po2["id"], wh,
                       [{"po_item_id": po2["items"][0]["id"], "received_quantity": "10"}])
    assert r2.status_code == 200, r2.text
    rid = r2.json()["data"]["id"]
    rr = client.post(f"/api/v1/purchase-receipts/{rid}/reverse", headers=z,
                     json={"reason": "round-trip 补偿测试"})
    assert rr.status_code == 200, rr.text

    bal = _balance(wh, mid)
    assert f"{bal['quantity']}" == "100.0000"       # state 回到快照值
    assert f"{bal['total_amount']}" == "1000.00"
    assert _max_ledger_id() > wm_at_snapshot          # 但事件水印已前移

    r = _approve_recon(client, admin, doc["id"])
    assert r.status_code == 409 and r.json()["code"] == 7005, r.text
    # 零副作用（CR-A-005 断言）
    assert _adjust_txns(mid) == []
    bal = _balance(wh, mid)
    assert f"{bal['quantity']}" == "100.0000"
    assert f"{bal['total_amount']}" == "1000.00"
    assert _recon_detail(client, z, doc["id"])["status"] == "PENDING"
    assert "STOCK_COUNT_APPROVE" not in _audit_actions(doc["reconciliation_no"])


def test_multi_material_atomic_rollback(client: TestClient, db) -> None:
    """A 行有效、B 行 stale -> 整体回滚：A 不被调整，单据仍非 POSTED。"""
    _clean_all()
    admin = _auth(_login(client))
    mat_a = _create_material(client, admin, name="A 料")["id"]
    mat_b = _create_material(client, admin, name="B 料")["id"]
    wh = _create_warehouse(client, admin)["id"]
    _seed_balance(client, wh, mat_a, qty="100", price="10.0000")
    _seed_balance(client, wh, mat_b, qty="100", price="10.0000")
    z = _wh_headers(client)

    doc = _ok_body(_create_recon(client, z, wh, [
        {"material_id": mat_a, "physical_quantity": "97"},     # 有效
        {"material_id": mat_b, "physical_quantity": "90"},     # 将被 +20 搞 stale
    ]))
    assert _submit_recon(client, z, doc["id"], 1).status_code == 200

    _seed_balance(client, wh, mat_b, qty="20", price="10.0000")  # B 漂移

    r = _approve_recon(client, admin, doc["id"])
    assert r.status_code == 409 and r.json()["code"] == 7005, r.text
    # A 未被调整（同事务回滚）
    assert _adjust_txns(mat_a) == []
    assert _adjust_txns(mat_b) == []
    assert f"{_balance(wh, mat_a)['quantity']}" == "100.0000"
    assert f"{_balance(wh, mat_b)['quantity']}" == "120.0000"
    assert _recon_detail(client, z, doc["id"])["status"] == "PENDING"


# ======================================================================
# Master data edge cases
# ======================================================================
def test_inactive_material_allowed_to_finish_reconciliation(client: TestClient, db) -> None:
    """四十二：创建后物料被停用，提交/过账不被阻断（历史纠错原则）。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    _seed_balance(client, wh, mid, qty="100", price="10.0000")
    z = _wh_headers(client)
    doc = _ok_body(_create_recon(client, z, wh, [{"material_id": mid, "physical_quantity": "97"}]))

    # 停用物料（创建期已过）
    r = client.post(f"/api/v1/materials/{mid}/disable", headers=admin)
    assert r.status_code == 200, r.text

    assert _submit_recon(client, z, doc["id"], 1).status_code == 200
    assert _approve_recon(client, admin, doc["id"]).status_code == 200
    assert f"{_balance(wh, mid)['quantity']}" == "97.0000"

    # 停用物料不可再新建盘点行
    r = _create_recon(client, z, wh, [{"material_id": mid, "physical_quantity": "90"}])
    assert r.status_code == 409, r.text


def test_inactive_warehouse_allowed_to_finish_reconciliation(client: TestClient, db) -> None:
    """四十三：盘点创建后仓库被停用，提交/过账不阻断；停用仓不可新建盘点。

    注：带库存的仓本就禁止停用（WAREHOUSE_HAS_STOCK），故本用例用零库存盘盈
    （book 0 -> physical 5 @ rate 12）验证"完成既有盘点不被停用阻断"。
    """
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    z = _wh_headers(client)
    doc = _ok_body(_create_recon(
        client, z, wh,
        [{"material_id": mid, "physical_quantity": "5", "valuation_rate": "12"}]))

    r = client.post(f"/api/v1/warehouses/{wh}/disable", headers=admin)
    assert r.status_code == 200, r.text

    assert _submit_recon(client, z, doc["id"], 1).status_code == 200
    assert _approve_recon(client, admin, doc["id"]).status_code == 200
    assert f"{_balance(wh, mid)['quantity']}" == "5.0000"

    r = _create_recon(client, z, wh, [{"material_id": mid, "physical_quantity": "5",
                                       "valuation_rate": "12"}])
    assert r.status_code == 409, r.text


# ======================================================================
# Ledger / balance invariants
# ======================================================================
def test_ledger_signed_invariant_and_balance_sum(client: TestClient, db) -> None:
    """ADJUST 行符号与类型一致；SUM(流水) == 余额（数量与金额）。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    _seed_balance(client, wh, mid, qty="100", price="10.0000")
    z = _wh_headers(client)
    doc = _ok_body(_create_recon(client, z, wh, [{"material_id": mid, "physical_quantity": "103",
                                                  "valuation_rate": "12"}]))
    _ok_body(_submit_recon(client, z, doc["id"], 1))
    _ok_body(_approve_recon(client, admin, doc["id"]))

    with SessionLocal() as s:
        s.rollback()
        sums = s.execute(
            text("SELECT COALESCE(SUM(quantity),0), COALESCE(SUM(amount),0) "
                 "FROM inventory_transactions WHERE warehouse_id=:w AND material_id=:m"),
            {"w": wh, "m": mid},
        ).one()
    bal = _balance(wh, mid)
    assert f"{Decimal(sums[0])}" == f"{bal['quantity']}"
    assert f"{Decimal(sums[1])}" == f"{bal['total_amount']}"


def test_append_only_ledger_protection(client: TestClient, db) -> None:
    """ADJUST 流水同样受 append-only 触发器保护（UPDATE/DELETE 被拒）。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    _seed_balance(client, wh, mid, qty="100", price="10.0000")
    z = _wh_headers(client)
    doc = _ok_body(_create_recon(client, z, wh, [{"material_id": mid, "physical_quantity": "97"}]))
    _ok_body(_submit_recon(client, z, doc["id"], 1))
    _ok_body(_approve_recon(client, admin, doc["id"]))
    txn = _adjust_txns(mid)[0]

    with SessionLocal() as s:
        with pytest.raises(SQLAlchemyError):
            s.execute(text("UPDATE inventory_transactions SET quantity = quantity WHERE id = :i"),
                      {"i": txn.id})
            s.commit()
        s.rollback()
    with SessionLocal() as s:
        with pytest.raises(SQLAlchemyError):
            s.execute(text("DELETE FROM inventory_transactions WHERE id = :i"), {"i": txn.id})
            s.commit()
        s.rollback()


# ======================================================================
# Audit / misc
# ======================================================================
def test_audit_trail_create_submit_approve(client: TestClient, db) -> None:
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    _seed_balance(client, wh, mid, qty="100", price="10.0000")
    z = _wh_headers(client)
    doc = _ok_body(_create_recon(client, z, wh, [{"material_id": mid, "physical_quantity": "97"}]))
    _ok_body(_submit_recon(client, z, doc["id"], 1))
    _ok_body(_approve_recon(client, admin, doc["id"]))
    actions = _audit_actions(doc["reconciliation_no"])
    assert {"STOCK_COUNT_CREATE", "STOCK_COUNT_SUBMIT", "STOCK_COUNT_APPROVE"} <= actions


def test_reconciliation_list_filters_and_pagination(client: TestClient, db) -> None:
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    _seed_balance(client, wh, mid, qty="100", price="10.0000")
    z = _wh_headers(client)
    doc = _ok_body(_create_recon(client, z, wh, [{"material_id": mid, "physical_quantity": "97"}]))

    r = client.get("/api/v1/stock-reconciliations", headers=z,
                   params={"status": "DRAFT"})
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["total"] >= 1
    item = next(x for x in body["items"] if x["id"] == doc["id"])
    assert item["item_count"] == 1 and item["status"] == "DRAFT"

    r = client.get(f"/api/v1/stock-reconciliations?reconciliation_no={doc['reconciliation_no'][:6]}",
                   headers=z)
    assert r.status_code == 200 and r.json()["data"]["total"] >= 1
