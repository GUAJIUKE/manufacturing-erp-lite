"""Phase 8 purchase-order (PO) tests.

Covers: PR -> PO conversion (§9.2: CAS quantity guard, split across POs
(Q3), merge of multiple PRs into one PO (Q4), PR header -> CONVERTED only
when fully converted), supplier/material validation (R4/R5), confirm
(DRAFT -> CONFIRMED, unit_price > 0 per Q9), cancel (R14 + §9.2 rollback of
converted_quantity + PR back to APPROVED), Q2 (APPROVED PR cancel with no
active PO), optimistic-lock 409s, concurrent conversion / confirm atomicity,
RBAC + object-level 403s, list visibility scoping, and the three PO audit
actions.

Helper users (from init_data):
- zhangsan: APPLICANT @ RD (creates PRs)
- lisi:     DEPT_MANAGER @ RD (approves RD PRs)
- wangwu:   BUYER @ PUR (creates / confirms / cancels POs)
- zhaoliu:  WAREHOUSE @ WH (po:view only — full PO list, no write ops)
- admin:    ADMIN (full permissions)
Tests additionally create ``buyer2`` (BUYER @ PUR) for object-level 403s.
"""

from __future__ import annotations

import threading
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db.session import SessionLocal
from app.models import (
    ApprovalRecord,
    OperationLog,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderItemSource,
    PurchaseRequisition,
    PurchaseRequisitionItem,
    Role,
    User,
)
from app.utils.enums import AuditAction, PoStatus, PrStatus, RoleCode


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _login(client: TestClient, username: str = "admin", password: str = "admin123") -> str:
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["data"]["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _clean_po_data() -> None:
    """Wipe PO + sources + PR + approval records (FK order matters).
    Never touches number_sequences — daily PO/PR counters are monotonic."""
    with SessionLocal() as s:
        s.execute(delete(PurchaseOrderItemSource))
        s.execute(delete(PurchaseOrderItem))
        s.execute(delete(PurchaseOrder))
        s.execute(delete(ApprovalRecord))
        s.execute(delete(PurchaseRequisitionItem))
        s.execute(delete(PurchaseRequisition))
        s.commit()


def _create_material(client: TestClient, headers: dict, name: str = "PO测试物料") -> dict:
    r = client.post("/api/v1/materials", headers=headers, json={"material_name": name, "unit": "pcs"})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _create_supplier(client: TestClient, headers: dict, name: str = "PO测试供应商") -> dict:
    r = client.post("/api/v1/suppliers", headers=headers, json={"supplier_name": name})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _disable_supplier(client: TestClient, headers: dict, supplier_id: int) -> None:
    r = client.post(f"/api/v1/suppliers/{supplier_id}/disable", headers=headers)
    assert r.status_code == 200, r.text


def _disable_material(client: TestClient, headers: dict, material_id: int) -> None:
    r = client.post(f"/api/v1/materials/{material_id}/disable", headers=headers)
    assert r.status_code == 200, r.text


def _mk_pr(client: TestClient, headers: dict, material_id: int, qty="10", price="12.3456") -> dict:
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


def _mk_approved_pr(client: TestClient, mid: int, qty="10", price="12.3456") -> dict:
    """zhangsan creates + submits; lisi approves → APPROVED (version=3)."""
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pr(client, z, mid, qty, price)
    assert pr["status"] == "DRAFT" and pr["version"] == 1
    submitted = _submit(client, z, pr["id"])
    assert submitted["status"] == "PENDING" and submitted["version"] == 2
    lisi = _auth(_login(client, "lisi", "demo123"))
    approved = _approve(client, lisi, pr["id"], version=2)
    assert approved["status"] == "APPROVED" and approved["version"] == 3
    return approved


def _mk_po(
    client: TestClient,
    supplier_id: int,
    pr_items: list[dict],
    buyer: str = "wangwu",
    unit_price: str = "12.50",
    **kw,
) -> dict:
    """pr_items: [{"pr_item_id": int, "quantity": str, "ordered_quantity": str}]
    Material id is resolved from the PR item detail in a fresh GET."""
    b = _auth(_login(client, buyer, "demo123"))
    items = []
    for src in pr_items:
        # resolve material_id via PR detail (item list)
        r = client.get(f"/api/v1/purchase-requisitions/{src['pr_id']}", headers=b)
        assert r.status_code == 200, r.text
        line = next(x for x in r.json()["data"]["items"] if x["id"] == src["pr_item_id"])
        items.append({
            "material_id": line["material_id"],
            "ordered_quantity": src["ordered_quantity"],
            "unit_price": unit_price,
            "sources": [{"pr_item_id": src["pr_item_id"], "quantity": src["quantity"]}],
        })
    payload = {"supplier_id": supplier_id, "items": items, **kw}
    r = client.post("/api/v1/purchase-orders", headers=b, json=payload)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _pr_detail(client: TestClient, headers: dict, pr_id: int) -> dict:
    r = client.get(f"/api/v1/purchase-requisitions/{pr_id}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _confirm(client: TestClient, headers: dict, po_id: int, version: int, **kw) -> dict:
    r = client.post(f"/api/v1/purchase-orders/{po_id}/confirm", headers=headers,
                    json={"version": version, **kw})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _cancel(client: TestClient, headers: dict, po_id: int, version: int, **kw) -> dict:
    r = client.post(f"/api/v1/purchase-orders/{po_id}/cancel", headers=headers,
                    json={"version": version, **kw})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _audit_actions(document_no: str) -> set[str]:
    with SessionLocal() as s:
        s.rollback()  # 结束 REPEATABLE READ 快照，看到 API 会话新提交
        rows = s.execute(
            select(OperationLog.action).where(OperationLog.document_no == document_no)
        ).scalars().all()
    return {a.value for a in rows}


def _role_id(code: RoleCode) -> int:
    with SessionLocal() as s:
        return s.execute(select(Role.id).where(Role.role_code == code)).scalar_one()


def _dept_id(code: str) -> int:
    from app.models import Department

    with SessionLocal() as s:
        return s.execute(select(Department.id).where(Department.dept_code == code)).scalar_one()


def _ensure_buyer2(client: TestClient) -> None:
    """Create a second BUYER @ PUR once per session run (object-level 403s)."""
    admin_h = _auth(_login(client))
    with SessionLocal() as s:
        exists = s.execute(select(User.id).where(User.username == "buyer2")).scalar_one_or_none()
    if exists is None:
        r = client.post("/api/v1/users", headers=admin_h, json={
            "username": "buyer2", "password": "demo123", "real_name": "采购员二号",
            "department_id": _dept_id("PUR"), "role_id": _role_id(RoleCode.BUYER),
        })
        assert r.status_code == 200, r.text


def _set_received(client: TestClient, po_id: int, qty: str) -> None:
    """直接写库模拟已收货（Phase 9 收货款式未实现，R14 需此状态）。"""
    with SessionLocal() as s:
        item_id = s.execute(
            select(PurchaseOrderItem.id).where(PurchaseOrderItem.po_id == po_id)
        ).scalar_one()
        s.execute(
            PurchaseOrderItem.__table__.update()
            .where(PurchaseOrderItem.id == item_id)
            .values(received_quantity=Decimal(qty))
        )
        s.commit()


# ----------------------------------------------------------------------
# 1-2: numbering / basic create / amount precision
# ----------------------------------------------------------------------
def test_create_po_basic_and_amounts(client: TestClient, db) -> None:
    _clean_po_data()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)
    pr = _mk_approved_pr(client, mid, qty="10", price="12.3456")
    # 10 × 12.3456 = 123.456 → ROUND_HALF_UP → 123.46
    po = _mk_po(client, sup["id"], [{
        "pr_id": pr["id"], "pr_item_id": pr["items"][0]["id"],
        "ordered_quantity": "10", "quantity": "10",
    }], unit_price="12.3456")
    assert po["status"] == "DRAFT"
    assert po["version"] == 1
    assert po["total_amount"] == "123.46"
    assert po["items"][0]["amount"] == "123.46"
    assert po["po_no"].startswith(f"PO-{date.today():%Y%m%d}-")
    assert len(po["po_no"].split("-")[-1]) == 4
    # 来源映射完整（Q4 可追溯）
    src = po["items"][0]["sources"][0]
    assert src["pr_no"] == pr["pr_no"]
    assert src["quantity"] == "10.0000"
    # PR 全转完 → CONVERTED
    z = _auth(_login(client, "zhangsan", "demo123"))
    assert _pr_detail(client, z, pr["id"])["status"] == "CONVERTED"
    # 审计
    assert {"PO_CREATE"} <= _audit_actions(po["po_no"])


def test_po_no_sequence_increments(client: TestClient, db) -> None:
    _clean_po_data()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)
    pr = _mk_approved_pr(client, mid, qty="20")
    src = {"pr_id": pr["id"], "pr_item_id": pr["items"][0]["id"],
           "ordered_quantity": "10", "quantity": "10"}
    po1 = _mk_po(client, sup["id"], [src])
    po2 = _mk_po(client, sup["id"], [src])
    seq1 = int(po1["po_no"].split("-")[-1])
    seq2 = int(po2["po_no"].split("-")[-1])
    assert seq2 == seq1 + 1


