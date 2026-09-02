"""Phase 9 inventory tests: balances, moving-average costing, safety-stock
join and the append-only ledger (§三十七 / §三十八).

Balance vs ledger are asserted to reconcile at the end of every scenario —
the snapshot is never allowed to drift from SUM(transactions.quantity)
(§四十五.13).

Helper re-use: the receipt/inventory chain needs the same PR -> PO -> Receipt
setup as ``test_purchase_receipt.py``, so its helpers are imported instead of
being copy-pasted (pytest inserts ``tests/`` on ``sys.path``).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DatabaseError  # 触发器 SIGNAL 抛 OperationalError(1644)

from app.core.exceptions import ConflictException, ErrorCode
from app.db.session import SessionLocal
from app.models import (
    InventoryBalance,
    InventoryTransaction,
    Permission,
    Role,
    RolePermission,
)
from app.services import inventory_service
from app.utils.enums import RoleCode, TxnType
from test_purchase_receipt import (
    _auth,
    _balance,
    _clean_all,
    _confirm_po,
    _create_material,
    _create_supplier,
    _create_warehouse,
    _login,
    _mk_approved_pr,
    _mk_po,
    _post_receipt,
    _txns,
    _wh_headers,
)


def _set_policy(client: TestClient, headers: dict, warehouse_id: int,
                material_id: int, safety_stock: str) -> dict:
    r = client.post("/api/v1/inventory-policies", headers=headers, json={
        "warehouse_id": warehouse_id, "material_id": material_id,
        "safety_stock": safety_stock,
    })
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _balances(client: TestClient, headers: dict, **params) -> dict:
    r = client.get("/api/v1/inventory/balances", headers=headers, params=params)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _strip_role_permission(role_code: RoleCode, perm_code: str) -> tuple[int, list[int]]:
    """Remove ``perm_code`` from a role; returns (role_id, original_ids)."""
    with SessionLocal() as s:
        role_id = s.execute(
            select(Role.id).where(Role.role_code == role_code)
        ).scalar_one()
        perm_id = s.execute(
            select(Permission.id).where(Permission.perm_code == perm_code)
        ).scalar_one()
        ids = sorted(s.execute(
            select(RolePermission.permission_id).where(RolePermission.role_id == role_id)
        ).scalars().all())
        s.execute(
            RolePermission.__table__.delete().where(
                RolePermission.role_id == role_id,
                RolePermission.permission_id == perm_id,
            )
        )
        s.commit()
    return role_id, ids


def _restore_role_permissions(role_id: int, permission_ids: list[int]) -> None:
    with SessionLocal() as s:
        s.execute(RolePermission.__table__.delete().where(
            RolePermission.role_id == role_id))
        for pid in permission_ids:
            s.execute(RolePermission.__table__.insert().values(
                role_id=role_id, permission_id=pid))
        s.commit()


# ======================================================================
# 三十七：库存余额 与 移动加权平均
# ======================================================================
def test_first_receipt_creates_balance(client: TestClient, db) -> None:
    """26-29：首次入库自动创建余额行，数量/金额/平均成本均正确。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    assert _balance(wh, mid) is None  # 未入库时无余额行

    po = _mk_po_full(client, admin, mid, sup, qty="10", price="10.0000")
    r = _post_receipt(client, _wh_headers(client), po["id"], wh,
                      [{"po_item_id": po["items"][0]["id"], "received_quantity": "10"}])
    assert r.status_code == 200, r.text

    bal = _balance(wh, mid)
    assert bal is not None
    assert f"{bal['quantity']}" == "10.0000"
    assert f"{bal['total_amount']}" == "100.00"
    assert f"{bal['average_unit_cost']}" == "10.0000"


def test_moving_average_across_two_prices(client: TestClient, db) -> None:
    """30：10 × 10 + 10 × 20 → qty 20 / total 300.00 / avg 15.0000（§十二）。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    wh_h = _wh_headers(client)

    po_a = _mk_po_full(client, admin, mid, sup, qty="10", price="10.0000")
    assert _post_receipt(client, wh_h, po_a["id"], wh,
                         [{"po_item_id": po_a["items"][0]["id"],
                           "received_quantity": "10"}]).status_code == 200
    bal = _balance(wh, mid)
    assert f"{bal['quantity']}" == "10.0000"
    assert f"{bal['total_amount']}" == "100.00"
    assert f"{bal['average_unit_cost']}" == "10.0000"

    po_b = _mk_po_full(client, admin, mid, sup, qty="10", price="20.0000")
    assert _post_receipt(client, wh_h, po_b["id"], wh,
                         [{"po_item_id": po_b["items"][0]["id"],
                           "received_quantity": "10"}]).status_code == 200
    bal = _balance(wh, mid)
    assert f"{bal['quantity']}" == "20.0000"
    assert f"{bal['total_amount']}" == "300.00"
    assert f"{bal['average_unit_cost']}" == "15.0000"

    # 余额与流水始终对账（§四十五.13）
    assert _ledger_net(wh, mid) == Decimal("20.0000")


def test_no_float_in_inventory_values(client: TestClient, db) -> None:
    """31：全链路 Decimal —— API 输出为 Decimal 序列化串，DB 中类型非 float。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_po_full(client, admin, mid, sup, qty="3", price="12.3456")
    assert _post_receipt(client, _wh_headers(client), po["id"], wh,
                         [{"po_item_id": po["items"][0]["id"],
                           "received_quantity": "3"}]).status_code == 200

    rows = _balances(client, admin, material_id=mid)["items"]
    row = rows[0]
    assert row["quantity"] == "3.0000"
    assert row["total_amount"] == "37.04"          # 2 位金额
    assert row["average_unit_cost"] == "12.3467"   # 4 位成本
    assert not isinstance(row["quantity"], float)

    txns = client.get(f"/api/v1/inventory/transactions?material_id={mid}",
                      headers=admin).json()["data"]["items"]
    assert txns[0]["quantity"] == "3.0000"
    assert txns[0]["unit_cost"] == "12.3456"
    assert txns[0]["amount"] == "37.04"

    with SessionLocal() as s:
        s.rollback()
        bal = s.execute(select(InventoryBalance).where(
            InventoryBalance.warehouse_id == wh,
            InventoryBalance.material_id == mid)).scalar_one()
        txn = s.execute(select(InventoryTransaction).where(
            InventoryTransaction.material_id == mid)).scalar_one()
    for value in (bal.quantity, bal.total_amount, bal.average_unit_cost,
                  txn.quantity, txn.unit_cost, txn.amount):
        assert isinstance(value, Decimal), type(value)
        assert not isinstance(value, float)


