"""Phase 11 Dashboard tests.

Fixture strategy: one module-scoped business chain is built through the
real HTTP API (the same shape as ``seed_demo_data``); read-only tests then
assert KPI semantics against that chain. Tests that must mutate data (e.g.
a reversal scenario) build their own small chain instead, so the shared
fixture stays stable.

Contract under test (docs/dashboard_metrics.md):

* summary/pending_pr:   status=PENDING within PR visible scope
* summary/pending_purchase: APPROVED PR that still has an item with
  converted_quantity < requested_quantity (distinct PR)
* summary/draft_po:     DRAFT PO the caller may confirm (BUYER own / ADMIN all)
* summary/pending_po:   CONFIRMED|PARTIALLY_RECEIVED within PO visible scope
* low stock:            policy row exists AND quantity < safety_stock
                        (no policy / quantity == safety are NOT low)
* inventory_total_amount: SUM(inventory_balances.total_amount) — Decimal
* trend:                apply_date, CANCELLED excluded, 7/30/90
* po-status:            all statuses returned incl. count=0
* recent activities:    key business actions only (no LOGIN/master CRUD)
"""

from __future__ import annotations

from decimal import Decimal
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.utils.enums import AuditAction, PoStatus
from cleanup_helper import wipe_business_data

_BUSINESS_ACTIONS = {
    AuditAction.PR_CREATE,
    AuditAction.PR_SUBMIT,
    AuditAction.PR_APPROVE,
    AuditAction.PR_REJECT,
    AuditAction.PR_REVISE,
    AuditAction.PR_CANCEL,
    AuditAction.PO_CREATE,
    AuditAction.PO_CONFIRM,
    AuditAction.PO_CANCEL,
    AuditAction.RECEIPT_POST,
    AuditAction.RECEIPT_REVERSE,
}