# ----------------------------------------------------------------------
# 3-8: validation chain (supplier / PR status / material / source sum / empty)
# ----------------------------------------------------------------------
def test_create_po_supplier_required_errors(client: TestClient, db) -> None:
    _clean_po_data()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    pr = _mk_approved_pr(client, mid)
    b = _auth(_login(client, "wangwu", "demo123"))
    # 供应商不存在 → 404
    r = client.post("/api/v1/purchase-orders", headers=b, json={
        "supplier_id": 999999, "items": [{"material_id": mid, "ordered_quantity": "1",
                                          "unit_price": "1", "sources": []}],
    })
    assert r.status_code == 404, r.text
    # 供应商停用 → 409 / PO_SUPPLIER_DISABLED(5006)
    sup = _create_supplier(client, admin)
    _disable_supplier(client, admin, sup["id"])
    r = client.post("/api/v1/purchase-orders", headers=b, json={
        "supplier_id": sup["id"], "items": [{"material_id": mid, "ordered_quantity": "1",
                                             "unit_price": "1", "sources": []}],
    })
    assert r.status_code == 409 and r.json()["code"] == 5006, r.text


def test_create_po_pr_not_approved(client: TestClient, db) -> None:
    _clean_po_data()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)
    z = _auth(_login(client, "zhangsan", "demo123"))
    # DRAFT（未提交）PR
    pr = _mk_pr(client, z, mid)
    b = _auth(_login(client, "wangwu", "demo123"))
    r = client.post("/api/v1/purchase-orders", headers=b, json={
        "supplier_id": sup["id"],
        "items": [{"material_id": mid, "ordered_quantity": "10", "unit_price": "1",
                   "sources": [{"pr_item_id": pr["items"][0]["id"], "quantity": "10"}]}],
    })
    assert r.status_code == 409 and r.json()["code"] == 4002, r.text  # PR_INVALID_STATUS_TRANSITION