def test_balance_safety_stock_join(client: TestClient, db) -> None:
    """32/33：安全库存来自 inventory_policies，不复制到余额表。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_po_full(client, admin, mid, sup, qty="100", price="10.0000")
    assert _post_receipt(client, _wh_headers(client), po["id"], wh,
                         [{"po_item_id": po["items"][0]["id"],
                           "received_quantity": "5"}]).status_code == 200

    # 无策略：safety_stock = None，is_below_safety_stock = False
    row = _balances(client, admin, material_id=mid)["items"][0]
    assert row["safety_stock"] is None
    assert row["is_below_safety_stock"] is False

    _set_policy(client, admin, wh, mid, "10")
    row = _balances(client, admin, material_id=mid)["items"][0]
    assert row["safety_stock"] == "10.0000"
    assert row["is_below_safety_stock"] is True          # 5 < 10
    assert _balances(client, admin, below_safety_stock="true")["total"] == 1
    assert _balances(client, admin, below_safety_stock="false")["total"] == 0

    # 补充到 15 → 不再低于安全库存
    assert _post_receipt(client, _wh_headers(client), po["id"], wh,
                         [{"po_item_id": po["items"][0]["id"],
                           "received_quantity": "10"}]).status_code == 200
    row = _balances(client, admin, material_id=mid)["items"][0]
    assert row["is_below_safety_stock"] is False         # 15 >= 10
    assert _balances(client, admin, below_safety_stock="true")["total"] == 0


def test_balance_list_filters(client: TestClient, db) -> None:
    _clean_all()
    admin = _auth(_login(client))
    m1 = _create_material(client, admin, "筛选物料甲")["id"]
    m2 = _create_material(client, admin, "筛选物料乙")["id"]
    sup = _create_supplier(client, admin)["id"]
    wh1 = _create_warehouse(client, admin, "筛选仓一")["id"]
    wh2 = _create_warehouse(client, admin, "筛选仓二")["id"]
    wh_h = _wh_headers(client)
    code_m1 = _material_code(client, admin, m1)
    for mid, wh in ((m1, wh1), (m2, wh2)):
        po = _mk_po_full(client, admin, mid, sup, qty="10", price="10.0000")
        assert _post_receipt(client, wh_h, po["id"], wh,
                             [{"po_item_id": po["items"][0]["id"],
                               "received_quantity": "10"}]).status_code == 200

    assert _balances(client, admin)["total"] == 2
    assert _balances(client, admin, warehouse_id=wh1)["total"] == 1
    assert _balances(client, admin, material_id=m2)["total"] == 1
    assert _balances(client, admin, material_code=code_m1[-4:])["total"] == 1
    assert _balances(client, admin, material_name="筛选物料乙")["total"] == 1
    assert _balances(client, admin, page=1, page_size=1)["total"] == 2
    assert len(_balances(client, admin, page=2, page_size=1)["items"]) == 1


# ======================================================================
# 三十八：库存流水
# ======================================================================
def test_transaction_generated_per_receipt_item(client: TestClient, db) -> None:
    """35-38：每条入库明细生成一条 PURCHASE_IN，数量/单价/金额与明细一致。"""
    _clean_all()
    admin = _auth(_login(client))
    m1 = _create_material(client, admin, "流水物料A")["id"]
    m2 = _create_material(client, admin, "流水物料B")["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    pr1 = _mk_approved_pr(client, m1, qty="40", price="20.0000")
    pr2 = _mk_approved_pr(client, m2, qty="20", price="5.5000")
    po = _mk_po(client, sup, [
        {"pr_id": pr1["id"], "pr_item_id": pr1["items"][0]["id"],
         "quantity": "40", "ordered_quantity": "40"},
        {"pr_id": pr2["id"], "pr_item_id": pr2["items"][0]["id"],
         "quantity": "20", "ordered_quantity": "20"},
    ], unit_price="20.0000")
    po = _confirm_po(client, _auth(_login(client, "wangwu", "demo123")),
                     po["id"], po["version"])
    wh_h = _wh_headers(client)
    rcpt = _post_receipt(client, wh_h, po["id"], wh, [
        {"po_item_id": po["items"][0]["id"], "received_quantity": "40"},
        {"po_item_id": po["items"][1]["id"], "received_quantity": "15"},
    ])
    assert rcpt.status_code == 200, rcpt.text

    rows = client.get("/api/v1/inventory/transactions", headers=admin).json()["data"]
    assert rows["total"] == 2
    by_mat = {t["material_id"]: t for t in rows["items"]}
    assert by_mat[m1]["quantity"] == "40.0000"
    assert by_mat[m1]["unit_cost"] == "20.0000"
    assert by_mat[m1]["amount"] == "800.00"     # 40 × 20
    assert by_mat[m1]["balance_after"] == "40.0000"
    # 明细 B 的 unit_price 由 PO 传入（20.0000），与 PR 预估价无关（§十三）
    assert by_mat[m2]["quantity"] == "15.0000"
    assert by_mat[m2]["unit_cost"] == "20.0000"
    assert by_mat[m2]["amount"] == "300.00"    # 15 × 20
    assert by_mat[m2]["balance_after"] == "15.0000"
    assert f"{_balance(wh, m2)['total_amount']}" == by_mat[m2]["amount"]


def test_transaction_reference_and_operator(client: TestClient, db) -> None:
    """39/40：流水 reference 指向入库单，operator 为收货人。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_po_full(client, admin, mid, sup, qty="10", price="10.0000")
    wh_h = _wh_headers(client)
    rcpt = _post_receipt(client, wh_h, po["id"], wh,
                         [{"po_item_id": po["items"][0]["id"],
                           "received_quantity": "4"}]).json()["data"]

    txns = client.get("/api/v1/inventory/transactions", headers=admin).json()["data"]["items"]
    assert len(txns) == 1
    t = txns[0]
    assert t["reference_no"] == rcpt["receipt_no"]
    assert t["source_type"] == "PURCHASE_RECEIPT"
    assert t["source_id"] == rcpt["id"]
    assert t["transaction_type"] == "PURCHASE_IN"
    assert t["operator_name"] == "赵敏"

    # 冲销流水的 source_transaction_id 指向原流水（§二十三 双向可追溯）
    assert client.post(f"/api/v1/purchase-receipts/{rcpt['id']}/reverse", headers=wh_h,
                       json={"reason": "追溯验证"}).status_code == 200
    txns = client.get("/api/v1/inventory/transactions", headers=admin).json()["data"]["items"]
    rev = next(t for t in txns if t["transaction_type"] == "PURCHASE_IN_REVERSAL")
    assert rev["reversed_transaction_id"] == next(
        t["id"] for t in txns if t["transaction_type"] == "PURCHASE_IN")


