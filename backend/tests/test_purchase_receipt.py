"""Phase 9 purchase-receipt tests: receiving, partial receipt, concurrency,
reversal, PO status rollback, transaction atomicity, RBAC and the full
PR -> Approval -> PO -> Receipt -> Inventory chain.

The four concepts stay separate throughout (Phase 9 §二):
PO = intent, Receipt = business fact, Transaction = ledger, Balance = cache.

Helper users (from init_data):
- zhangsan: APPLICANT @ RD (creates PRs)
- lisi:     DEPT_MANAGER @ RD (approves RD PRs)
- wangwu:   BUYER @ PUR (creates / confirms POs; receipt:view only)
- zhaoliu:  WAREHOUSE @ WH (receipt:create / receipt:reverse)
- admin:    ADMIN (everything)
"""

from __future__ import annotations

import re
import threading
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text

from app.core.exceptions import ConflictException
from app.db.session import SessionLocal
from app.models import (
    ApprovalRecord,
    InventoryBalance,
    InventoryPolicy,
    InventoryTransaction,
    Material,
    OperationLog,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderItemSource,
    PurchaseReceipt,
    PurchaseReceiptItem,
    PurchaseRequisition,
    PurchaseRequisitionItem,
    Supplier,
    User,
    Warehouse,
)
from app.services import audit_service, inventory_service
from app.utils.enums import (
    AuditAction,
    PoStatus,
    ReceiptStatus,
    TxnSourceType,
    TxnType,
)