def test_create_po_material_disabled(client: TestClient, db) -> None:
    _clean_po_data()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)
    pr = _mk_approved_pr(client, mid)
    _disable_material(client, admin, mid)
    b = _auth(_login(client, "wangwu", "demo123"))
    r = client.post("/api/v1/purchase-orders", headers=b, json={
        "supplier_id": sup["id"],
        "items": [{"material_id": mid, "ordered_quantity": "10", "unit_price": "1",
                   "sources": [{"pr_item_id": pr["items"][0]["id"], "quantity": "10"}]}],
    })
    assert r.status_code == 409 and r.json()["code"] == 3009, r.text  # MASTER_DATA_DISABLED


def test_create_po_source_exceeds_ordered(client: TestClient, db) -> None:
    _clean_po_data()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)
    pr = _mk_approved_pr(client, mid, qty="10")
    b = _auth(_login(client, "wangwu", "demo123"))
    # sources 合计 12 > ordered_quantity 10 → 5010
    r = client.post("/api/v1/purchase-orders", headers=b, json={
        "supplier_id": sup["id"],
        "items": [{"material_id": mid, "ordered_quantity": "10", "unit_price": "1",
                   "sources": [{"pr_item_id": pr["items"][0]["id"], "quantity": "12"}]}],
    })
    assert r.status_code == 409 and r.json()["code"] == 5010, r.text


def test_create_po_empty_items_rejected(client: TestClient, db) -> None:
    _clean_po_data()
    admin = _auth(_login(client))
    sup = _create_supplier(client, admin)
    b = _auth(_login(client, "wangwu", "demo123"))
    r = client.post("/api/v1/purchase-orders", headers=b, json={"supplier_id": sup["id"], "items": []})
    assert r.status_code == 422, r.text  # schema min_length=1