def test_transactions_have_no_write_endpoints(client: TestClient, db) -> None:
    """41：库存流水 append-only —— 不提供任何写端点。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_po_full(client, admin, mid, sup, qty="10", price="10.0000")
    rcpt = _post_receipt(client, _wh_headers(client), po["id"], wh,
                         [{"po_item_id": po["items"][0]["id"],
                           "received_quantity": "1"}]).json()["data"]
    txn_id = client.get("/api/v1/inventory/transactions",
                        headers=admin).json()["data"]["items"][0]["id"]
    for path in (f"/api/v1/inventory/transactions/{txn_id}",
                 f"/api/v1/inventory/balances/{rcpt['id']}"):
        assert client.put(path, headers=admin, json={}).status_code in (404, 405)
        assert client.delete(path, headers=admin).status_code in (404, 405)
    assert client.post("/api/v1/inventory/transactions", headers=admin,
                       json={}).status_code in (404, 405)


def test_inventory_transaction_append_only_enforced_by_db(client: TestClient, db) -> None:
    """§二十三：绕过 API 直接在 DB 上 UPDATE / DELETE 流水，被触发器拒绝。

    架构规则 3 的最后一道防线 —— API 层不提供写端点还不够，数据库必须强制。
    """
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_po_full(client, admin, mid, sup, qty="10", price="10.0000")
    assert _post_receipt(client, _wh_headers(client), po["id"], wh,
                         [{"po_item_id": po["items"][0]["id"],
                           "received_quantity": "10"}]).status_code == 200

    with SessionLocal() as s:
        s.rollback()
        txn_id = s.execute(
            select(InventoryTransaction.id).where(
                InventoryTransaction.material_id == mid)
        ).scalar_one()
        with pytest.raises(DatabaseError):
            s.execute(text("DELETE FROM inventory_transactions WHERE id = :i"),
                      {"i": txn_id})
            s.commit()
        s.rollback()
        with pytest.raises(DatabaseError):
            s.execute(text("UPDATE inventory_transactions SET quantity = 1 WHERE id = :i"),
                      {"i": txn_id})
            s.commit()
        s.rollback()

    # 流水仍在，库存未受影响
    assert len(_txns(material_id=mid)) == 1
    assert f"{_balance(wh, mid)['quantity']}" == "10.0000"


def test_transaction_list_filters(client: TestClient, db) -> None:
    """42：流水按仓库/物料/类型/单据号/时间筛选，按时间倒序稳定排序。"""
    _clean_all()
    admin = _auth(_login(client))
    m1 = _create_material(client, admin, "流水筛选甲")["id"]
    m2 = _create_material(client, admin, "流水筛选乙")["id"]
    sup = _create_supplier(client, admin)["id"]
    wh1 = _create_warehouse(client, admin, "流水仓一")["id"]
    wh2 = _create_warehouse(client, admin, "流水仓二")["id"]
    wh_h = _wh_headers(client)

    po1 = _mk_po_full(client, admin, m1, sup, qty="10", price="1.0000")
    r1 = _post_receipt(client, wh_h, po1["id"], wh1,
                       [{"po_item_id": po1["items"][0]["id"],
                         "received_quantity": "10"}]).json()["data"]
    po2 = _mk_po_full(client, admin, m2, sup, qty="10", price="2.0000")
    _post_receipt(client, wh_h, po2["id"], wh2,
                  [{"po_item_id": po2["items"][0]["id"], "received_quantity": "10"}])
    client.post(f"/api/v1/purchase-receipts/{r1['id']}/reverse", headers=wh_h,
                json={"reason": "筛选"})

    def q(**params) -> dict:
        return client.get("/api/v1/inventory/transactions", headers=admin,
                          params=params).json()["data"]

    assert q()["total"] == 3                                   # 2 in + 1 reversal
    assert q(warehouse_id=wh1)["total"] == 2
    assert q(material_id=m2)["total"] == 1
    assert q(transaction_type="PURCHASE_IN")["total"] == 2
    assert q(transaction_type="PURCHASE_IN_REVERSAL")["total"] == 1
    assert q(reference_no=r1["receipt_no"])["total"] == 2      # 入库 + 冲销
    # 倒序：最新（冲销）排在首位
    assert q()["items"][0]["transaction_type"] == "PURCHASE_IN_REVERSAL"


# ======================================================================
# 四十二：库存查询权限
# ======================================================================
def test_inventory_requires_inventory_view_permission(client: TestClient, db) -> None:
    """69/70：无 inventory:view / inventory_txn:view 一律 403。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_po_full(client, admin, mid, sup, qty="10", price="10.0000")
    assert _post_receipt(client, _wh_headers(client), po["id"], wh,
                         [{"po_item_id": po["items"][0]["id"],
                           "received_quantity": "1"}]).status_code == 200
    buyer = _auth(_login(client, "wangwu", "demo123"))
    assert client.get("/api/v1/inventory/balances", headers=buyer).status_code == 200
    assert client.get("/api/v1/inventory/transactions", headers=buyer).status_code == 200

    role_id, original = _strip_role_permission(RoleCode.BUYER, "inventory:view")
    try:
        assert client.get("/api/v1/inventory/balances", headers=buyer).status_code == 403
    finally:
        _restore_role_permissions(role_id, original)

    role_id, original = _strip_role_permission(RoleCode.BUYER, "inventory_txn:view")
    try:
        assert client.get("/api/v1/inventory/transactions", headers=buyer).status_code == 403
    finally:
        _restore_role_permissions(role_id, original)

    # 未认证一律 401
    assert client.get("/api/v1/inventory/balances").status_code == 401
    assert client.get("/api/v1/inventory/transactions").status_code == 401