from cleanup_helper import wipe_business_data


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _login(client: TestClient, username: str = "admin", password: str = "admin123") -> str:
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["data"]["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _clean_all() -> None:
    """Wipe every business document the Phase 9 chain can create, master data
    included — receipts and the append-only ledger make FK order non-trivial,
    so the shared :func:`cleanup_helper.wipe_business_data` owns that logic."""
    wipe_business_data()


def _create_material(client: TestClient, headers: dict, name: str = "入库测试物料") -> dict:
    r = client.post("/api/v1/materials", headers=headers, json={"material_name": name, "unit": "pcs"})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _create_supplier(client: TestClient, headers: dict, name: str = "入库测试供应商") -> dict:
    r = client.post("/api/v1/suppliers", headers=headers, json={"supplier_name": name})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _create_warehouse(client: TestClient, headers: dict, name: str = "入库测试仓") -> dict:
    r = client.post("/api/v1/warehouses", headers=headers, json={"warehouse_name": name})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _mk_pr(client: TestClient, headers: dict, material_id: int, qty="100", price="10.0000") -> dict:
    r = client.post("/api/v1/purchase-requisitions", headers=headers, json={
        "items": [{"material_id": material_id, "requested_quantity": qty,
                   "estimated_unit_price": price}],
    })
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _submit(client: TestClient, headers: dict, pr_id: int) -> dict:
    r = client.post(f"/api/v1/purchase-requisitions/{pr_id}/submit", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _approve(client: TestClient, headers: dict, pr_id: int, version: int) -> dict:
    r = client.post(f"/api/v1/purchase-requisitions/{pr_id}/approve", headers=headers,
                    json={"version": version})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _mk_approved_pr(client: TestClient, material_id: int, qty="100", price="10.0000") -> dict:
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pr(client, z, material_id, qty, price)
    submitted = _submit(client, z, pr["id"])
    lisi = _auth(_login(client, "lisi", "demo123"))
    return _approve(client, lisi, pr["id"], version=submitted["version"])


def _mk_po(client: TestClient, supplier_id: int, pr_items: list[dict],
           buyer: str = "wangwu", unit_price: str = "10.0000") -> dict:
    b = _auth(_login(client, buyer, "demo123"))
    items = []
    for src in pr_items:
        r = client.get(f"/api/v1/purchase-requisitions/{src['pr_id']}", headers=b)
        assert r.status_code == 200, r.text
        line = next(x for x in r.json()["data"]["items"] if x["id"] == src["pr_item_id"])
        items.append({
            "material_id": line["material_id"],
            "ordered_quantity": src["ordered_quantity"],
            "unit_price": unit_price,
            "sources": [{"pr_item_id": src["pr_item_id"], "quantity": src["quantity"]}],
        })
    r = client.post("/api/v1/purchase-orders", headers=b,
                    json={"supplier_id": supplier_id, "items": items})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _confirm_po(client: TestClient, headers: dict, po_id: int, version: int) -> dict:
    r = client.post(f"/api/v1/purchase-orders/{po_id}/confirm", headers=headers,
                    json={"version": version})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _mk_confirmed_po(client: TestClient, headers: dict, material_id: int, supplier_id: int,
                     qty="100", price="10.0000") -> dict:
    """PR -> approve -> PO -> confirm, ready to receive against."""
    pr = _mk_approved_pr(client, material_id, qty, price)
    po = _mk_po(client, supplier_id, [{
        "pr_id": pr["id"], "pr_item_id": pr["items"][0]["id"],
        "quantity": qty, "ordered_quantity": qty,
    }], unit_price=price)
    b = _auth(_login(client, "wangwu", "demo123"))
    return _confirm_po(client, b, po["id"], po["version"])


def _wh_headers(client: TestClient) -> dict[str, str]:
    return _auth(_login(client, "zhaoliu", "demo123"))


def _post_receipt(client: TestClient, headers: dict, po_id: int, warehouse_id: int,
                  items: list[dict], **kw):
    return client.post("/api/v1/purchase-receipts", headers=headers,
                       json={"po_id": po_id, "warehouse_id": warehouse_id,
                             "items": items, **kw})


def _po_detail(client: TestClient, headers: dict, po_id: int) -> dict:
    r = client.get(f"/api/v1/purchase-orders/{po_id}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _balance(warehouse_id: int, material_id: int) -> dict | None:
    with SessionLocal() as s:
        s.rollback()  # 穿透 REPEATABLE READ 快照，看到 API 会话已提交的数据
        b = s.execute(
            select(InventoryBalance).where(
                InventoryBalance.warehouse_id == warehouse_id,
                InventoryBalance.material_id == material_id,
            )
        ).scalar_one_or_none()
        if b is None:
            return None
        return {"quantity": b.quantity, "total_amount": b.total_amount,
                "average_unit_cost": b.average_unit_cost, "version": b.version}


def _txns(**filters) -> list[InventoryTransaction]:
    with SessionLocal() as s:
        s.rollback()
        stmt = select(InventoryTransaction)
        for k, v in filters.items():
            stmt = stmt.where(getattr(InventoryTransaction, k) == v)
        return list(s.execute(stmt.order_by(InventoryTransaction.id)).scalars().all())


def _count(model) -> int:
    with SessionLocal() as s:
        s.rollback()
        return s.execute(select(model)).scalars().all().__len__()


def _audit_actions(document_no: str) -> set[str]:
    with SessionLocal() as s:
        s.rollback()
        rows = s.execute(
            select(OperationLog.action).where(OperationLog.document_no == document_no)
        ).scalars().all()
    return {a.value for a in rows}


def _user_id(username: str) -> int:
    with SessionLocal() as s:
        s.rollback()
        return s.execute(select(User.id).where(User.username == username)).scalar_one()


# ======================================================================
# 三十四：正常入库校验链
# ======================================================================
def test_create_receipt_on_confirmed_po_success(client: TestClient, db) -> None:
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_confirmed_po(client, admin, mid, sup, qty="100", price="10.0000")
    wh_h = _wh_headers(client)

    r = _post_receipt(client, wh_h, po["id"], wh,
                      [{"po_item_id": po["items"][0]["id"], "received_quantity": "40"}])
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    # 14. 编号 RCV-YYYYMMDD-XXXX
    assert re.fullmatch(r"RCV-\d{8}-\d{4}", body["receipt_no"]), body["receipt_no"]
    # 6. 创建即 POSTED（无 DRAFT）
    assert body["status"] == "POSTED"
    # 11. received_by 服务端确定（zhaoliu 登录，非客户端指定）
    assert body["received_by"] == _user_id("zhaoliu")
    assert body["received_by_name"] == "赵敏"
    assert body["po_no"] == po["po_no"]
    assert body["reversed_at"] is None and body["reverse_reason"] is None
    # 12. 成本取自 PO 单价；13. 金额服务端 Decimal 计算（40 × 10.0000 = 400.00）
    item = body["items"][0]
    assert item["unit_price"] == "10.0000"
    assert item["amount"] == "400.00"
    assert item["material_id"] == mid


def test_create_receipt_draft_po_rejected(client: TestClient, db) -> None:
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    pr = _mk_approved_pr(client, mid, qty="10")
    po = _mk_po(client, sup, [{"pr_id": pr["id"], "pr_item_id": pr["items"][0]["id"],
                               "quantity": "10", "ordered_quantity": "10"}])
    assert po["status"] == "DRAFT"
    r = _post_receipt(client, _wh_headers(client), po["id"], wh,
                      [{"po_item_id": po["items"][0]["id"], "received_quantity": "1"}])
    assert r.status_code == 409 and r.json()["code"] == 5009, r.text


def test_create_receipt_cancelled_po_rejected(client: TestClient, db) -> None:
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_confirmed_po(client, admin, mid, sup, qty="10")
    b = _auth(_login(client, "wangwu", "demo123"))
    assert _po_detail(client, b, po["id"])["status"] == "CONFIRMED"
    r = client.post(f"/api/v1/purchase-orders/{po['id']}/cancel", headers=b,
                    json={"version": po["version"], "reason": "测试取消"})
    assert r.status_code == 200, r.text
    r = _post_receipt(client, _wh_headers(client), po["id"], wh,
                      [{"po_item_id": po["items"][0]["id"], "received_quantity": "1"}])
    assert r.status_code == 409 and r.json()["code"] == 5009, r.text


def test_create_receipt_received_po_rejected(client: TestClient, db) -> None:
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_confirmed_po(client, admin, mid, sup, qty="10")
    wh_h = _wh_headers(client)
    r = _post_receipt(client, wh_h, po["id"], wh,
                      [{"po_item_id": po["items"][0]["id"], "received_quantity": "10"}])
    assert r.status_code == 200, r.text
    b = _auth(_login(client, "wangwu", "demo123"))
    assert _po_detail(client, b, po["id"])["status"] == "RECEIVED"
    r = _post_receipt(client, wh_h, po["id"], wh,
                      [{"po_item_id": po["items"][0]["id"], "received_quantity": "1"}])
    assert r.status_code == 409 and r.json()["code"] == 5009, r.text


def test_create_receipt_inactive_warehouse_rejected(client: TestClient, db) -> None:
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_confirmed_po(client, admin, mid, sup, qty="10")
    r = client.post(f"/api/v1/warehouses/{wh}/disable", headers=admin)
    assert r.status_code == 200, r.text
    r = _post_receipt(client, _wh_headers(client), po["id"], wh,
                      [{"po_item_id": po["items"][0]["id"], "received_quantity": "1"}])
    assert r.status_code == 409, r.text


def test_create_receipt_inactive_material_rejected(client: TestClient, db) -> None:
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_confirmed_po(client, admin, mid, sup, qty="10")
    r = client.post(f"/api/v1/materials/{mid}/disable", headers=admin)
    assert r.status_code == 200, r.text
    r = _post_receipt(client, _wh_headers(client), po["id"], wh,
                      [{"po_item_id": po["items"][0]["id"], "received_quantity": "1"}])
    assert r.status_code == 409, r.text


def test_create_receipt_requires_at_least_one_item(client: TestClient, db) -> None:
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_confirmed_po(client, admin, mid, sup, qty="10")
    r = client.post("/api/v1/purchase-receipts", headers=_wh_headers(client),
                    json={"po_id": po["id"], "warehouse_id": wh, "items": []})
    assert r.status_code == 422, r.text


def test_create_receipt_non_positive_quantity_rejected(client: TestClient, db) -> None:
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_confirmed_po(client, admin, mid, sup, qty="10")
    poi = po["items"][0]["id"]
    for bad in ("0", "-1"):
        r = _post_receipt(client, _wh_headers(client), po["id"], wh,
                          [{"po_item_id": poi, "received_quantity": bad}])
        assert r.status_code == 422, r.text


def test_create_receipt_po_item_not_in_po_rejected(client: TestClient, db) -> None:
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_confirmed_po(client, admin, mid, sup, qty="10")
    # 第二张 PO 的明细不属于第一张 PO
    po2 = _mk_confirmed_po(client, admin, mid, sup, qty="10")
    r = _post_receipt(client, _wh_headers(client), po["id"], wh,
                      [{"po_item_id": po2["items"][0]["id"], "received_quantity": "1"}])
    assert r.status_code == 409 and r.json()["code"] == 6012, r.text


def test_create_receipt_duplicate_po_item_rejected(client: TestClient, db) -> None:
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_confirmed_po(client, admin, mid, sup, qty="10")
    poi = po["items"][0]["id"]
    r = _post_receipt(client, _wh_headers(client), po["id"], wh, [
        {"po_item_id": poi, "received_quantity": "2"},
        {"po_item_id": poi, "received_quantity": "3"},
    ])
    assert r.status_code == 409 and r.json()["code"] == 6004, r.text
    # 未留下任何库存影响
    assert _balance(wh, mid) is None
    assert _txns(material_id=mid) == []


def test_received_by_cannot_be_forged(client: TestClient, db) -> None:
    """客户端传 received_by / status / material_id 一律被忽略（§五）。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    mid2 = _create_material(client, admin, "伪造物料")["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_confirmed_po(client, admin, mid, sup, qty="10")
    r = client.post("/api/v1/purchase-receipts", headers=_wh_headers(client), json={
        "po_id": po["id"], "warehouse_id": wh,
        "received_by": _user_id("admin"),
        "status": "REVERSED",
        "items": [{"po_item_id": po["items"][0]["id"], "received_quantity": "1",
                   "material_id": mid2, "unit_price": "9999", "amount": "9999"}],
    })
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["received_by"] == _user_id("zhaoliu")  # 登录用户，而非伪造值
    assert body["status"] == "POSTED"                  # 服务端状态，不可伪造
    assert body["items"][0]["material_id"] == mid      # 由 PO 明细推导
    assert body["items"][0]["unit_price"] == "10.0000"
    assert body["items"][0]["amount"] == "10.00"


def test_receipt_amount_uses_decimal_rounding(client: TestClient, db) -> None:
    """金额 = ROUND_HALF_UP(qty × PO 单价, 2)：3 × 12.3456 = 37.0368 → 37.04。

    平均成本由 2 位权威金额反算（§十二：total_amount 权威、average 派生）：
    37.04 / 3 = 12.346666… → ROUND_HALF_UP → 12.3467。
    """
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_confirmed_po(client, admin, mid, sup, qty="10", price="12.3456")
    r = _post_receipt(client, _wh_headers(client), po["id"], wh,
                      [{"po_item_id": po["items"][0]["id"], "received_quantity": "3"}])
    assert r.status_code == 200, r.text
    item = r.json()["data"]["items"][0]
    assert item["unit_price"] == "12.3456"
    assert item["amount"] == "37.04"
    bal = _balance(wh, mid)
    assert f"{bal['quantity']}" == "3.0000"
    assert f"{bal['total_amount']}" == "37.04"
    # total_amount 是权威值（2 位），average_unit_cost 由其反算（4 位）
    assert f"{bal['average_unit_cost']}" == "12.3467"


def test_posted_receipt_cannot_be_edited_or_deleted(client: TestClient, db) -> None:
    """§十七：POSTED 入库单不提供 PUT / PATCH / DELETE。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_confirmed_po(client, admin, mid, sup, qty="10")
    wh_h = _wh_headers(client)
    rid = _post_receipt(client, wh_h, po["id"], wh,
                        [{"po_item_id": po["items"][0]["id"], "received_quantity": "1"}]
                        ).json()["data"]["id"]
    for verb in ("put", "patch"):
        r = getattr(client, verb)(f"/api/v1/purchase-receipts/{rid}", headers=wh_h, json={})
        assert r.status_code == 405, (verb, r.status_code, r.text)
    r = client.delete(f"/api/v1/purchase-receipts/{rid}", headers=wh_h)
    assert r.status_code == 405, r.text


# ======================================================================
# 三十五：部分收货
# ======================================================================
def test_partial_receipt_flow(client: TestClient, db) -> None:
    """100 → 收 40（PARTIALLY_RECEIVED）→ 收 60（RECEIVED）→ 再收 1 被拒。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_confirmed_po(client, admin, mid, sup, qty="100")
    poi = po["items"][0]["id"]
    wh_h = _wh_headers(client)
    b = _auth(_login(client, "wangwu", "demo123"))

    r1 = _post_receipt(client, wh_h, po["id"], wh,
                       [{"po_item_id": poi, "received_quantity": "40"}])
    assert r1.status_code == 200, r1.text
    assert _po_detail(client, b, po["id"])["status"] == "PARTIALLY_RECEIVED"
    assert _po_detail(client, b, po["id"])["items"][0]["received_quantity"] == "40.0000"
    assert f"{_balance(wh, mid)['quantity']}" == "40.0000"

    r2 = _post_receipt(client, wh_h, po["id"], wh,
                       [{"po_item_id": poi, "received_quantity": "60"}])
    assert r2.status_code == 200, r2.text
    assert _po_detail(client, b, po["id"])["status"] == "RECEIVED"
    assert f"{_balance(wh, mid)['quantity']}" == "100.0000"
    assert r1.json()["data"]["receipt_no"] != r2.json()["data"]["receipt_no"]

    r3 = _post_receipt(client, wh_h, po["id"], wh,
                       [{"po_item_id": poi, "received_quantity": "1"}])
    # PO 已 RECEIVED → 5009（PO_NOT_RECEIVABLE）
    assert r3.status_code == 409 and r3.json()["code"] == 5009, r3.text


def test_receipt_over_remaining_rejected(client: TestClient, db) -> None:
    """PO 未收满但本次超剩余 → 6002（RECEIPT_EXCEEDS_REMAINING）。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_confirmed_po(client, admin, mid, sup, qty="100")
    poi = po["items"][0]["id"]
    wh_h = _wh_headers(client)
    assert _post_receipt(client, wh_h, po["id"], wh,
                         [{"po_item_id": poi, "received_quantity": "90"}]).status_code == 200
    r = _post_receipt(client, wh_h, po["id"], wh,
                      [{"po_item_id": poi, "received_quantity": "20"}])
    assert r.status_code == 409 and r.json()["code"] == 6002, r.text
    b = _auth(_login(client, "wangwu", "demo123"))
    assert _po_detail(client, b, po["id"])["items"][0]["received_quantity"] == "90.0000"


def test_multi_item_po_status_derivation(client: TestClient, db) -> None:
    """多明细：A 收满 + B 部分 → PARTIALLY_RECEIVED；全部收满 → RECEIVED。"""
    _clean_all()
    admin = _auth(_login(client))
    m1 = _create_material(client, admin, "多明细物料A")["id"]
    m2 = _create_material(client, admin, "多明细物料B")["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    pr1 = _mk_approved_pr(client, m1, qty="10")
    pr2 = _mk_approved_pr(client, m2, qty="50")
    po = _mk_po(client, sup, [
        {"pr_id": pr1["id"], "pr_item_id": pr1["items"][0]["id"],
         "quantity": "10", "ordered_quantity": "10"},
        {"pr_id": pr2["id"], "pr_item_id": pr2["items"][0]["id"],
         "quantity": "50", "ordered_quantity": "50"},
    ])
    b = _auth(_login(client, "wangwu", "demo123"))
    po = _confirm_po(client, b, po["id"], po["version"])
    wh_h = _wh_headers(client)
    item_a = next(i for i in po["items"] if i["material_id"] == m1)
    item_b = next(i for i in po["items"] if i["material_id"] == m2)

    assert _post_receipt(client, wh_h, po["id"], wh, [
        {"po_item_id": item_a["id"], "received_quantity": "10"},
        {"po_item_id": item_b["id"], "received_quantity": "20"},
    ]).status_code == 200
    assert _po_detail(client, b, po["id"])["status"] == "PARTIALLY_RECEIVED"

    assert _post_receipt(client, wh_h, po["id"], wh,
                         [{"po_item_id": item_b["id"], "received_quantity": "30"}]
                         ).status_code == 200
    assert _po_detail(client, b, po["id"])["status"] == "RECEIVED"
    assert f"{_balance(wh, m1)['quantity']}" == "10.0000"
    assert f"{_balance(wh, m2)['quantity']}" == "50.0000"


# ======================================================================
# 三十六：并发
# ======================================================================
def test_concurrent_receipt_no_over_receive(client: TestClient, db) -> None:
    """剩余 10，两线程同时收 7 与 6 → 恰一成功，received <= ordered。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_confirmed_po(client, admin, mid, sup, qty="100")
    poi = po["items"][0]["id"]
    wh_h = _wh_headers(client)
    assert _post_receipt(client, wh_h, po["id"], wh,
                         [{"po_item_id": poi, "received_quantity": "90"}]).status_code == 200

    results: list[int] = []
    barrier = threading.Barrier(2)

    def worker(qty: str) -> None:
        barrier.wait()
        r = _post_receipt(client, wh_h, po["id"], wh,
                          [{"po_item_id": poi, "received_quantity": qty}])
        results.append(r.status_code)

    threads = [threading.Thread(target=worker, args=(q,)) for q in ("7", "6")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [200, 409], results

    b = _auth(_login(client, "wangwu", "demo123"))
    received = Decimal(_po_detail(client, b, po["id"])["items"][0]["received_quantity"])
    assert received in (Decimal("97"), Decimal("96"))
    assert received <= Decimal("100")
    assert f"{_balance(wh, mid)['quantity']}" == f"{received:.4f}"


def test_concurrent_receipt_same_balance_no_lost_update(client: TestClient, db) -> None:
    """并发对同一 (warehouse, material) 入库，余额不丢更新。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    # 10 张 PO，各收 5，并发执行
    pos = [_mk_confirmed_po(client, admin, mid, sup, qty="5") for _ in range(10)]
    wh_h = _wh_headers(client)
    results: list[int] = []
    lock = threading.Lock()
    barrier = threading.Barrier(10)

    def worker(po: dict) -> None:
        barrier.wait()
        r = _post_receipt(client, wh_h, po["id"], wh,
                          [{"po_item_id": po["items"][0]["id"], "received_quantity": "5"}])
        with lock:
            results.append(r.status_code)

    threads = [threading.Thread(target=worker, args=(p,)) for p in pos]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count(200) == 10, results
    with SessionLocal() as s:
        s.rollback()
        rows = s.execute(select(InventoryBalance).where(
            InventoryBalance.warehouse_id == wh,
            InventoryBalance.material_id == mid,
        )).scalars().all()
    assert len(rows) == 1                       # 24. 首次并发创建也只有一行
    assert f"{rows[0].quantity}" == "50.0000"   # 无 Lost Update
    assert f"{rows[0].total_amount}" == "500.00"


def test_concurrent_first_balance_creation_single_row(client: TestClient, db) -> None:
    """两个物料并发首次入库 → 各一行余额，无重复键。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_confirmed_po(client, admin, mid, sup, qty="100")
    poi = po["items"][0]["id"]
    wh_h = _wh_headers(client)
    results: list[int] = []
    barrier = threading.Barrier(4)

    def worker(qty: str) -> None:
        barrier.wait()
        r = _post_receipt(client, wh_h, po["id"], wh,
                          [{"po_item_id": poi, "received_quantity": qty}])
        results.append(r.status_code)

    threads = [threading.Thread(target=worker, args=(q,)) for q in ("10", "10", "10", "10")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(200) == 4, results
    with SessionLocal() as s:
        s.rollback()
        rows = s.execute(select(InventoryBalance).where(
            InventoryBalance.warehouse_id == wh, InventoryBalance.material_id == mid
        )).scalars().all()
    assert len(rows) == 1
    assert f"{rows[0].quantity}" == "40.0000"


def test_concurrent_receipt_numbers_unique(client: TestClient, db) -> None:
    """并发取号无重复（uk_receipt_no 唯一键 + 序列行锁）。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    pos = [_mk_confirmed_po(client, admin, mid, sup, qty="1") for _ in range(8)]
    wh_h = _wh_headers(client)
    nos: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(8)

    def worker(po: dict) -> None:
        barrier.wait()
        r = _post_receipt(client, wh_h, po["id"], wh,
                          [{"po_item_id": po["items"][0]["id"], "received_quantity": "1"}])
        if r.status_code == 200:
            with lock:
                nos.append(r.json()["data"]["receipt_no"])

    threads = [threading.Thread(target=worker, args=(p,)) for p in pos]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(nos) == 8 and len(set(nos)) == 8, nos


# ======================================================================
# 三十九 / 四十：冲销 与 PO 状态回退
# ======================================================================
def test_reverse_receipt_success(client: TestClient, db) -> None:
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_confirmed_po(client, admin, mid, sup, qty="100", price="10.0000")
    wh_h = _wh_headers(client)
    rcpt = _post_receipt(client, wh_h, po["id"], wh,
                         [{"po_item_id": po["items"][0]["id"], "received_quantity": "40"}]
                         ).json()["data"]
    assert f"{_balance(wh, mid)['quantity']}" == "40.0000"

    r = client.post(f"/api/v1/purchase-receipts/{rcpt['id']}/reverse", headers=wh_h,
                    json={"reason": "供应商发错货"})
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    # 44. 状态 POSTED → REVERSED
    assert body["status"] == "REVERSED"
    assert body["reversed_by"] == _user_id("zhaoliu")
    assert body["reverse_reason"] == "供应商发错货"
    assert body["reversed_at"] is not None

    # 45/46. 反向流水：quantity 取负，类型 PURCHASE_IN_REVERSAL
    out = _txns(transaction_type=TxnType.PURCHASE_IN_REVERSAL)
    assert len(out) == 1
    assert f"{out[0].quantity}" == "-40.0000"
    assert f"{out[0].amount}" == "-400.00"
    # 47. source_transaction_id 指向原始流水
    original = _txns(transaction_type=TxnType.PURCHASE_IN)
    assert len(original) == 1 and out[0].reversed_transaction_id == original[0].id
    # 49/52. 余额归零
    bal = _balance(wh, mid)
    assert f"{bal['quantity']}" == "0.0000"
    assert f"{bal['total_amount']}" == "0.00"
    assert f"{bal['average_unit_cost']}" == "0.0000"
    # 48. PO 收货数量回退
    b = _auth(_login(client, "wangwu", "demo123"))
    assert _po_detail(client, b, po["id"])["items"][0]["received_quantity"] == "0.0000"
    # 59. PO 状态回到 CONFIRMED
    assert _po_detail(client, b, po["id"])["status"] == "CONFIRMED"
    # 审计
    assert AuditAction.RECEIPT_REVERSE.value in _audit_actions(rcpt["receipt_no"])


def test_reverse_uses_original_amount_not_current_average(client: TestClient, db) -> None:
    """§十九：冲销按原始入库金额回退，而非当前平均成本 × 数量。

    入库 A：10 × 10 = 100；入库 B：10 × 30 = 300 → qty 20 / total 400 / avg 20。
    冲销 A 应回退 100（不是 avg 20 × 10 = 200）→ qty 10 / total 300 / avg 30。
    """
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po_a = _mk_confirmed_po(client, admin, mid, sup, qty="10", price="10.0000")
    po_b = _mk_confirmed_po(client, admin, mid, sup, qty="10", price="30.0000")
    wh_h = _wh_headers(client)
    ra = _post_receipt(client, wh_h, po_a["id"], wh,
                       [{"po_item_id": po_a["items"][0]["id"], "received_quantity": "10"}]
                       ).json()["data"]
    _post_receipt(client, wh_h, po_b["id"], wh,
                  [{"po_item_id": po_b["items"][0]["id"], "received_quantity": "10"}])
    bal = _balance(wh, mid)
    assert f"{bal['quantity']}" == "20.0000"
    assert f"{bal['total_amount']}" == "400.00"
    assert f"{bal['average_unit_cost']}" == "20.0000"

    r = client.post(f"/api/v1/purchase-receipts/{ra['id']}/reverse", headers=wh_h,
                    json={"reason": "原始成本回退验证"})
    assert r.status_code == 200, r.text
    bal = _balance(wh, mid)
    assert f"{bal['quantity']}" == "10.0000"
    assert f"{bal['total_amount']}" == "300.00"   # 400 - 100（非 400 - 200）
    assert f"{bal['average_unit_cost']}" == "30.0000"


def test_reverse_average_cost_recomputed_on_partial_receipt(client: TestClient, db) -> None:
    """部分冲销后平均成本按 (total - 原金额) / (qty - 原数量) 重算。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_confirmed_po(client, admin, mid, sup, qty="30", price="10.0000")
    wh_h = _wh_headers(client)
    poi = po["items"][0]["id"]
    r1 = _post_receipt(client, wh_h, po["id"], wh,
                       [{"po_item_id": poi, "received_quantity": "10"}]).json()["data"]
    r2 = _post_receipt(client, wh_h, po["id"], wh,
                       [{"po_item_id": poi, "received_quantity": "20"}]).json()["data"]
    b = _auth(_login(client, "wangwu", "demo123"))
    assert _po_detail(client, b, po["id"])["status"] == "RECEIVED"
    assert f"{_balance(wh, mid)['quantity']}" == "30.0000"

    # 58. RECEIVED → 冲销第二张（20）→ PARTIALLY_RECEIVED
    r = client.post(f"/api/v1/purchase-receipts/{r2['id']}/reverse", headers=wh_h,
                    json={"reason": "部分退回"})
    assert r.status_code == 200, r.text
    assert _po_detail(client, b, po["id"])["status"] == "PARTIALLY_RECEIVED"
    bal = _balance(wh, mid)
    assert f"{bal['quantity']}" == "10.0000"
    assert f"{bal['total_amount']}" == "100.00"
    assert f"{bal['average_unit_cost']}" == "10.0000"


def test_reverse_requires_reason(client: TestClient, db) -> None:
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_confirmed_po(client, admin, mid, sup, qty="10")
    wh_h = _wh_headers(client)
    rid = _post_receipt(client, wh_h, po["id"], wh,
                        [{"po_item_id": po["items"][0]["id"], "received_quantity": "1"}]
                        ).json()["data"]["id"]
    for bad in ({}, {"reason": ""}, {"reason": "   "}):
        r = client.post(f"/api/v1/purchase-receipts/{rid}/reverse", headers=wh_h, json=bad)
        assert r.status_code == 422, (bad, r.text)


def test_reverse_twice_rejected(client: TestClient, db) -> None:
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_confirmed_po(client, admin, mid, sup, qty="10")
    wh_h = _wh_headers(client)
    rid = _post_receipt(client, wh_h, po["id"], wh,
                        [{"po_item_id": po["items"][0]["id"], "received_quantity": "4"}]
                        ).json()["data"]["id"]
    assert client.post(f"/api/v1/purchase-receipts/{rid}/reverse", headers=wh_h,
                       json={"reason": "第一次"}).status_code == 200
    r = client.post(f"/api/v1/purchase-receipts/{rid}/reverse", headers=wh_h,
                    json={"reason": "第二次"})
    assert r.status_code == 409 and r.json()["code"] == 6005, r.text
    # 只能回退一次
    assert len(_txns(transaction_type=TxnType.PURCHASE_IN_REVERSAL)) == 1
    assert f"{_balance(wh, mid)['quantity']}" == "0.0000"


def test_concurrent_reverse_only_one_succeeds(client: TestClient, db) -> None:
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_confirmed_po(client, admin, mid, sup, qty="10")
    wh_h = _wh_headers(client)
    rid = _post_receipt(client, wh_h, po["id"], wh,
                        [{"po_item_id": po["items"][0]["id"], "received_quantity": "10"}]
                        ).json()["data"]["id"]

    results: list[int] = []
    lock = threading.Lock()
    barrier = threading.Barrier(8)

    def worker() -> None:
        barrier.wait()
        r = client.post(f"/api/v1/purchase-receipts/{rid}/reverse", headers=wh_h,
                        json={"reason": "并发冲销"})
        with lock:
            results.append(r.status_code)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(200) == 1, results
    assert results.count(409) == 7, results
    assert len(_txns(transaction_type=TxnType.PURCHASE_IN_REVERSAL)) == 1
    assert f"{_balance(wh, mid)['quantity']}" == "0.0000"


def test_reverse_allowed_for_inactive_material(client: TestClient, db) -> None:
    """§二十九：物料停用后仍允许冲销（撤销历史错误不应被当前主数据阻断）。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_confirmed_po(client, admin, mid, sup, qty="10")
    wh_h = _wh_headers(client)
    rid = _post_receipt(client, wh_h, po["id"], wh,
                        [{"po_item_id": po["items"][0]["id"], "received_quantity": "6"}]
                        ).json()["data"]["id"]
    assert client.post(f"/api/v1/materials/{mid}/disable", headers=admin).status_code == 200
    r = client.post(f"/api/v1/purchase-receipts/{rid}/reverse", headers=wh_h,
                    json={"reason": "停用物料仍可冲销"})
    assert r.status_code == 200, r.text
    assert f"{_balance(wh, mid)['quantity']}" == "0.0000"


def test_reverse_multi_item_receipt(client: TestClient, db) -> None:
    """整单冲销：多明细一次性全部回退（§十八 第一版不支持部分冲销）。"""
    _clean_all()
    admin = _auth(_login(client))
    m1 = _create_material(client, admin, "冲销物料A")["id"]
    m2 = _create_material(client, admin, "冲销物料B")["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    pr1 = _mk_approved_pr(client, m1, qty="40")
    pr2 = _mk_approved_pr(client, m2, qty="20")
    po = _mk_po(client, sup, [
        {"pr_id": pr1["id"], "pr_item_id": pr1["items"][0]["id"],
         "quantity": "40", "ordered_quantity": "40"},
        {"pr_id": pr2["id"], "pr_item_id": pr2["items"][0]["id"],
         "quantity": "20", "ordered_quantity": "20"},
    ])
    po = _confirm_po(client, _auth(_login(client, "wangwu", "demo123")), po["id"], po["version"])
    wh_h = _wh_headers(client)
    rcpt = _post_receipt(client, wh_h, po["id"], wh, [
        {"po_item_id": po["items"][0]["id"], "received_quantity": "40"},
        {"po_item_id": po["items"][1]["id"], "received_quantity": "20"},
    ]).json()["data"]
    assert f"{_balance(wh, m1)['quantity']}" == "40.0000"
    assert f"{_balance(wh, m2)['quantity']}" == "20.0000"

    r = client.post(f"/api/v1/purchase-receipts/{rcpt['id']}/reverse", headers=wh_h,
                    json={"reason": "整单退回"})
    assert r.status_code == 200, r.text
    assert f"{_balance(wh, m1)['quantity']}" == "0.0000"
    assert f"{_balance(wh, m2)['quantity']}" == "0.0000"
    assert len(_txns(transaction_type=TxnType.PURCHASE_IN_REVERSAL)) == 2
    b = _auth(_login(client, "wangwu", "demo123"))
    assert _po_detail(client, b, po["id"])["status"] == "CONFIRMED"


# ======================================================================
# 四十一：事务原子性
# ======================================================================
def test_receipt_second_item_over_remaining_rolls_back(client: TestClient, db) -> None:
    """61：多明细入库第 2 行超收 → 整单回滚，第 1 行不留下任何影响。"""
    _clean_all()
    admin = _auth(_login(client))
    m1 = _create_material(client, admin, "原子性物料A")["id"]
    m2 = _create_material(client, admin, "原子性物料B")["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    pr1 = _mk_approved_pr(client, m1, qty="10")
    pr2 = _mk_approved_pr(client, m2, qty="10")
    po = _mk_po(client, sup, [
        {"pr_id": pr1["id"], "pr_item_id": pr1["items"][0]["id"],
         "quantity": "10", "ordered_quantity": "10"},
        {"pr_id": pr2["id"], "pr_item_id": pr2["items"][0]["id"],
         "quantity": "10", "ordered_quantity": "10"},
    ])
    po = _confirm_po(client, _auth(_login(client, "wangwu", "demo123")), po["id"], po["version"])
    wh_h = _wh_headers(client)

    r = _post_receipt(client, wh_h, po["id"], wh, [
        {"po_item_id": po["items"][0]["id"], "received_quantity": "5"},   # 合法
        {"po_item_id": po["items"][1]["id"], "received_quantity": "50"},  # 超收
    ])
    assert r.status_code == 409 and r.json()["code"] == 6002, r.text

    assert _count(PurchaseReceipt) == 0
    assert _count(PurchaseReceiptItem) == 0
    assert _count(InventoryTransaction) == 0
    assert _balance(wh, m1) is None and _balance(wh, m2) is None
    b = _auth(_login(client, "wangwu", "demo123"))
    detail = _po_detail(client, b, po["id"])
    assert detail["items"][0]["received_quantity"] == "0.0000"
    assert detail["status"] == "CONFIRMED"


def test_receipt_rollback_when_balance_update_fails(client: TestClient, db, monkeypatch) -> None:
    """62：余额写入失败 → 入库单 / PO 收货 / 流水 全部回滚。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_confirmed_po(client, admin, mid, sup, qty="10")
    wh_h = _wh_headers(client)

    original = inventory_service.apply_inbound

    def boom(*args, **kwargs):
        raise ConflictException("模拟余额写入失败", code=6009)

    monkeypatch.setattr(inventory_service, "apply_inbound", boom)
    try:
        r = _post_receipt(client, wh_h, po["id"], wh,
                          [{"po_item_id": po["items"][0]["id"], "received_quantity": "3"}])
        assert r.status_code == 409, r.text
    finally:
        monkeypatch.setattr(inventory_service, "apply_inbound", original)

    assert _count(PurchaseReceipt) == 0
    assert _count(PurchaseReceiptItem) == 0
    assert _count(InventoryTransaction) == 0
    assert _balance(wh, mid) is None
    b = _auth(_login(client, "wangwu", "demo123"))
    assert _po_detail(client, b, po["id"])["items"][0]["received_quantity"] == "0.0000"


def test_receipt_rollback_when_audit_fails(client: TestClient, db, monkeypatch) -> None:
    """63：审计写入失败 → 整个入库事务回滚（业务与审计同生共死）。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_confirmed_po(client, admin, mid, sup, qty="10")
    wh_h = _wh_headers(client)

    original = audit_service.write_audit

    def boom(*args, **kwargs):
        raise ConflictException("模拟审计写入失败", code=6009)

    monkeypatch.setattr(audit_service, "write_audit", boom)
    try:
        r = _post_receipt(client, wh_h, po["id"], wh,
                          [{"po_item_id": po["items"][0]["id"], "received_quantity": "3"}])
        assert r.status_code == 409, r.text
    finally:
        monkeypatch.setattr(audit_service, "write_audit", original)

    assert _count(PurchaseReceipt) == 0
    assert _count(InventoryTransaction) == 0
    assert _balance(wh, mid) is None


# ======================================================================
# 四十二：权限
# ======================================================================
def test_receipt_create_permission_matrix(client: TestClient, db) -> None:
    """64-68：WAREHOUSE/ADMIN 可收货；BUYER/APPLICANT/DEPT_MANAGER 403。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]

    def attempt(username: str) -> int:
        po = _mk_confirmed_po(client, admin, mid, sup, qty="10")
        headers = _auth(_login(client, username, "demo123" if username != "admin" else "admin123"))
        r = _post_receipt(client, headers, po["id"], wh,
                          [{"po_item_id": po["items"][0]["id"], "received_quantity": "1"}])
        return r.status_code

    assert attempt("zhaoliu") == 200      # 64. WAREHOUSE
    assert attempt("admin") == 200        # 68. ADMIN
    assert attempt("wangwu") == 403       # 65. BUYER
    assert attempt("zhangsan") == 403     # 66. APPLICANT
    assert attempt("lisi") == 403         # 67. DEPT_MANAGER


def test_reverse_permission_denied_for_buyer(client: TestClient, db) -> None:
    """71：无 receipt:reverse 不能冲销。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_confirmed_po(client, admin, mid, sup, qty="10")
    wh_h = _wh_headers(client)
    rid = _post_receipt(client, wh_h, po["id"], wh,
                        [{"po_item_id": po["items"][0]["id"], "received_quantity": "2"}]
                        ).json()["data"]["id"]
    for username in ("wangwu", "zhangsan", "lisi"):
        headers = _auth(_login(client, username, "demo123"))
        r = client.post(f"/api/v1/purchase-receipts/{rid}/reverse", headers=headers,
                        json={"reason": "无权限冲销"})
        assert r.status_code == 403, (username, r.text)
    assert client.get(f"/api/v1/purchase-receipts/{rid}", headers=wh_h).json()[
        "data"]["status"] == "POSTED"


def test_receipt_list_visibility_scope(client: TestClient, db) -> None:
    """对象级可见范围：BUYER 见自己订单的入库单；WAREHOUSE/ADMIN 全量。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_confirmed_po(client, admin, mid, sup, qty="10", price="5.0000")
    wh_h = _wh_headers(client)
    rid = _post_receipt(client, wh_h, po["id"], wh,
                        [{"po_item_id": po["items"][0]["id"], "received_quantity": "2"}]
                        ).json()["data"]["id"]

    w = _auth(_login(client, "wangwu", "demo123"))       # BUYER，该 PO 是自己建的
    lst = client.get("/api/v1/purchase-receipts", headers=w).json()["data"]
    assert [x["id"] for x in lst["items"]] == [rid]

    z = _auth(_login(client, "zhaoliu", "demo123"))      # WAREHOUSE 全量
    assert client.get("/api/v1/purchase-receipts", headers=z).json()["data"]["total"] == 1
    # 详情可读
    assert client.get(f"/api/v1/purchase-receipts/{rid}", headers=z).status_code == 200

    a = _auth(_login(client, "zhangsan", "demo123"))     # APPLICANT：PR 是自己提的
    assert client.get(f"/api/v1/purchase-receipts/{rid}", headers=a).status_code == 200


# ======================================================================
# 二十六：列表筛选
# ======================================================================
def test_receipt_list_filters(client: TestClient, db) -> None:
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_confirmed_po(client, admin, mid, sup, qty="10")
    wh_h = _wh_headers(client)
    r1 = _post_receipt(client, wh_h, po["id"], wh,
                       [{"po_item_id": po["items"][0]["id"], "received_quantity": "3"}]
                       ).json()["data"]
    r2 = _post_receipt(client, wh_h, po["id"], wh,
                       [{"po_item_id": po["items"][0]["id"], "received_quantity": "4"}]
                       ).json()["data"]
    client.post(f"/api/v1/purchase-receipts/{r2['id']}/reverse", headers=wh_h,
                json={"reason": "筛选测试"})

    assert client.get(f"/api/v1/purchase-receipts?receipt_no={r1['receipt_no']}",
                      headers=wh_h).json()["data"]["total"] == 1
    assert client.get(f"/api/v1/purchase-receipts?po_no={po['po_no']}",
                      headers=wh_h).json()["data"]["total"] == 2
    assert client.get(f"/api/v1/purchase-receipts?warehouse_id={wh}",
                      headers=wh_h).json()["data"]["total"] == 2
    assert client.get("/api/v1/purchase-receipts?status=REVERSED",
                      headers=wh_h).json()["data"]["total"] == 1
    assert client.get("/api/v1/purchase-receipts?status=POSTED",
                      headers=wh_h).json()["data"]["total"] == 1
    assert client.get(f"/api/v1/purchase-receipts?po_id={po['id']}",
                      headers=wh_h).json()["data"]["total"] == 2


# ======================================================================
# 四十三：全链路验收
# ======================================================================
def test_full_chain_pr_approval_po_receipt_inventory(client: TestClient, db) -> None:
    """Material → Supplier → Warehouse → PR → Submit → Approve → PO → Confirm
    → Receipt 40 → PARTIALLY_RECEIVED / Balance 40
    → Receipt 60 → RECEIVED / Balance 100
    → Transactions 可追溯
    → Reverse 第二张 → PARTIALLY_RECEIVED / Balance 40
    → Reverse 第一张 → CONFIRMED / Balance 0
    """
    _clean_all()
    admin = _auth(_login(client))
    mat = _create_material(client, admin, "全链路物料")
    mid = mat["id"]
    sup = _create_supplier(client, admin, "全链路供应商")
    sup_id = sup["id"]
    wh = _create_warehouse(client, admin, "全链路仓库")
    wh_id = wh["id"]

    # PR → Submit → Approve
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pr(client, z, mid, qty="100", price="10.0000")
    assert re.fullmatch(r"PR-\d{8}-\d{4}", pr["pr_no"])
    submitted = _submit(client, z, pr["id"])
    lisi = _auth(_login(client, "lisi", "demo123"))
    approved = _approve(client, lisi, pr["id"], submitted["version"])
    assert approved["status"] == "APPROVED"

    # PO → Confirm
    po = _mk_po(client, sup_id, [{
        "pr_id": pr["id"], "pr_item_id": pr["items"][0]["id"],
        "quantity": "100", "ordered_quantity": "100",
    }], unit_price="10.0000")
    assert re.fullmatch(r"PO-\d{8}-\d{4}", po["po_no"])
    b = _auth(_login(client, "wangwu", "demo123"))
    po = _confirm_po(client, b, po["id"], po["version"])
    poi = po["items"][0]["id"]
    wh_h = _wh_headers(client)

    # Receipt 40
    r1 = _post_receipt(client, wh_h, po["id"], wh_id,
                       [{"po_item_id": poi, "received_quantity": "40"}])
    assert r1.status_code == 200, r1.text
    rc1 = r1.json()["data"]
    assert _po_detail(client, b, po["id"])["status"] == "PARTIALLY_RECEIVED"
    assert f"{_balance(wh_id, mid)['quantity']}" == "40.0000"

    # Receipt 60
    r2 = _post_receipt(client, wh_h, po["id"], wh_id,
                       [{"po_item_id": poi, "received_quantity": "60"}])
    assert r2.status_code == 200, r2.text
    rc2 = r2.json()["data"]
    assert _po_detail(client, b, po["id"])["status"] == "RECEIVED"
    bal = _balance(wh_id, mid)
    assert f"{bal['quantity']}" == "100.0000"
    assert f"{bal['total_amount']}" == "1000.00"
    assert f"{bal['average_unit_cost']}" == "10.0000"

    # 流水可追溯：两条 PURCHASE_IN，reference 指向各自入库单
    txns = client.get(f"/api/v1/inventory/transactions?material_id={mid}",
                      headers=admin).json()["data"]["items"]
    assert len(txns) == 2
    by_no = {t["reference_no"]: t for t in txns}
    assert set(by_no) == {rc1["receipt_no"], rc2["receipt_no"]}
    assert by_no[rc1["receipt_no"]]["quantity"] == "40.0000"
    assert by_no[rc2["receipt_no"]]["quantity"] == "60.0000"
    assert all(t["transaction_type"] == "PURCHASE_IN" for t in txns)
    assert all(t["operator_name"] == "赵敏" for t in txns)

    # 按入库单号筛选流水
    filtered = client.get(
        f"/api/v1/inventory/transactions?reference_no={rc1['receipt_no']}",
        headers=admin).json()["data"]
    assert filtered["total"] == 1

    # Reverse 第二张（60）→ PARTIALLY_RECEIVED / Balance 40
    assert client.post(f"/api/v1/purchase-receipts/{rc2['id']}/reverse", headers=wh_h,
                       json={"reason": "全链路冲销二"}).status_code == 200
    assert _po_detail(client, b, po["id"])["status"] == "PARTIALLY_RECEIVED"
    assert f"{_balance(wh_id, mid)['quantity']}" == "40.0000"
    assert f"{_balance(wh_id, mid)['total_amount']}" == "400.00"

    # Reverse 第一张（40）→ CONFIRMED / Balance 0
    assert client.post(f"/api/v1/purchase-receipts/{rc1['id']}/reverse", headers=wh_h,
                       json={"reason": "全链路冲销一"}).status_code == 200
    assert _po_detail(client, b, po["id"])["status"] == "CONFIRMED"
    bal = _balance(wh_id, mid)
    assert f"{bal['quantity']}" == "0.0000"
    assert f"{bal['total_amount']}" == "0.00"
    assert f"{bal['average_unit_cost']}" == "0.0000"

    # 全链路审计：PR / PO / 入库 / 冲销 全部留痕
    assert AuditAction.RECEIPT_POST.value in _audit_actions(rc1["receipt_no"])
    assert AuditAction.RECEIPT_REVERSE.value in _audit_actions(rc1["receipt_no"])
    assert AuditAction.PO_CONFIRM.value in _audit_actions(po["po_no"])
    assert AuditAction.PR_APPROVE.value in _audit_actions(pr["pr_no"])
    # 流水 SUM(quantity) 与余额一致（ledger ↔ snapshot 对账）
    with SessionLocal() as s:
        s.rollback()
        from sqlalchemy import func as _func
        net = s.execute(
            select(_func.sum(InventoryTransaction.quantity)).where(
                InventoryTransaction.warehouse_id == wh_id,
                InventoryTransaction.material_id == mid,
            )
        ).scalar()
    assert f"{net}" == "0.0000"


def test_warehouse_with_stock_cannot_be_disabled(client: TestClient, db) -> None:
    """§二十八：真实入库后有非零库存的仓库不能停用；清空后可以。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_confirmed_po(client, admin, mid, sup, qty="10")
    wh_h = _wh_headers(client)
    rid = _post_receipt(client, wh_h, po["id"], wh,
                        [{"po_item_id": po["items"][0]["id"], "received_quantity": "10"}]
                        ).json()["data"]["id"]

    r = client.post(f"/api/v1/warehouses/{wh}/disable", headers=admin)
    assert r.status_code == 409, r.text

    assert client.post(f"/api/v1/purchase-receipts/{rid}/reverse", headers=wh_h,
                       json={"reason": "清空库存"}).status_code == 200
    assert client.post(f"/api/v1/warehouses/{wh}/disable", headers=admin).status_code == 200


# ======================================================================
# Review Fix §3：交叉双物料并发入库（#43 锁序重构验证）
# ======================================================================
def test_cross_material_concurrent_receipts_no_deadlock(client: TestClient, db) -> None:
    """PO_X 行序 [A, B] 与 PO_Y 行序 [B, A] 两 Receipt 并发同仓入库，多轮重复。

    Review Fix §3 / #43：余额锁必须全量预排序后按 (warehouse_id, material_id)
    升序一次性取齐（lock_balances）。若按各 PO 自身的行序逐个锁余额，
    两个行序相反的入库单并发时会形成 A→B 与 B→A 的交叉等待 → InnoDB
    死锁（1213 → 500）。本测试断言：

    - 无未处理 deadlock：所有并发请求均 200（服务层不做 1213 重试，
      出现死锁即 500，直接判失败）；
    - 原子性：每张成功的入库单两条明细全部落库；
    - Balance A/B 数量与金额正确；
    - Transaction 数量与金额正确（每明细一条 PURCHASE_IN）；
    - 无 Lost Update：余额 == 全部入库之和。
    """
    _clean_all()
    admin = _auth(_login(client))
    ma = _create_material(client, admin, "交叉并发物料A")["id"]
    mb = _create_material(client, admin, "交叉并发物料B")["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    wangwu = _auth(_login(client, "wangwu", "demo123"))
    wh_h = _wh_headers(client)

    # 预置两行余额（quantity=0）：并发全部落在 X 锁竞争路径上，避免
    # 首行 INSERT 路径干扰锁序验证。
    with SessionLocal() as s:
        s.rollback()
        for mid in (ma, mb):
            s.execute(text(
                "INSERT INTO inventory_balances"
                " (warehouse_id, material_id, quantity, total_amount,"
                "  average_unit_cost, version)"
                " VALUES (:w, :m, 0, 0, 0, 0)"
            ), {"w": wh, "m": mid})
        s.commit()

    rounds = 4
    qty = "5"           # 每行收满 5
    expected = 2 * rounds * int(qty)   # A/B 各 2×rounds 行 × 5

    def _mk_cross_pairs() -> tuple[dict, dict]:
        """PO_X 行序 [A, B]；PO_Y 行序 [B, A]。返回已 CONFIRMED 的 (po_x, po_y)。"""
        # --- PO_X：A 在前 B 在后 ---
        pr_ax = _mk_approved_pr(client, ma, qty=qty)
        pr_bx = _mk_approved_pr(client, mb, qty=qty)
        po_x = _mk_po(client, sup, [
            {"pr_id": pr_ax["id"], "pr_item_id": pr_ax["items"][0]["id"],
             "quantity": qty, "ordered_quantity": qty},
            {"pr_id": pr_bx["id"], "pr_item_id": pr_bx["items"][0]["id"],
             "quantity": qty, "ordered_quantity": qty},
        ])
        assert [i["material_id"] for i in po_x["items"]] == [ma, mb]
        po_x = _confirm_po(client, wangwu, po_x["id"], po_x["version"])
        # --- PO_Y：B 在前 A 在后（行序与 PO_X 相反）---
        pr_by = _mk_approved_pr(client, mb, qty=qty)
        pr_ay = _mk_approved_pr(client, ma, qty=qty)
        po_y = _mk_po(client, sup, [
            {"pr_id": pr_by["id"], "pr_item_id": pr_by["items"][0]["id"],
             "quantity": qty, "ordered_quantity": qty},
            {"pr_id": pr_ay["id"], "pr_item_id": pr_ay["items"][0]["id"],
             "quantity": qty, "ordered_quantity": qty},
        ])
        assert [i["material_id"] for i in po_y["items"]] == [mb, ma]
        po_y = _confirm_po(client, wangwu, po_y["id"], po_y["version"])
        return po_x, po_y

    def _receipt_payload(po: dict) -> dict:
        return {"po_id": po["id"], "warehouse_id": wh,
                "items": [{"po_item_id": it["id"], "received_quantity": qty}
                          for it in po["items"]]}

    failures: list[str] = []
    lock = threading.Lock()
    all_pos: list[dict] = []

    for _ in range(rounds):
        po_x, po_y = _mk_cross_pairs()
        all_pos.extend([po_x, po_y])
        barrier = threading.Barrier(2)
        results: list[int] = []

        def worker(po: dict) -> None:
            barrier.wait()
            r = _post_receipt(client, wh_h, po["id"], wh,
                              [{"po_item_id": it["id"], "received_quantity": qty}
                               for it in po["items"]])
            with lock:
                results.append(r.status_code)
                if r.status_code != 200:
                    failures.append(r.text[:300])

        threads = [threading.Thread(target=worker, args=(p,))
                   for p in (po_x, po_y)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sorted(results) == [200, 200], f"round deadlock/conflict: {failures}"

    assert failures == [], failures
    assert len(_txns(transaction_type=TxnType.PURCHASE_IN)) == 2 * rounds * 2  # 2 单据 × 2 明细 × rounds

    for mid in (ma, mb):
        bal = _balance(wh, mid)
        assert bal is not None
        assert f"{bal['quantity']}" == f"{expected}.0000", f"Lost update on {mid}"
        assert f"{bal['total_amount']}" == f"{expected * 10}.00"  # 单价 10.0000
        tx_a = _txns(material_id=mid, transaction_type=TxnType.PURCHASE_IN)
        assert len(tx_a) == 2 * rounds
        assert f"{sum(t.quantity for t in tx_a)}" == f"{expected}.0000"
        assert f"{sum(t.amount for t in tx_a)}" == f"{expected * 10}.00"

    # 每张 PO 都应整体收满 → RECEIVED（原子性 + 状态推导正确）
    b = _auth(_login(client, "wangwu", "demo123"))
    for po in all_pos:
        assert _po_detail(client, b, po["id"])["status"] == "RECEIVED"