# ----------------------------------------------------------------------
# 9-12: split (Q3) / merge (Q4) / over-convert / concurrent convert
# ----------------------------------------------------------------------
def test_split_pr_across_two_pos(client: TestClient, db) -> None:
    """Q3：一 PR（10 个）拆给两张 PO 各 5 → 第一张后 PR 仍 APPROVED，
    第二张转完 → PR CONVERTED；converted_quantity 累积 5 → 10。"""
    _clean_po_data()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)
    pr = _mk_approved_pr(client, mid, qty="10")
    pr_item_id = pr["items"][0]["id"]
    src = {"pr_id": pr["id"], "pr_item_id": pr_item_id, "ordered_quantity": "5", "quantity": "5"}
    po1 = _mk_po(client, sup["id"], [src])
    z = _auth(_login(client, "zhangsan", "demo123"))
    d1 = _pr_detail(client, z, pr["id"])
    assert d1["status"] == "APPROVED"  # 未全转完，头保持 APPROVED
    assert d1["items"][0]["converted_quantity"] == "5.0000"
    po2 = _mk_po(client, sup["id"], [src])
    d2 = _pr_detail(client, z, pr["id"])
    assert d2["status"] == "CONVERTED"  # 全部转完
    assert d2["items"][0]["converted_quantity"] == "10.0000"
    assert po1["id"] != po2["id"]  # 拆成两张独立 PO


def test_merge_two_prs_into_one_po(client: TestClient, db) -> None:
    """Q4：两张 APPROVED PR 合并进一张 PO（各转满）→ 两个 PR 均 CONVERTED。"""
    _clean_po_data()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)
    pr1 = _mk_approved_pr(client, mid, qty="5")
    pr2 = _mk_approved_pr(client, mid, qty="5")
    b = _auth(_login(client, "wangwu", "demo123"))
    payload = {
        "supplier_id": sup["id"],
        "items": [
            {"material_id": mid, "ordered_quantity": "5", "unit_price": "1",
             "sources": [{"pr_item_id": pr1["items"][0]["id"], "quantity": "5"}]},
            {"material_id": mid, "ordered_quantity": "5", "unit_price": "1",
             "sources": [{"pr_item_id": pr2["items"][0]["id"], "quantity": "5"}]},
        ],
    }
    r = client.post("/api/v1/purchase-orders", headers=b, json=payload)
    assert r.status_code == 200, r.text
    po = r.json()["data"]
    assert len(po["items"]) == 2
    z = _auth(_login(client, "zhangsan", "demo123"))
    assert _pr_detail(client, z, pr1["id"])["status"] == "CONVERTED"
    assert _pr_detail(client, z, pr2["id"])["status"] == "CONVERTED"


def test_convert_exceeds_remaining(client: TestClient, db) -> None:
    _clean_po_data()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)
    pr = _mk_approved_pr(client, mid, qty="10")
    src = {"pr_id": pr["id"], "pr_item_id": pr["items"][0]["id"],
           "ordered_quantity": "7", "quantity": "7"}
    _mk_po(client, sup["id"], [src])
    # 剩余 3，试图再转 5 → 4009
    b = _auth(_login(client, "wangwu", "demo123"))
    r = client.post("/api/v1/purchase-orders", headers=b, json={
        "supplier_id": sup["id"],
        "items": [{"material_id": mid, "ordered_quantity": "5", "unit_price": "1",
                   "sources": [{"pr_item_id": pr["items"][0]["id"], "quantity": "5"}]}],
    })
    assert r.status_code == 409 and r.json()["code"] == 4009, r.text


def test_concurrent_convert_only_one_succeeds(client: TestClient, db) -> None:
    """并发转单：两张 PO 同时转同一 PR 明细，CAS 保证恰一成功（另一 409）。"""
    _clean_po_data()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)
    pr = _mk_approved_pr(client, mid, qty="10")
    pr_item_id = pr["items"][0]["id"]
    b_headers = _auth(_login(client, "wangwu", "demo123"))
    results: list[int] = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        barrier.wait()
        r = client.post("/api/v1/purchase-orders", headers=b_headers, json={
            "supplier_id": sup["id"],
            "items": [{"material_id": mid, "ordered_quantity": "10", "unit_price": "1",
                       "sources": [{"pr_item_id": pr_item_id, "quantity": "10"}]}],
        })
        results.append(r.status_code)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(200) == 1
    assert results.count(409) == 1  # 超转 4009 或状态已 CONVERTED 4002，均为 409