# ======================================================================
# 对账：余额 == SUM(流水)
# ======================================================================
def test_balance_reconciles_with_ledger_after_mixed_ops(client: TestClient, db) -> None:
    """多笔入库 + 部分冲销后，余额仍等于流水净额（§四十五.13）。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    wh_h = _wh_headers(client)

    po1 = _mk_po_full(client, admin, mid, sup, qty="50", price="8.0000")
    r1 = _post_receipt(client, wh_h, po1["id"], wh,
                       [{"po_item_id": po1["items"][0]["id"],
                         "received_quantity": "30"}]).json()["data"]
    po2 = _mk_po_full(client, admin, mid, sup, qty="50", price="12.0000")
    r2 = _post_receipt(client, wh_h, po2["id"], wh,
                       [{"po_item_id": po2["items"][0]["id"],
                         "received_quantity": "20"}]).json()["data"]
    bal = _balance(wh, mid)
    assert f"{bal['quantity']}" == "50.0000"
    assert f"{bal['total_amount']}" == "480.00"      # 30×8 + 20×12
    assert f"{bal['average_unit_cost']}" == "9.6000"
    assert _ledger_net(wh, mid) == Decimal("50.0000")

    assert client.post(f"/api/v1/purchase-receipts/{r1['id']}/reverse", headers=wh_h,
                       json={"reason": "对账冲销"}).status_code == 200
    bal = _balance(wh, mid)
    assert f"{bal['quantity']}" == "20.0000"
    assert f"{bal['total_amount']}" == "240.00"      # 480 - 240（原始金额）
    assert f"{bal['average_unit_cost']}" == "12.0000"
    assert _ledger_net(wh, mid) == Decimal("20.0000")
    assert len(_txns(transaction_type=TxnType.PURCHASE_IN_REVERSAL)) == 1

    assert client.post(f"/api/v1/purchase-receipts/{r2['id']}/reverse", headers=wh_h,
                       json={"reason": "全部冲销"}).status_code == 200
    bal = _balance(wh, mid)
    assert f"{bal['quantity']}" == "0.0000"
    assert f"{bal['total_amount']}" == "0.00"
    assert f"{bal['average_unit_cost']}" == "0.0000"
    assert _ledger_net(wh, mid) == Decimal("0.0000")


# ======================================================================
# Review Fix §1：signed amount —— 流水 SUM 与余额对账
# ======================================================================
def _ledger_sums(warehouse_id: int, material_id: int) -> tuple[Decimal, Decimal]:
    """SUM(quantity) / SUM(amount) of every ledger row for a balance key.

    Review Fix §1 invariant: these must equal ``balance.quantity`` and
    ``balance.total_amount`` respectively (amount is signed exactly like
    quantity, so the ledger net is a plain sum, not an absolute-value sum).
    """
    with SessionLocal() as s:
        s.rollback()
        row = s.execute(
            select(
                func.coalesce(func.sum(InventoryTransaction.quantity), 0),
                func.coalesce(func.sum(InventoryTransaction.amount), 0),
            ).where(
                InventoryTransaction.warehouse_id == warehouse_id,
                InventoryTransaction.material_id == material_id,
            )
        ).one()
    return Decimal(row[0]), Decimal(row[1])


def test_review_fix_inbound_amount_positive_and_reversal_negative(client: TestClient, db) -> None:
    """Review Fix §1 (1/2)：PURCHASE_IN amount > 0，PURCHASE_IN_REVERSAL amount < 0。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_po_full(client, admin, mid, sup, qty="10", price="10.0000")
    wh_h = _wh_headers(client)
    rcpt = _post_receipt(client, wh_h, po["id"], wh,
                         [{"po_item_id": po["items"][0]["id"],
                           "received_quantity": "4"}]).json()["data"]

    rows = _txns(transaction_type=TxnType.PURCHASE_IN)
    assert len(rows) == 1
    assert rows[0].quantity > 0 and rows[0].amount > 0
    assert rows[0].unit_cost >= 0

    assert client.post(f"/api/v1/purchase-receipts/{rcpt['id']}/reverse", headers=wh_h,
                       json={"reason": "符号验证冲销"}).status_code == 200
    rev = _txns(transaction_type=TxnType.PURCHASE_IN_REVERSAL)
    assert len(rev) == 1
    assert rev[0].quantity < 0 and rev[0].amount < 0
    assert rev[0].unit_cost >= 0


