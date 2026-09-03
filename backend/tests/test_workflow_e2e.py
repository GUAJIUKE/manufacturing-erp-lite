"""Phase 12 E2E: the canonical business story walked end-to-end (scenarios 1-15).

Runs against the real test DB (Q14). Wipes business data at module start so
ledger/balance sums are deterministic, then replays the full chain over HTTP:

    login x5 -> create material -> PR(DRAFT) -> submit(PENDING)
    -> BUYER approve blocked (2005) -> DEPT_MANAGER approve (APPROVED)
    -> create PO from DRAFT PR blocked (4002) -> create PO (DRAFT) -> confirm
    (CONFIRMED) -> APPLICANT receive blocked (2005) -> receive 40
    (PARTIALLY_RECEIVED) -> over-receive blocked (6002) -> receive 60 (RECEIVED)
    -> receive-on-RECEIVED blocked (5009) -> cancel APPROVED PR w/ PO blocked
    (4008) -> resubmit APPROVED PR blocked (409) -> reverse 60
    (PARTIALLY_RECEIVED) -> double reverse blocked (409) -> ledger == balance

Scenario map (roadmap §Phase 12):
  1 login · 2 create material · 3 create PR · 4 submit PR · 5 approve PR
  6 create PO · 7 confirm PO · 8 full receipt (part of 10) · 9 partial receipt
  10 PO -> RECEIVED · 11 inventory change (balance + ledger + amount)
  12 illegal transitions · 13 over-receipt · 15 permission guardrails.
  Scenario 14 (concurrent receipt idempotency) is covered by the threaded CAS
  tests in test_purchase_receipt.py and is intentionally not repeated here.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.models import InventoryBalance, InventoryTransaction
from cleanup_helper import wipe_business_data


@pytest.fixture(scope="module", autouse=True)
def _isolated_business_data() -> None:
    """Wipe chain + master data once so document/ledger counters are ours."""
    wipe_business_data()


def _login(client: TestClient, username: str, password: str) -> str:
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["data"]["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _ok(client: TestClient, headers: dict, method: str, url: str, **kw) -> dict:
    r = client.request(method, url, headers=headers, **kw)
    assert r.status_code == 200, f"{method} {url} -> {r.status_code} {r.text}"
    body = r.json()
    assert body["code"] == 0, f"{method} {url} -> {body}"
    return body["data"]


def _login_all(client: TestClient) -> dict[str, dict[str, str]]:
    return {
        "admin": _auth(_login(client, "admin", "admin123")),
        "zh": _auth(_login(client, "zhangsan", "demo123")),
        "li": _auth(_login(client, "lisi", "demo123")),
        "ww": _auth(_login(client, "wangwu", "demo123")),
        "zl": _auth(_login(client, "zhaoliu", "demo123")),
    }


def test_e2e_login_all_five_roles(client: TestClient) -> None:
    """Scenario 1: login success for every demo account (admin + 4 business roles)."""
    H = _login_all(client)
    expect = {"admin": "ADMIN", "zh": "APPLICANT", "li": "DEPT_MANAGER",
              "ww": "BUYER", "zl": "WAREHOUSE"}
    for key, role in expect.items():
        me = _ok(client, H[key], "GET", "/api/v1/auth/me")
        assert me["role_code"] == role


def test_e2e_full_business_story(client: TestClient, db) -> None:
    """Scenarios 2-13 + 15: one deterministic walk of the whole purchase chain."""
    H = _login_all(client)

    # -- Scenario 2: create material / supplier / warehouse (auto codes)
    mat = _ok(client, H["admin"], "POST", "/api/v1/materials",
              json={"material_name": "P12 铝合金外壳", "unit": "pcs", "category": "结构件"})
    assert re.fullmatch(r"MAT-\d{6}", mat["material_code"])
    sup = _ok(client, H["admin"], "POST", "/api/v1/suppliers",
              json={"supplier_name": "P12 冲压外协厂", "contact_person": "李工"})
    assert re.fullmatch(r"SUP-\d{6}", sup["supplier_code"])
    wh = _ok(client, H["admin"], "POST", "/api/v1/warehouses",
             json={"warehouse_name": "P12 原材料仓"})
    assert re.fullmatch(r"WH-\d{6}", wh["warehouse_code"])

    # -- Scenario 3: create PR (DRAFT) ; Scenario 4: submit -> PENDING
    pr = _ok(client, H["zh"], "POST", "/api/v1/purchase-requisitions", json={
        "reason": "P12 E2E 样机备料",
        "items": [{"material_id": mat["id"], "requested_quantity": "100",
                   "estimated_unit_price": "10"}],
    })
    assert pr["status"] == "DRAFT"
    assert re.fullmatch(r"PR-\d{8}-\d{4,}", pr["pr_no"])
    pr_id = pr["id"]
    pr = _ok(client, H["zh"], "POST", f"/api/v1/purchase-requisitions/{pr_id}/submit")
    assert pr["status"] == "PENDING"
    submit_version = pr["version"]

    # -- Scenario 15a: 越权审批 —— BUYER 无 pr:approve
    r = client.post(f"/api/v1/purchase-requisitions/{pr_id}/approve",
                    headers=H["ww"], json={"version": submit_version})
    assert r.status_code == 403 and r.json()["code"] == 2005

    # -- Scenario 5: DEPT_MANAGER approve -> APPROVED (+ approval history)
    _ok(client, H["li"], "POST", f"/api/v1/purchase-requisitions/{pr_id}/approve",
        json={"version": submit_version, "comment": "同意备料"})
    pr = _ok(client, H["zh"], "GET", f"/api/v1/purchase-requisitions/{pr_id}")
    assert pr["status"] == "APPROVED"
    history = _ok(client, H["zh"], "GET", f"/api/v1/purchase-requisitions/{pr_id}/approvals")
    assert len(history) == 1 and history[0]["action"] == "APPROVE"

    # -- Scenario 6 guardrail: 未审批 PR 不可转单 (DRAFT PR -> 4002)
    draft_pr = _ok(client, H["zh"], "POST", "/api/v1/purchase-requisitions", json={
        "reason": "P12 E2E 未提交申请",
        "items": [{"material_id": mat["id"], "requested_quantity": "5",
                   "estimated_unit_price": "10"}],
    })
    draft_line = _ok(client, H["ww"], "GET",
                     f"/api/v1/purchase-requisitions/{draft_pr['id']}")["items"][0]
    r = client.post("/api/v1/purchase-orders", headers=H["ww"], json={
        "supplier_id": sup["id"],
        "items": [{"material_id": mat["id"], "ordered_quantity": "5", "unit_price": "10",
                   "sources": [{"pr_item_id": draft_line["id"], "quantity": "5"}]}],
    })
    assert r.status_code == 409 and r.json()["code"] == 4002

    # -- Scenario 6: create PO from APPROVED PR -> DRAFT ; Scenario 7: confirm
    pr_line = _ok(client, H["ww"], "GET", f"/api/v1/purchase-requisitions/{pr_id}")["items"][0]
    po = _ok(client, H["ww"], "POST", "/api/v1/purchase-orders", json={
        "supplier_id": sup["id"],
        "items": [{"material_id": mat["id"], "ordered_quantity": "100", "unit_price": "10",
                   "sources": [{"pr_item_id": pr_line["id"], "quantity": "100"}]}],
    })
    assert po["status"] == "DRAFT"
    assert re.fullmatch(r"PO-\d{8}-\d{4,}", po["po_no"])
    po_id = po["id"]
    po = _ok(client, H["ww"], "POST", f"/api/v1/purchase-orders/{po_id}/confirm",
             json={"version": po["version"]})
    assert po["status"] == "CONFIRMED"
    po_item = po["items"][0]

    # -- Scenario 15b: 越权入库 —— APPLICANT 无 receipt:create
    r = client.post("/api/v1/purchase-receipts", headers=H["zh"], json={
        "po_id": po_id, "warehouse_id": wh["id"],
        "items": [{"po_item_id": po_item["id"], "received_quantity": "10"}],
    })
    assert r.status_code == 403 and r.json()["code"] == 2005

    # -- Scenario 9: partial receipt 40 -> PARTIALLY_RECEIVED (balance/ledger/amount)
    rcv1 = _ok(client, H["zl"], "POST", "/api/v1/purchase-receipts", json={
        "po_id": po_id, "warehouse_id": wh["id"],
        "items": [{"po_item_id": po_item["id"], "received_quantity": "40"}],
    })
    assert re.fullmatch(r"RCV-\d{8}-\d{4,}", rcv1["receipt_no"])
    po = _ok(client, H["ww"], "GET", f"/api/v1/purchase-orders/{po_id}")
    assert po["status"] == "PARTIALLY_RECEIVED"
    db.rollback()
    bal = db.execute(select(InventoryBalance).where(
        InventoryBalance.warehouse_id == wh["id"],
        InventoryBalance.material_id == mat["id"],
    )).scalar_one()
    assert float(bal.quantity) == 40.0
    assert str(bal.total_amount) == "400.00"

    # -- Scenario 13: over-receive blocked (remaining 60, ask 70 -> 6002)
    r = client.post("/api/v1/purchase-receipts", headers=H["zl"], json={
        "po_id": po_id, "warehouse_id": wh["id"],
        "items": [{"po_item_id": po_item["id"], "received_quantity": "70"}],
    })
    assert r.status_code == 409 and r.json()["code"] == 6002

    # -- Scenario 8 + 10: full receipt 60 -> RECEIVED
    rcv2 = _ok(client, H["zl"], "POST", "/api/v1/purchase-receipts", json={
        "po_id": po_id, "warehouse_id": wh["id"],
        "items": [{"po_item_id": po_item["id"], "received_quantity": "60"}],
    })
    po = _ok(client, H["ww"], "GET", f"/api/v1/purchase-orders/{po_id}")
    assert po["status"] == "RECEIVED"

    # -- Scenario 12a: receipt on RECEIVED PO blocked (5009)
    r = client.post("/api/v1/purchase-receipts", headers=H["zl"], json={
        "po_id": po_id, "warehouse_id": wh["id"],
        "items": [{"po_item_id": po_item["id"], "received_quantity": "1"}],
    })
    assert r.status_code == 409 and r.json()["code"] == 5009

    # -- Scenario 12b: fully-converted (CONVERTED) PR cannot be cancelled (4002)
    r = client.post(f"/api/v1/purchase-requisitions/{pr_id}/cancel", headers=H["zh"])
    assert r.status_code == 409 and r.json()["code"] == 4002

    # -- Scenario 12c: resubmit an APPROVED PR blocked (invalid transition)
    r = client.post(f"/api/v1/purchase-requisitions/{pr_id}/submit", headers=H["zh"])
    assert r.status_code == 409

    # -- Reversal: undo receipt #2 (60) -> PARTIALLY_RECEIVED, then double-reverse blocked
    _ok(client, H["zl"], "POST", f"/api/v1/purchase-receipts/{rcv2['id']}/reverse",
        json={"reason": "P12 E2E 仓库多收冲销"})
    po = _ok(client, H["ww"], "GET", f"/api/v1/purchase-orders/{po_id}")
    assert po["status"] == "PARTIALLY_RECEIVED"
    r = client.post(f"/api/v1/purchase-receipts/{rcv2['id']}/reverse",
                    headers=H["zl"], json={"reason": "P12 E2E 重复冲销"})
    assert r.status_code == 409 and r.json()["code"] in (6005, 6006)

    # -- Scenario 11: reconcile ledger SUM == balance for (warehouse, material)
    db.rollback()
    bal = db.execute(select(InventoryBalance).where(
        InventoryBalance.warehouse_id == wh["id"],
        InventoryBalance.material_id == mat["id"],
    )).scalar_one()
    assert float(bal.quantity) == 40.0
    assert str(bal.total_amount) == "400.00"
    qty_sum, amt_sum = db.execute(
        select(func.coalesce(func.sum(InventoryTransaction.quantity), 0),
               func.coalesce(func.sum(InventoryTransaction.amount), 0))
        .where(InventoryTransaction.warehouse_id == wh["id"],
               InventoryTransaction.material_id == mat["id"])
    ).one()
    assert float(qty_sum) == float(bal.quantity)          # +40 +60 -60 == 40
    assert str(amt_sum) == str(bal.total_amount)          # 400.00 + 600.00 - 600.00
    n_txn = db.execute(
        select(func.count()).select_from(InventoryTransaction)
    ).scalar_one()
    assert n_txn == 3                                     # +40 / +60 / -60