# ----------------------------------------------------------------------
# 13-18: confirm
# ----------------------------------------------------------------------
def test_confirm_po_zero_price_rejected(client: TestClient, db) -> None:
    _clean_po_data()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)
    pr = _mk_approved_pr(client, mid)
    b = _auth(_login(client, "wangwu", "demo123"))
    # DRAFT 允许单价 0（Q9）
    r = client.post("/api/v1/purchase-orders", headers=b, json={
        "supplier_id": sup["id"],
        "items": [{"material_id": mid, "ordered_quantity": "10", "unit_price": "0",
                   "sources": [{"pr_item_id": pr["items"][0]["id"], "quantity": "10"}]}],
    })
    assert r.status_code == 200, r.text
    po = r.json()["data"]
    # confirm 时强制 > 0 → 5007
    r = client.post(f"/api/v1/purchase-orders/{po['id']}/confirm", headers=b,
                    json={"version": po["version"]})
    assert r.status_code == 409 and r.json()["code"] == 5007, r.text


def test_confirm_po_success(client: TestClient, db) -> None:
    _clean_po_data()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)
    pr = _mk_approved_pr(client, mid)
    po = _mk_po(client, sup["id"], [{
        "pr_id": pr["id"], "pr_item_id": pr["items"][0]["id"],
        "ordered_quantity": "10", "quantity": "10",
    }])
    b = _auth(_login(client, "wangwu", "demo123"))
    confirmed = _confirm(client, b, po["id"], po["version"])
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["version"] == po["version"] + 1
    assert {"PO_CREATE", "PO_CONFIRM"} <= _audit_actions(po["po_no"])


def test_confirm_po_twice_rejected(client: TestClient, db) -> None:
    _clean_po_data()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)
    pr = _mk_approved_pr(client, mid)
    po = _mk_po(client, sup["id"], [{
        "pr_id": pr["id"], "pr_item_id": pr["items"][0]["id"],
        "ordered_quantity": "10", "quantity": "10",
    }])
    b = _auth(_login(client, "wangwu", "demo123"))
    confirmed = _confirm(client, b, po["id"], po["version"])
    r = client.post(f"/api/v1/purchase-orders/{po['id']}/confirm", headers=b,
                    json={"version": confirmed["version"]})
    assert r.status_code == 409 and r.json()["code"] == 5002, r.text


def test_confirm_po_stale_version(client: TestClient, db) -> None:
    _clean_po_data()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)
    pr = _mk_approved_pr(client, mid)
    po = _mk_po(client, sup["id"], [{
        "pr_id": pr["id"], "pr_item_id": pr["items"][0]["id"],
        "ordered_quantity": "10", "quantity": "10",
    }])
    b = _auth(_login(client, "wangwu", "demo123"))
    r = client.post(f"/api/v1/purchase-orders/{po['id']}/confirm", headers=b,
                    json={"version": 99})
    assert r.status_code == 409 and r.json()["code"] == 5012, r.text  # PO_VERSION_CONFLICT


def test_concurrent_confirm_only_one_succeeds(client: TestClient, db) -> None:
    _clean_po_data()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)
    pr = _mk_approved_pr(client, mid)
    po = _mk_po(client, sup["id"], [{
        "pr_id": pr["id"], "pr_item_id": pr["items"][0]["id"],
        "ordered_quantity": "10", "quantity": "10",
    }])
    b = _auth(_login(client, "wangwu", "demo123"))
    version = po["version"]
    results: list[int] = []
    barrier = threading.Barrier(8)

    def worker() -> None:
        barrier.wait()
        r = client.post(f"/api/v1/purchase-orders/{po['id']}/confirm", headers=b,
                        json={"version": version})
        results.append(r.status_code)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(200) == 1
    assert results.count(409) == 7