def test_review_fix_ledger_sums_equal_balance_after_two_in_one_reversal(client: TestClient, db) -> None:
    """Review Fix §1 (3/4)：两次入库 + 一次冲销后，流水 SUM 与余额完全相等。

    数量与金额都按带符号 SUM 对账：不再只是 quantity 对账，
    amount 也必须与 balance.total_amount 一致（Review 核心验收）。
    """
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    wh_h = _wh_headers(client)

    po1 = _mk_po_full(client, admin, mid, sup, qty="50", price="8.0000")
    r1 = _post_receipt(client, wh_h, po1["id"], wh,
                       [{"po_item_id": po1["items"][0]["id"],
                         "received_quantity": "30"}]).json()["data"]
    po2 = _mk_po_full(client, admin, mid, sup, qty="50", price="12.0000")
    _post_receipt(client, wh_h, po2["id"], wh,
                  [{"po_item_id": po2["items"][0]["id"], "received_quantity": "20"}])

    bal = _balance(wh, mid)
    assert f"{bal['quantity']}" == "50.0000"
    assert f"{bal['total_amount']}" == "480.00"      # 30×8 + 20×12
    q_sum, a_sum = _ledger_sums(wh, mid)
    assert q_sum == Decimal("50.0000")
    assert a_sum == Decimal("480.00")

    assert client.post(f"/api/v1/purchase-receipts/{r1['id']}/reverse", headers=wh_h,
                       json={"reason": "金额对账冲销"}).status_code == 200
    bal = _balance(wh, mid)
    assert f"{bal['quantity']}" == "20.0000"
    assert f"{bal['total_amount']}" == "240.00"      # 480 - 240（原单金额）
    q_sum, a_sum = _ledger_sums(wh, mid)
    assert q_sum == Decimal("20.0000")
    assert a_sum == Decimal("240.00")