# ----------------------------------------------------------------------
# helpers (same conventions as the Phase 9 chain tests)
# ----------------------------------------------------------------------
def _login(client: TestClient, username: str, password: str = "demo123") -> str:
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["data"]["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _get(client: TestClient, path: str, headers: dict) -> dict:
    r = client.get(path, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == 0, body
    return body["data"]


def _mk_material(client: TestClient, h: dict, name: str, unit: str = "pcs") -> int:
    data = _get(client, "/api/v1/materials", h)  # noqa: F841 - ensure endpoint shape
    return 0


# ---- chain builders ----
def _create_material(client: TestClient, headers: dict, name: str, unit: str) -> int:
    r = client.post("/api/v1/materials", headers=headers,
                    json={"material_name": name, "unit": unit})
    assert r.status_code == 200, r.text
    return r.json()["data"]["id"]


def _create_supplier(client: TestClient, headers: dict, name: str) -> int:
    r = client.post("/api/v1/suppliers", headers=headers, json={"supplier_name": name})
    assert r.status_code == 200, r.text
    return r.json()["data"]["id"]


def _create_warehouse(client: TestClient, headers: dict, name: str) -> int:
    r = client.post("/api/v1/warehouses", headers=headers, json={"warehouse_name": name})
    assert r.status_code == 200, r.text
    return r.json()["data"]["id"]


def _set_policy(client: TestClient, headers: dict, wh_id: int, mat_id: int, safety: str) -> None:
    r = client.post("/api/v1/inventory-policies", headers=headers,
                    json={"warehouse_id": wh_id, "material_id": mat_id,
                          "safety_stock": safety})
    assert r.status_code == 200, r.text


def _mk_pr(client: TestClient, headers: dict, material_id: int,
           qty: str, price: str) -> dict:
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


def _cancel_pr(client: TestClient, headers: dict, pr_id: int) -> dict:
    r = client.post(f"/api/v1/purchase-requisitions/{pr_id}/cancel", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _approved_pr(client: TestClient, applicant_h: dict, manager_h: dict,
                 material_id: int, qty: str, price: str) -> dict:
    pr = _mk_pr(client, applicant_h, material_id, qty, price)
    submitted = _submit(client, applicant_h, pr["id"])
    return _approve(client, manager_h, pr["id"], version=submitted["version"])


def _mk_po(client: TestClient, buyer_h: dict, supplier_id: int, pr: dict,
           ordered_qty: str, source_qty: str, price: str) -> dict:
    """Convert (possibly partially) one approved PR into a PO."""
    r = client.get(f"/api/v1/purchase-requisitions/{pr['id']}", headers=buyer_h)
    assert r.status_code == 200, r.text
    line = next(x for x in r.json()["data"]["items"])
    r = client.post("/api/v1/purchase-orders", headers=buyer_h, json={
        "supplier_id": supplier_id,
        "items": [{
            "material_id": line["material_id"],
            "ordered_quantity": ordered_qty,
            "unit_price": price,
            "sources": [{"pr_item_id": line["id"], "quantity": source_qty}],
        }],
    })
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _confirm_po(client: TestClient, headers: dict, po_id: int, version: int) -> dict:
    r = client.post(f"/api/v1/purchase-orders/{po_id}/confirm", headers=headers,
                    json={"version": version})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _po_detail(client: TestClient, headers: dict, po_id: int) -> dict:
    r = client.get(f"/api/v1/purchase-orders/{po_id}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _receive(client: TestClient, wh_h: dict, po_id: int, warehouse_id: int,
             po_item_id: int, qty: str) -> dict:
    r = client.post("/api/v1/purchase-receipts", headers=wh_h, json={
        "po_id": po_id, "warehouse_id": warehouse_id,
        "items": [{"po_item_id": po_item_id, "received_quantity": qty}],
    })
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _roles(client: TestClient) -> dict[str, dict]:
    """Authenticated headers per demo user."""
    return {
        "admin": _auth(_login(client, "admin", "admin123")),
        "zhangsan": _auth(_login(client, "zhangsan")),
        "lisi": _auth(_login(client, "lisi")),
        "wangwu": _auth(_login(client, "wangwu")),
        "zhaoliu": _auth(_login(client, "zhaoliu")),
    }


# ----------------------------------------------------------------------
# module-scoped demo chain (mirrors seed_demo_data shape)
# ----------------------------------------------------------------------
@pytest.fixture(scope="module")
def chain(client: TestClient) -> dict:
    """One deterministic business chain used by the read-only KPI tests."""
    wipe_business_data()
    r = _roles(client)
    admin, zh, li, ww, zl = r["admin"], r["zhangsan"], r["lisi"], r["wangwu"], r["zhaoliu"]

    # master data
    m_a = _create_material(client, admin, "ESP32 模组", "pcs")
    m_b = _create_material(client, admin, "STM32 芯片", "pcs")
    m_c = _create_material(client, admin, "微型轴承", "套")
    m_d = _create_material(client, admin, "连接线材", "米")
    sup = _create_supplier(client, admin, "演示供应商")
    w1 = _create_warehouse(client, admin, "原材料仓")
    w2 = _create_warehouse(client, admin, "成品仓")
    _set_policy(client, ww, w1, m_a, "50")
    _set_policy(client, ww, w1, m_c, "15")

    # PR1 -> PO1 (A 100) receive 40 @W1 + 60 @W2  => PO1 RECEIVED
    pr1 = _approved_pr(client, zh, li, m_a, "100", "10")
    po1 = _mk_po(client, ww, sup, pr1, "100", "100", "10")
    po1 = _confirm_po(client, ww, po1["id"], po1["version"])
    poi1 = po1["items"][0]["id"]
    _receive(client, zl, po1["id"], w1, poi1, "40")
    _receive(client, zl, po1["id"], w2, poi1, "60")

    # PR2 (B 20) PENDING (zhangsan own) & PR6 (B 10) PENDING (lisi own)
    pr2 = _mk_pr(client, zh, m_b, "20", "5")
    _submit(client, zh, pr2["id"])
    pr6 = _mk_pr(client, li, m_b, "10", "5")
    _submit(client, li, pr6["id"])

    # PR3 (C 10) APPROVED, untouched -> pending purchase
    pr3 = _approved_pr(client, zh, li, m_c, "10", "3")

    # PR4 -> PO2 (D 200) confirm, receive 80 @W2  => PO2 PARTIALLY_RECEIVED
    pr4 = _approved_pr(client, zh, li, m_d, "200", "2")
    po2 = _mk_po(client, ww, sup, pr4, "200", "200", "2")
    po2 = _confirm_po(client, ww, po2["id"], po2["version"])
    _receive(client, zl, po2["id"], w2, po2["items"][0]["id"], "80")

    # PR5 (A 30) approved, PO3 converts only 10 & stays DRAFT -> both
    # "pending purchase" (remaining 20) and "draft PO" exist
    pr5 = _approved_pr(client, zh, li, m_a, "30", "10")
    po3 = _mk_po(client, ww, sup, pr5, "10", "10", "10")
    assert po3["status"] == "DRAFT"

    # PR9 -> PO4 (C 10) confirm; receive 6 then 4 @W1 => C@W1=10 < 15 low
    pr9 = _approved_pr(client, zh, li, m_c, "10", "3")
    po4 = _mk_po(client, ww, sup, pr9, "10", "10", "3")
    po4 = _confirm_po(client, ww, po4["id"], po4["version"])
    _receive(client, zl, po4["id"], w1, po4["items"][0]["id"], "6")
    _receive(client, zl, po4["id"], w1, po4["items"][0]["id"], "4")

    # PR7 CANCELLED (zhangsan DRAFT -> cancel) must never enter the trend
    pr7 = _mk_pr(client, zh, m_a, "5", "10")
    _cancel_pr(client, zh, pr7["id"])

    return {
        "headers": r, "m_a": m_a, "m_b": m_b, "m_c": m_c, "m_d": m_d,
        "w1": w1, "w2": w2,
        "pr2": pr2, "pr6": pr6, "pr3": pr3, "pr5": pr5, "po3": po3,
        "po1": po1, "po2": po2, "po4": po4,
    }


def _summary(client: TestClient, headers: dict) -> dict:
    return _get(client, "/api/v1/dashboard/summary", headers)


# ======================================================================
# Summary: global / full-scope roles (ADMIN, BUYER, WAREHOUSE)
# ======================================================================
def test_summary_admin_global(client: TestClient, chain: dict) -> None:
    s = _summary(client, chain["headers"]["admin"])
    assert s["pending_pr_count"] == 2          # PR2 + PR6
    assert s["pending_purchase_count"] == 2    # PR3 + PR5 (remaining)
    assert s["draft_po_count"] == 1            # PO3 (admin may confirm all)
    assert s["pending_po_count"] == 1          # PO2 partial (PO1/PO4 received)
    assert s["low_stock_count"] == 2           # A@W1 40<50, C@W1 10<15
    assert s["inventory_total_amount"] == "1190.00"


def test_summary_buyer_scope(client: TestClient, chain: dict) -> None:
    s = _summary(client, chain["headers"]["wangwu"])
    assert s["pending_pr_count"] == 2
    assert s["pending_purchase_count"] == 2
    assert s["draft_po_count"] == 1            # PO3 own
    assert s["pending_po_count"] == 1
    assert s["low_stock_count"] == 2
    assert s["inventory_total_amount"] == "1190.00"


def test_summary_warehouse_scope(client: TestClient, chain: dict) -> None:
    """WAREHOUSE has no pr:view (matches PR-list page scope): PR KPIs must be 0
    (frontend hides those cards), while receiving-facing KPIs are live."""
    s = _summary(client, chain["headers"]["zhaoliu"])
    assert s["pending_pr_count"] == 0          # no pr:view -> card hidden
    assert s["pending_purchase_count"] == 0    # requires pr:view too
    assert s["pending_po_count"] == 1          # receiving focus
    assert s["low_stock_count"] == 2           # inventory:view (full scope)
    assert s["draft_po_count"] == 0            # no po:confirm


# ======================================================================
# Role isolation (APPLICANT / DEPT_MANAGER)
# ======================================================================
def test_summary_applicant_sees_own_only(client: TestClient, chain: dict) -> None:
    """APPLICANT must not see other applicants' PENDING PRs (scope rule)."""
    s = _summary(client, chain["headers"]["zhangsan"])
    assert s["pending_pr_count"] == 1          # PR2 own; PR6 (lisi) hidden
    assert s["pending_po_count"] == 1          # own PR chain POs (PO2)
    assert s["pending_purchase_count"] == 2    # own PRs PR3/PR5
    assert s["draft_po_count"] == 0            # no po:confirm


def test_summary_dept_manager_scope(client: TestClient, chain: dict) -> None:
    """DEPT_MANAGER sees own + managed dept PRs (both lisi PR6 and RD PR2)."""
    s = _summary(client, chain["headers"]["lisi"])
    assert s["pending_pr_count"] == 2          # PR2 (RD) + PR6 (own)
    assert s["pending_po_count"] == 1          # RD-chain POs
    assert s["draft_po_count"] == 0


# ======================================================================
# PR trend
# ======================================================================
def _days_trend(client: TestClient, headers: dict, days: int) -> list[dict]:
    return _get(client, f"/api/v1/dashboard/pr-trend?days={days}", headers)


def test_pr_trend_7_30_90_days(client: TestClient, chain: dict) -> None:
    h = chain["headers"]["admin"]
    for days in (7, 30, 90):
        pts = _days_trend(client, h, days)
        assert len(pts) == days
        assert all(p["count"] >= 0 for p in pts)


def test_pr_trend_today_counts_and_amount(client: TestClient, chain: dict) -> None:
    h = chain["headers"]["admin"]
    pts = _days_trend(client, h, 30)
    today = date.today().isoformat()
    today_pt = next(p for p in pts if p["date"] == today)
    # active PRs created today: PR1..PR6 + PR9 (7); CANCELLED PR7 excluded
    assert today_pt["count"] == 7
    # amounts: 1000 + 100 + 30 + 400 + 300 + 50 + 30
    assert today_pt["amount"] == "1910.00"


def test_pr_trend_excludes_cancelled(client: TestClient, chain: dict) -> None:
    """CANCELLED PR7 must never show up in any bucket."""
    h = chain["headers"]["admin"]
    pts = _days_trend(client, h, 7)
    today_pt = next(p for p in pts if p["date"] == date.today().isoformat())
    assert today_pt["count"] == 7              # PR7 excluded


def test_pr_trend_applicant_scope(client: TestClient, chain: dict) -> None:
    """APPLICANT trend only covers own PRs (PR6 by lisi invisible)."""
    h = chain["headers"]["zhangsan"]
    pts = _days_trend(client, h, 30)
    today_pt = next(p for p in pts if p["date"] == date.today().isoformat())
    assert today_pt["count"] == 6              # own PR1..PR5 + PR9 (PR7 cancelled)


# ======================================================================
# PO status distribution
# ======================================================================
def test_po_status_distribution_all_states_with_zero(client: TestClient, chain: dict) -> None:
    dist = _get(client, "/api/v1/dashboard/po-status-distribution",
                chain["headers"]["admin"])
    statuses = {d["status"]: d["count"] for d in dist}
    # every defined status must be present, even with count 0
    assert set(statuses) == {s.value for s in PoStatus}
    assert statuses["DRAFT"] == 1               # PO3
    assert statuses["CONFIRMED"] == 0
    assert statuses["PARTIALLY_RECEIVED"] == 1  # PO2
    assert statuses["RECEIVED"] == 2            # PO1, PO4
    assert statuses["CANCELLED"] == 0


def test_po_status_distribution_applicant_scope(client: TestClient, chain: dict) -> None:
    """APPLICANT only sees POs whose PR is in their chain."""
    dist = _get(client, "/api/v1/dashboard/po-status-distribution",
                chain["headers"]["zhangsan"])
    statuses = {d["status"]: d["count"] for d in dist}
    assert set(statuses) == {s.value for s in PoStatus}
    assert statuses["DRAFT"] == 1               # PO3 from own PR5
    assert statuses["RECEIVED"] == 2            # PO1 + PO4
    assert statuses["PARTIALLY_RECEIVED"] == 1  # PO2


# ======================================================================
# Low stock
# ======================================================================
def test_low_stock_semantics(client: TestClient, chain: dict) -> None:
    rows = _get(client, "/api/v1/dashboard/low-stock?limit=10",
                chain["headers"]["admin"])
    by_mat = {(r["warehouse_id"], r["material_id"]): r for r in rows}
    # A@W1: qty 40 < safety 50 -> in list, shortage 10
    r = by_mat[(chain["w1"], chain["m_a"])]
    assert r["shortage_quantity"] == "10.0000"
    assert r["quantity"] == "40.0000"
    assert r["safety_stock"] == "50.0000"
    # C@W1: qty 10 < 15 -> in list, shortage 5
    assert (chain["w1"], chain["m_c"]) in by_mat
    # A@W2 (60, no policy) / D@W2 (80, no policy) / B (no balance) NOT low
    assert (chain["w2"], chain["m_a"]) not in by_mat
    assert (chain["w2"], chain["m_d"]) not in by_mat
    assert (chain["w1"], chain["m_b"]) not in by_mat


def test_low_stock_sorted_by_shortage_desc(client: TestClient, chain: dict) -> None:
    rows = _get(client, "/api/v1/dashboard/low-stock", chain["headers"]["admin"])
    shortages = [Decimal(r["shortage_quantity"]) for r in rows]
    assert shortages == sorted(shortages, reverse=True)
    assert len(rows) == 2                       # A@W1 (10) then C@W1 (5)
    assert rows[0]["material_id"] == chain["m_a"]


def test_low_stock_count_matches_list(client: TestClient, chain: dict) -> None:
    """KPI count must equal the top-list semantics (口径一致性)."""
    s = _summary(client, chain["headers"]["admin"])
    rows = _get(client, "/api/v1/dashboard/low-stock?limit=50",
                chain["headers"]["admin"])
    assert s["low_stock_count"] == len(rows) == 2


# ======================================================================
# Todos
# ======================================================================
def test_todos_buyer(client: TestClient, chain: dict) -> None:
    todos = _get(client, "/api/v1/dashboard/todos", chain["headers"]["wangwu"])
    by_type = {t["type"]: t["count"] for t in todos}
    assert by_type["PR_TO_PO"] == 2
    assert by_type["PO_CONFIRM"] == 1
    assert by_type["PO_RECEIVE"] == 1
    assert "PR_APPROVAL" not in by_type        # BUYER cannot approve


def test_todos_admin(client: TestClient, chain: dict) -> None:
    todos = _get(client, "/api/v1/dashboard/todos", chain["headers"]["admin"])
    by_type = {t["type"]: t["count"] for t in todos}
    assert by_type["PR_APPROVAL"] == 2
    assert by_type["PR_TO_PO"] == 2
    assert by_type["PO_CONFIRM"] == 1
    assert by_type["PO_RECEIVE"] == 1


def test_todos_warehouse_receiving_focus(client: TestClient, chain: dict) -> None:
    todos = _get(client, "/api/v1/dashboard/todos", chain["headers"]["zhaoliu"])
    types = {t["type"] for t in todos}
    assert types == {"PO_RECEIVE"}              # receiving focus only


def test_todos_applicant_empty(client: TestClient, chain: dict) -> None:
    todos = _get(client, "/api/v1/dashboard/todos", chain["headers"]["zhangsan"])
    assert todos == []                          # no actionable todo for APPLICANT


# ======================================================================
# Recent activities / inventory activities
# ======================================================================
def test_recent_activities_key_actions_only(client: TestClient, chain: dict) -> None:
    acts = _get(client, "/api/v1/dashboard/recent-activities",
                chain["headers"]["admin"])
    assert 0 < len(acts) <= 10
    for a in acts:
        assert a["action"] in {x.value for x in _BUSINESS_ACTIONS}, a
        assert a["action"] not in {"LOGIN", "LOGIN_FAILED"}
    # PR / PO / RCV document numbers are rendered in the timeline
    assert any(a["document_no"] for a in acts)


def test_inventory_activities_signed_quantity(client: TestClient, chain: dict) -> None:
    acts = _get(client, "/api/v1/dashboard/inventory-activities",
                chain["headers"]["admin"])
    assert len(acts) == 5
    qty_sign = {Decimal(a["quantity"]) for a in acts}
    assert any(q > 0 for q in qty_sign)         # inbound rows present
    assert all("material_name" in a and "warehouse_name" in a for a in acts)


# ======================================================================
# Permission gating
# ======================================================================
def test_dashboard_requires_permission(client: TestClient, chain: dict) -> None:
    """A role without dashboard:view must get the envelope 2005 / 403.

    Role codes are a closed enum (RoleCreate.role_code: RoleCode), so the
    only API-legal way to build a no-dashboard:view principal is to strip the
    permission from an existing role (replace-style assignment) and restore
    it afterwards — zhaoliu (WAREHOUSE) is used as the probe principal.
    """
    admin = chain["headers"]["admin"]
    roles = _get(client, "/api/v1/roles", admin)
    wh_role = next(r for r in roles if r["role_code"] == "WAREHOUSE")
    original = wh_role["permission_ids"]
    try:
        r = client.post(f"/api/v1/roles/{wh_role['id']}/permissions",
                        headers=admin, json={"permission_ids": []})
        assert r.status_code == 200, r.text
        # permissions are re-read from the DB on every request -> existing
        # zhaoliu token is enough; the dashboard gate must reject the call.
        r = client.get("/api/v1/dashboard/summary",
                       headers=chain["headers"]["zhaoliu"])
        assert r.status_code == 403, r.text
        assert r.json()["code"] == 2005
    finally:
        client.post(f"/api/v1/roles/{wh_role['id']}/permissions",
                    headers=admin, json={"permission_ids": original})
        wipe_business_data()