def test_confirm_po_buyer_only_admin_override(client: TestClient, db) -> None:
    _clean_po_data()
    admin_h = _auth(_login(client))
    mid = _create_material(client, admin_h)["id"]
    sup = _create_supplier(client, admin_h)
    pr = _mk_approved_pr(client, mid)
    po = _mk_po(client, sup["id"], [{
        "pr_id": pr["id"], "pr_item_id": pr["items"][0]["id"],
        "ordered_quantity": "10", "quantity": "10",
    }])
    # APPLICANT（zhangsan）无 po:confirm → 403（RBAC 第一层）
    z = _auth(_login(client, "zhangsan", "demo123"))
    r = client.post(f"/api/v1/purchase-orders/{po['id']}/confirm", headers=z,
                    json={"version": po["version"]})
    assert r.status_code == 403, r.text
    # ADMIN override → 200
    confirmed = _confirm(client, admin_h, po["id"], po["version"])
    assert confirmed["status"] == "CONFIRMED"


# ----------------------------------------------------------------------
# 19-22: cancel (R14 + §9.2 rollback)
# ----------------------------------------------------------------------
def test_cancel_po_rolls_back_pr(client: TestClient, db) -> None:
    """取消 → converted_quantity 回退、PR 回退 APPROVED；审计 PO_CANCEL。"""
    _clean_po_data()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)
    pr = _mk_approved_pr(client, mid, qty="10")
    src = {"pr_id": pr["id"], "pr_item_id": pr["items"][0]["id"],
           "ordered_quantity": "10", "quantity": "10"}
    po = _mk_po(client, sup["id"], [src])
    z = _auth(_login(client, "zhangsan", "demo123"))
    assert _pr_detail(client, z, pr["id"])["status"] == "CONVERTED"
    b = _auth(_login(client, "wangwu", "demo123"))
    cancelled = _cancel(client, b, po["id"], po["version"], reason="计划调整")
    assert cancelled["status"] == "CANCELLED"
    d = _pr_detail(client, z, pr["id"])
    assert d["status"] == "APPROVED"  # 回退
    assert d["items"][0]["converted_quantity"] == "0.0000"  # 回退
    assert {"PO_CANCEL"} <= _audit_actions(po["po_no"])


def test_cancel_po_with_receipt_rejected(client: TestClient, db) -> None:
    _clean_po_data()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)
    pr = _mk_approved_pr(client, mid)
    po = _mk_po(client, sup["id"], [{
        "pr_id": pr["id"], "pr_item_id": pr["items"][0]["id"],
        "ordered_quantity": "10", "quantity": "10",
    }])
    _set_received(client, po["id"], "3")  # 模拟已部分收货
    b = _auth(_login(client, "wangwu", "demo123"))
    r = client.post(f"/api/v1/purchase-orders/{po['id']}/cancel", headers=b,
                    json={"version": po["version"]})
    assert r.status_code == 409 and r.json()["code"] == 5008, r.text  # PO_CANCEL_HAS_RECEIPT


def test_cancel_po_twice_rejected(client: TestClient, db) -> None:
    _clean_po_data()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)
    pr = _mk_approved_pr(client, mid)
    po = _mk_po(client, sup["id"], [{
        "pr_id": pr["id"], "pr_item_id": pr["items"][0]["id"],
        "ordered_quantity": "10", "quantity": "10",
    }])
    b = _auth(_login(client, "wangwu", "demo123"))
    cancelled = _cancel(client, b, po["id"], po["version"])
    r = client.post(f"/api/v1/purchase-orders/{po['id']}/cancel", headers=b,
                    json={"version": cancelled["version"]})
    assert r.status_code == 409 and r.json()["code"] == 5002, r.text


def test_cancel_po_stale_version(client: TestClient, db) -> None:
    _clean_po_data()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)
    pr = _mk_approved_pr(client, mid)
    po = _mk_po(client, sup["id"], [{
        "pr_id": pr["id"], "pr_item_id": pr["items"][0]["id"],
        "ordered_quantity": "10", "quantity": "10",
    }])
    b = _auth(_login(client, "wangwu", "demo123"))
    r = client.post(f"/api/v1/purchase-orders/{po['id']}/cancel", headers=b,
                    json={"version": 99})
    assert r.status_code == 409 and r.json()["code"] == 5012, r.text