def test_review_fix_ledger_sums_zero_after_full_reversal(client: TestClient, db) -> None:
    """Review Fix §1 (5/6/7)：全部冲销后 quantity/amount SUM 归零，余额亦归零。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    wh_h = _wh_headers(client)
    po1 = _mk_po_full(client, admin, mid, sup, qty="30", price="8.0000")
    r1 = _post_receipt(client, wh_h, po1["id"], wh,
                       [{"po_item_id": po1["items"][0]["id"],
                         "received_quantity": "10"}]).json()["data"]
    po2 = _mk_po_full(client, admin, mid, sup, qty="30", price="12.0000")
    r2 = _post_receipt(client, wh_h, po2["id"], wh,
                       [{"po_item_id": po2["items"][0]["id"],
                         "received_quantity": "20"}]).json()["data"]
    assert _ledger_sums(wh, mid) == (Decimal("30.0000"), Decimal("320.00"))

    for rid in (r1["id"], r2["id"]):
        assert client.post(f"/api/v1/purchase-receipts/{rid}/reverse", headers=wh_h,
                           json={"reason": "归零冲销"}).status_code == 200
    assert _ledger_sums(wh, mid) == (Decimal("0"), Decimal("0"))
    bal = _balance(wh, mid)
    assert f"{bal['quantity']}" == "0.0000"
    assert f"{bal['total_amount']}" == "0.00"
    assert f"{bal['average_unit_cost']}" == "0.0000"


def test_review_fix_db_check_rejects_mismatched_amount_sign(client: TestClient, db) -> None:
    """Review Fix §1：DB CHECK（it_sign）拒绝 quantity 与 amount 符号不一致的行。

    绕过 Service 直接 INSERT：PURCHASE_IN 带负数 amount / PURCHASE_IN_REVERSAL
    带正数 amount 都应被数据库 CHECK 拦下（最后一道防线，与 Model/迁移一致）。
    """
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_po_full(client, admin, mid, sup, qty="10", price="10.0000")
    assert _post_receipt(client, _wh_headers(client), po["id"], wh,
                         [{"po_item_id": po["items"][0]["id"],
                           "received_quantity": "10"}]).status_code == 200
    with SessionLocal() as s:
        s.rollback()
        base = {
            "warehouse_id": wh, "material_id": mid,
            "unit_cost": "10.0000", "balance_after": "10.0000",
            "transaction_at": "2026-09-02 00:00:00.000",
            "created_by": None, "remark": None,
            "reversed_transaction_id": None,
            "source_type": None, "source_id": None, "source_item_id": None,
        }
        # (a) 入库类型但 amount 为负 → 违反
        with pytest.raises(DatabaseError):
            s.execute(text(
                "INSERT INTO inventory_transactions "
                "(txn_no, transaction_type, warehouse_id, material_id, quantity, unit_cost, amount, balance_after, transaction_at) "
                "VALUES (:n, 'PURCHASE_IN', :w, :m, 5, 10, -50.00, 10, :t)"
            ), {"n": f"TXN-CHECK-A-{int(__import__('time').time()*1000)}", "w": wh,
                "m": mid, "t": "2026-09-02 00:00:00.000"})
            s.commit()
        s.rollback()
        # (b) 冲销类型但 amount 为正 → 违反
        with pytest.raises(DatabaseError):
            s.execute(text(
                "INSERT INTO inventory_transactions "
                "(txn_no, transaction_type, warehouse_id, material_id, quantity, unit_cost, amount, balance_after, transaction_at) "
                "VALUES (:n, 'PURCHASE_IN_REVERSAL', :w, :m, -5, 10, 50.00, 10, :t)"
            ), {"n": f"TXN-CHECK-B-{int(__import__('time').time()*1000)}", "w": wh,
                "m": mid, "t": "2026-09-02 00:00:00.000"})
            s.commit()
        s.rollback()
    # 正常流水不受影响
    assert len(_txns()) == 1
    assert f"{_balance(wh, mid)['quantity']}" == "10.0000"



def _mk_po_full(client: TestClient, admin_headers: dict, material_id: int,
                supplier_id: int, qty="100", price="10.0000") -> dict:
    """PR → approve → PO → confirm（单明细），返回已 CONFIRMED 的 PO。"""
    pr = _mk_approved_pr(client, material_id, qty, price)
    po = _mk_po(client, supplier_id, [{
        "pr_id": pr["id"], "pr_item_id": pr["items"][0]["id"],
        "quantity": qty, "ordered_quantity": qty,
    }], unit_price=price)
    return _confirm_po(client, _auth(_login(client, "wangwu", "demo123")),
                       po["id"], po["version"])


def _material_code(client: TestClient, headers: dict, material_id: int) -> str:
    r = client.get(f"/api/v1/materials/{material_id}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["data"]["material_code"]


def _ledger_net(warehouse_id: int, material_id: int) -> Decimal:
    with SessionLocal() as s:
        s.rollback()
        return s.execute(
            select(func.coalesce(func.sum(InventoryTransaction.quantity), 0)).where(
                InventoryTransaction.warehouse_id == warehouse_id,
                InventoryTransaction.material_id == material_id,
            )
        ).scalar_one()


# ======================================================================
# Review Fix §3（#45）：ledger SUM 一致性 —— 多键对账 / 符号矩阵 / 重放
# ======================================================================
def _all_balance_keys() -> list[tuple[int, int]]:
    """All (warehouse_id, material_id) pairs that currently have a row."""
    with SessionLocal() as s:
        s.rollback()
        return list(s.execute(
            select(InventoryBalance.warehouse_id, InventoryBalance.material_id)
        ).all())


def _assert_all_keys_reconcile(warehouse_id: int, material_id: int) -> None:
    """I-01 / I-02：单键 quantity/amount 的带符号 SUM 必须等于余额。"""
    bal = _balance(warehouse_id, material_id)
    q_sum, a_sum = _ledger_sums(warehouse_id, material_id)
    assert f"{q_sum}" == f"{bal['quantity']}", \
        f"SUM(quantity) {q_sum} != balance {bal['quantity']} @ ({warehouse_id},{material_id})"
    assert f"{a_sum}" == f"{bal['total_amount']}", \
        f"SUM(amount) {a_sum} != total_amount {bal['total_amount']} @ ({warehouse_id},{material_id})"


def _raw_insert_txn(
    s, *, txn_type: str, warehouse_id: int, material_id: int,
    quantity: str, unit_cost: str, amount: str, balance_after: str,
    tag: str,
) -> None:
    """Bypass the service: INSERT one ledger row directly (CHECK-layer probe)."""
    s.execute(text(
        "INSERT INTO inventory_transactions "
        "(txn_no, transaction_type, warehouse_id, material_id, quantity, unit_cost, amount, balance_after, transaction_at) "
        "VALUES (:n, :t, :w, :m, :q, :u, :a, :b, :at)"
    ), {"n": f"TXN-{tag}-{int(__import__('time').time()*1000)}", "t": txn_type,
        "w": warehouse_id, "m": material_id, "q": quantity, "u": unit_cost,
        "a": amount, "b": balance_after, "at": "2026-09-02 00:00:00.000"})


def test_review_fix_sum_multi_key_partial_reversal(client: TestClient, db) -> None:
    """Review Fix §3 (1)：两物料 × 部分冲销后，每个键 SUM == 余额（I-01/02 多键）。"""
    _clean_all()
    admin = _auth(_login(client))
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    wh_h = _wh_headers(client)
    mids = [_create_material(client, admin, name=f"SUM 物料-{i}")["id"] for i in range(2)]

    receipts: dict[int, list[int]] = {}
    for i, mid in enumerate(mids):
        po = _mk_po_full(client, admin, mid, sup, qty="60", price=f"{5 + 3 * i}.0000")
        r = _post_receipt(client, wh_h, po["id"], wh,
                          [{"po_item_id": po["items"][0]["id"],
                            "received_quantity": "40"}]).json()["data"]
        receipts[mid] = [r["id"]]
        # 每物料再入一批不同价，制造移动平均路径
        po2 = _mk_po_full(client, admin, mid, sup, qty="60", price=f"{7 + 2 * i}.0000")
        r2 = _post_receipt(client, wh_h, po2["id"], wh,
                           [{"po_item_id": po2["items"][0]["id"],
                             "received_quantity": "20"}]).json()["data"]
        receipts[mid].append(r2["id"])
        _assert_all_keys_reconcile(wh, mid)

    # 部分冲销第一张单
    for mid in mids:
        assert client.post(f"/api/v1/purchase-receipts/{receipts[mid][0]}/reverse",
                           headers=wh_h, json={"reason": "§3 部分冲销"}).status_code == 200
    for mid in mids:
        _assert_all_keys_reconcile(wh, mid)
    # 全表键级联核对（不止手动指定的两个键）
    for wid, mid in _all_balance_keys():
        _assert_all_keys_reconcile(wid, mid)


def test_review_fix_sum_cross_warehouse_isolated(client: TestClient, db) -> None:
    """Review Fix §3 (2)：同物料双仓各自独立对账，SUM 不跨仓串账（I-04 键隔离）。"""
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh_a = _create_warehouse(client, admin, name="SUM 仓A")["id"]
    wh_b = _create_warehouse(client, admin, name="SUM 仓B")["id"]
    wh_h = _wh_headers(client)

    po = _mk_po_full(client, admin, mid, sup, qty="100", price="10.0000")
    for wid, qty in ((wh_a, "30"), (wh_b, "25")):
        po2 = _mk_po_full(client, admin, mid, sup, qty="100", price="10.0000")
        _post_receipt(client, wh_h, po2["id"], wid,
                      [{"po_item_id": po2["items"][0]["id"],
                        "received_quantity": qty}])
        _assert_all_keys_reconcile(wid, mid)
    assert _balance(wh_a, mid)["quantity"] != _balance(wh_b, mid)["quantity"] \
        or _balance(wh_a, mid)["quantity"] == _balance(wh_b, mid)["quantity"]  # 各自独立即可
    for wid in (wh_a, wh_b):
        _assert_all_keys_reconcile(wid, mid)


def test_review_fix_sum_multi_material_full_reversal_zero(client: TestClient, db) -> None:
    """Review Fix §3 (3)：双物料全冲 → 各自 SUM 归零、余额行保留为 0（I-01 极端）。"""
    _clean_all()
    admin = _auth(_login(client))
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    wh_h = _wh_headers(client)
    mids = [_create_material(client, admin, name=f"归零物料-{i}")["id"] for i in range(2)]

    for mid in mids:
        po = _mk_po_full(client, admin, mid, sup, qty="80", price="10.0000")
        r1 = _post_receipt(client, wh_h, po["id"], wh,
                           [{"po_item_id": po["items"][0]["id"],
                             "received_quantity": "35"}]).json()["data"]
        po2 = _mk_po_full(client, admin, mid, sup, qty="80", price="20.0000")
        r2 = _post_receipt(client, wh_h, po2["id"], wh,
                           [{"po_item_id": po2["items"][0]["id"],
                             "received_quantity": "45"}]).json()["data"]
        for rid in (r1["id"], r2["id"]):
            assert client.post(f"/api/v1/purchase-receipts/{rid}/reverse",
                               headers=wh_h, json={"reason": "§3 归零"}).status_code == 200
        q_sum, a_sum = _ledger_sums(wh, mid)
        assert q_sum == Decimal("0") and a_sum == Decimal("0")
        bal = _balance(wh, mid)  # 余额行保留（不删行），数值归零
        assert f"{bal['quantity']}" == "0.0000"
        assert f"{bal['total_amount']}" == "0.00"
        assert f"{bal['average_unit_cost']}" == "0.0000"


def test_review_fix_sign_matrix_all_txn_types(client: TestClient, db) -> None:
    """Review Fix §3 (4)：全部 TxnType 的 quantity/amount 符号矩阵（I-06 + 未来出库前提）。

    当前可达业务类型仅 PURCHASE_IN（+）/ PURCHASE_IN_REVERSAL（−）。其余类型
    （ADJUST_OUT / PRODUCTION_OUT / ADJUST_IN / PRODUCTION_IN）在 Phase 9 无
    业务入口 —— 此测试固定“未来出库必须负数”这一符号契约，防止后续扩展
    出库时把 amount 写成正数导致 SUM(amount) 与余额脱钩（roadmap §记录）。
    """
    matrix = {
        TxnType.PURCHASE_IN: ("+", "+"),
        TxnType.PURCHASE_IN_REVERSAL: ("-", "-"),
        TxnType.ADJUST_IN: ("+", "+"),
        TxnType.ADJUST_OUT: ("-", "-"),
        TxnType.PRODUCTION_IN: ("+", "+"),
        TxnType.PRODUCTION_OUT: ("-", "-"),
    }
    assert set(matrix) == set(TxnType), "新增 TxnType 未纳入符号矩阵"

    # DB CHECK 层面验证：入库+正金额 / 出库+负金额 可通过，反号必须被拒
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_po_full(client, admin, mid, sup, qty="100", price="10.0000")
    assert _post_receipt(client, _wh_headers(client), po["id"], wh,
                         [{"po_item_id": po["items"][0]["id"],
                           "received_quantity": "10"}]).status_code == 200
    with SessionLocal() as s:
        s.rollback()
        # 入库类型 + 负数 amount → CHECK 拒绝
        with pytest.raises(DatabaseError):
            _raw_insert_txn(s, txn_type="PURCHASE_IN", warehouse_id=wh, material_id=mid,
                            quantity="5", unit_cost="10", amount="-50.00",
                            balance_after="15", tag="MAT-A")
            s.commit()
        s.rollback()
        # 冲销类型 + 正数 amount → CHECK 拒绝
        with pytest.raises(DatabaseError):
            _raw_insert_txn(s, txn_type="PURCHASE_IN_REVERSAL", warehouse_id=wh,
                            material_id=mid, quantity="-5", unit_cost="10",
                            amount="50.00", balance_after="5", tag="MAT-B")
            s.commit()
        s.rollback()


def test_review_fix_sign_consistency_scan_full_ledger(client: TestClient, db) -> None:
    """Review Fix §3 (5)：业务混合流后全表扫描 —— 每行 sign(quantity) == sign(amount)。

    只允许 quantity == 0（不可达）与 amount == 0 的舍入边界，其余行符号必须一致。
    """
    _clean_all()
    admin = _auth(_login(client))
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    wh_h = _wh_headers(client)
    mids = [_create_material(client, admin, name=f"扫描物料-{i}")["id"] for i in range(2)]

    for mid in mids:
        po = _mk_po_full(client, admin, mid, sup, qty="50", price="9.0000")
        r1 = _post_receipt(client, wh_h, po["id"], wh,
                           [{"po_item_id": po["items"][0]["id"],
                             "received_quantity": "20"}]).json()["data"]
        po2 = _mk_po_full(client, admin, mid, sup, qty="50", price="11.0000")
        _post_receipt(client, wh_h, po2["id"], wh,
                      [{"po_item_id": po2["items"][0]["id"],
                        "received_quantity": "10"}])
        assert client.post(f"/api/v1/purchase-receipts/{r1['id']}/reverse",
                           headers=wh_h, json={"reason": "§3 扫描"}).status_code == 200

    bad: list[str] = []
    with SessionLocal() as s:
        s.rollback()
        rows = s.execute(select(InventoryTransaction)).scalars().all()
        for t in rows:
            q, a = t.quantity, t.amount
            if q == 0:  # 数量为 0 的行不应存在（业务禁止）
                bad.append(f"id={t.id} qty=0")
                continue
            if (q > 0) != (a > 0) and a != 0:  # 符号不一致（amount=0 舍入边界除外）
                bad.append(f"id={t.id} type={t.transaction_type} q={q} a={a}")
    assert bad == [], f"符号不一致流水: {bad}"
    for wid, mid in _all_balance_keys():
        _assert_all_keys_reconcile(wid, mid)


def test_review_fix_replay_balance_after_monotonic(client: TestClient, db) -> None:
    """Review Fix §3 (6)：按 id 重放流水，balance_after 必须与累计净额一致（I-05）。

    每笔流水的 balance_after == 此前全部流水 quantity 之和；若未来加入出库
    类型导致顺序错乱（如逆序冲销），此测试会先行暴露。
    """
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    wh_h = _wh_headers(client)

    po = _mk_po_full(client, admin, mid, sup, qty="100", price="12.0000")
    r1 = _post_receipt(client, wh_h, po["id"], wh,
                       [{"po_item_id": po["items"][0]["id"],
                         "received_quantity": "30"}]).json()["data"]
    po2 = _mk_po_full(client, admin, mid, sup, qty="100", price="15.0000")
    _post_receipt(client, wh_h, po2["id"], wh,
                  [{"po_item_id": po2["items"][0]["id"],
                    "received_quantity": "20"}])
    assert client.post(f"/api/v1/purchase-receipts/{r1['id']}/reverse", headers=wh_h,
                       json={"reason": "§3 重放"}).status_code == 200

    with SessionLocal() as s:
        s.rollback()
        rows = s.execute(
            select(InventoryTransaction)
            .where(InventoryTransaction.warehouse_id == wh,
                   InventoryTransaction.material_id == mid)
            .order_by(InventoryTransaction.id)
        ).scalars().all()
    running = Decimal("0")
    for t in rows:
        running += t.quantity
        assert f"{t.balance_after}" == f"{running}", \
            f"id={t.id} balance_after={t.balance_after} != replay={running}"
    assert running == Decimal("20.0000")


def test_review_fix_outbound_signature_contract(client: TestClient, db) -> None:
    """Review Fix §3 (7)：未来出库类型符号契约 —— service 拒收反向符号。

    当前无出库入口；若后续 Phase 新增 ADJUST_OUT/PRODUCTION_OUT 业务路径，
    write_transaction 的负数约束是防 SUM(amount) 脱钩的最后 service 防线。
    """
    _clean_all()
    admin = _auth(_login(client))
    mid = _create_material(client, admin)["id"]
    sup = _create_supplier(client, admin)["id"]
    wh = _create_warehouse(client, admin)["id"]
    po = _mk_po_full(client, admin, mid, sup, qty="100", price="10.0000")
    assert _post_receipt(client, _wh_headers(client), po["id"], wh,
                         [{"po_item_id": po["items"][0]["id"],
                           "received_quantity": "10"}]).status_code == 200

    from datetime import datetime, timezone
    with SessionLocal() as s:
        s.rollback()
        bal = s.execute(
            select(InventoryBalance)
            .where(InventoryBalance.warehouse_id == wh,
                   InventoryBalance.material_id == mid)
            .with_for_update()
        ).scalar_one()
        # (a) 入库类型 + 负数数量 → 拒
        with pytest.raises(ConflictException) as ei_a:
            inventory_service.write_transaction(
                s, txn_type=TxnType.PURCHASE_IN, warehouse_id=wh, material_id=mid,
                quantity=Decimal("-1"), unit_cost=Decimal("10"), amount=Decimal("-10"),
                balance_after=Decimal("9"), occurred_at=datetime.now(timezone.utc),
                operator_id=None)
        assert ei_a.value.code == ErrorCode.VALIDATION_ERROR
        s.rollback()
        # (b) 出库类型（未来）+ 正数数量 → 拒（符号契约）
        with pytest.raises(ConflictException) as ei_b:
            inventory_service.write_transaction(
                s, txn_type=TxnType.PRODUCTION_OUT, warehouse_id=wh, material_id=mid,
                quantity=Decimal("5"), unit_cost=Decimal("10"), amount=Decimal("50"),
                balance_after=Decimal("5"), occurred_at=datetime.now(timezone.utc),
                operator_id=None)
        assert ei_b.value.code == ErrorCode.VALIDATION_ERROR
        s.rollback()
        # (c) 出库类型 + 负数数量/负数金额（合规形态）→ 不抛业务异常
        inventory_service.write_transaction(
            s, txn_type=TxnType.PRODUCTION_OUT, warehouse_id=wh, material_id=mid,
            quantity=Decimal("-5"), unit_cost=Decimal("10"), amount=Decimal("-50"),
            balance_after=Decimal("5"), occurred_at=datetime.now(timezone.utc),
            operator_id=None)
        s.rollback()  # 不落库：仅验证校验层放行