def test_cancel_po_confirmed_state(client: TestClient, db) -> None:
    """CONFIRMED 的订单也可取消（未收货）→ 回退。"""
    _clean_po_data()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)
    pr = _mk_approved_pr(client, mid)
    po = _mk_po(client, sup["id"], [{
        "pr_id": pr["id"], "pr_item_id": pr["items"][0]["id"],
        "ordered_quantity": "10", "quantity": "10",
    }])
    b = _auth(_login(client, "wangwu", "demo123"))
    confirmed = _confirm(client, b, po["id"], po["version"])
    cancelled = _cancel(client, b, po["id"], confirmed["version"])
    assert cancelled["status"] == "CANCELLED"


# ----------------------------------------------------------------------
# 23-25: Q2 — APPROVED PR cancel rules
# ----------------------------------------------------------------------
def test_cancel_approved_pr_without_po(client: TestClient, db) -> None:
    _clean_po_data()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    pr = _mk_approved_pr(client, mid)
    z = _auth(_login(client, "zhangsan", "demo123"))
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/cancel", headers=z)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "CANCELLED"


def test_cancel_approved_pr_with_active_po_rejected(client: TestClient, db) -> None:
    """PR 部分转出（仍 APPROVED）且存在 active PO → Q2 限制取消（4008）。"""
    _clean_po_data()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)
    pr = _mk_approved_pr(client, mid, qty="10")
    # 只转 5 → PR 保持 APPROVED（有 active PO 引用）
    _mk_po(client, sup["id"], [{
        "pr_id": pr["id"], "pr_item_id": pr["items"][0]["id"],
        "ordered_quantity": "5", "quantity": "5",
    }])
    z = _auth(_login(client, "zhangsan", "demo123"))
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/cancel", headers=z)
    assert r.status_code == 409 and r.json()["code"] == 4008, r.text  # PR_CANCEL_HAS_ACTIVE_PO


def test_cancel_approved_pr_after_po_cancelled(client: TestClient, db) -> None:
    """PO 全部取消后，PR 不再受 Q2 限制 → 可取消。"""
    _clean_po_data()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)
    pr = _mk_approved_pr(client, mid)
    po = _mk_po(client, sup["id"], [{
        "pr_id": pr["id"], "pr_item_id": pr["items"][0]["id"],
        "ordered_quantity": "10", "quantity": "10",
    }])
    b = _auth(_login(client, "wangwu", "demo123"))
    _cancel(client, b, po["id"], po["version"])
    z = _auth(_login(client, "zhangsan", "demo123"))
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/cancel", headers=z)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "CANCELLED"


# ----------------------------------------------------------------------
# 26-27: RBAC / object-level 403s
# ----------------------------------------------------------------------
def test_po_permission_matrix(client: TestClient, db) -> None:
    _clean_po_data()
    admin_h = _auth(_login(client))
    mid = _create_material(client, admin_h)["id"]
    sup = _create_supplier(client, admin_h)
    pr = _mk_approved_pr(client, mid)
    # zhangsan（APPLICANT）无 po:create → 403
    z = _auth(_login(client, "zhangsan", "demo123"))
    r = client.post("/api/v1/purchase-orders", headers=z, json={
        "supplier_id": sup["id"], "items": [{"material_id": mid, "ordered_quantity": "1",
                                             "unit_price": "1", "sources": []}],
    })
    assert r.status_code == 403, r.text
    # zhaoliu（WAREHOUSE）无 po:confirm → 403
    po = _mk_po(client, sup["id"], [{
        "pr_id": pr["id"], "pr_item_id": pr["items"][0]["id"],
        "ordered_quantity": "10", "quantity": "10",
    }])
    wh = _auth(_login(client, "zhaoliu", "demo123"))
    r = client.post(f"/api/v1/purchase-orders/{po['id']}/confirm", headers=wh,
                    json={"version": po["version"]})
    assert r.status_code == 403, r.text


def test_po_object_level_other_buyer(client: TestClient, db) -> None:
    """buyer2 不能 confirm/cancel wangwu 创建的 PO（服务层对象级 403）。"""
    _ensure_buyer2(client)
    _clean_po_data()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)
    pr = _mk_approved_pr(client, mid)
    po = _mk_po(client, sup["id"], [{
        "pr_id": pr["id"], "pr_item_id": pr["items"][0]["id"],
        "ordered_quantity": "10", "quantity": "10",
    }], buyer="wangwu")
    b2 = _auth(_login(client, "buyer2", "demo123"))
    r = client.post(f"/api/v1/purchase-orders/{po['id']}/confirm", headers=b2,
                    json={"version": po["version"]})
    assert r.status_code == 403, r.text
    r = client.post(f"/api/v1/purchase-orders/{po['id']}/cancel", headers=b2,
                    json={"version": po["version"]})
    assert r.status_code == 403, r.text


# ----------------------------------------------------------------------
# 28-29: list / detail visibility scope
# ----------------------------------------------------------------------
def test_po_list_visibility_scope(client: TestClient, db) -> None:
    """APPLICANT 只见自己 PR 转出的 PO；WAREHOUSE 见全部。"""
    _clean_po_data()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)
    pr1 = _mk_approved_pr(client, mid, qty="5")
    pr2 = _mk_approved_pr(client, mid, qty="5")
    po1 = _mk_po(client, sup["id"], [{
        "pr_id": pr1["id"], "pr_item_id": pr1["items"][0]["id"],
        "ordered_quantity": "5", "quantity": "5",
    }])
    po2 = _mk_po(client, sup["id"], [{
        "pr_id": pr2["id"], "pr_item_id": pr2["items"][0]["id"],
        "ordered_quantity": "5", "quantity": "5",
    }])
    z = _auth(_login(client, "zhangsan", "demo123"))
    r = client.get("/api/v1/purchase-orders", headers=z)
    assert r.status_code == 200
    ids = [x["id"] for x in r.json()["data"]["items"]]
    assert po1["id"] in ids and po2["id"] in ids  # 两条 PR 都是 zhangsan 的
    # DEPT_MANAGER（lisi @ RD）同样可见
    lisi = _auth(_login(client, "lisi", "demo123"))
    r = client.get("/api/v1/purchase-orders", headers=lisi)
    assert r.json()["data"]["total"] == 2
    # WAREHOUSE 全量
    wh = _auth(_login(client, "zhaoliu", "demo123"))
    r = client.get("/api/v1/purchase-orders", headers=wh)
    assert r.status_code == 200 and r.json()["data"]["total"] == 2


def test_get_po_foreign_chain_forbidden(client: TestClient, db) -> None:
    """创建另一申请人（by1）的 PR→PO，zhangsan 访问该 PO → 403（不泄漏存在性）。"""
    _clean_po_data()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)
    # 造一个 buyuser（APPLICANT @ RD），已存在则复用（测试可重复运行）
    with SessionLocal() as s:
        exists = s.execute(select(User.id).where(User.username == "by1")).scalar_one_or_none()
    if exists is None:
        r = client.post("/api/v1/users", headers=admin, json={
            "username": "by1", "password": "demo123", "real_name": "申请人乙",
            "department_id": _dept_id("RD"), "role_id": _role_id(RoleCode.APPLICANT),
        })
        assert r.status_code == 200, r.text
    by1 = _auth(_login(client, "by1", "demo123"))
    pr = _mk_pr(client, by1, mid)
    submitted = _submit(client, by1, pr["id"])
    lisi = _auth(_login(client, "lisi", "demo123"))
    approved = _approve(client, lisi, pr["id"], submitted["version"])
    po = _mk_po(client, sup["id"], [{
        "pr_id": approved["id"], "pr_item_id": approved["items"][0]["id"],
        "ordered_quantity": "10", "quantity": "10",
    }])
    z = _auth(_login(client, "zhangsan", "demo123"))
    r = client.get(f"/api/v1/purchase-orders/{po['id']}", headers=z)
    assert r.status_code == 403, r.text


# ----------------------------------------------------------------------
# 30: audit actions for the three PO operations
# ----------------------------------------------------------------------
def test_po_audit_full_chain(client: TestClient, db) -> None:
    _clean_po_data()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)
    pr = _mk_approved_pr(client, mid)
    po = _mk_po(client, sup["id"], [{
        "pr_id": pr["id"], "pr_item_id": pr["items"][0]["id"],
        "ordered_quantity": "10", "quantity": "10",
    }])
    b = _auth(_login(client, "wangwu", "demo123"))
    confirmed = _confirm(client, b, po["id"], po["version"])
    _cancel(client, b, po["id"], confirmed["version"])
    actions = _audit_actions(po["po_no"])
    assert {"PO_CREATE", "PO_CONFIRM", "PO_CANCEL"} <= actions
    # PR 侧审计不受影响
    assert {"PR_APPROVE"} <= _audit_actions(pr["pr_no"])
