"""Shared test-data cleanup for the PR -> Approval -> PO -> Receipt -> Inventory chain.

Why this exists (Phase 9)
-------------------------
The Phase 9 chain adds three tables between ``purchase_order_items`` and the
master data, all with ``ON DELETE RESTRICT`` foreign keys::

    inventory_transactions  (append-only: MySQL triggers block DELETE/UPDATE)
    purchase_receipt_items  fk_ri_poi -> purchase_order_items   (RESTRICT)
    purchase_receipts       fk_receipt_po -> purchase_orders    (RESTRICT)

So the older Phase 6/7/8 cleanup helpers — which only deleted PO/PR rows —
started failing with MySQL 1451 as soon as any receipt test had run before
them. Every cleanup in the suite therefore funnels through
:func:`wipe_chain`, which deletes in FK-safe order and temporarily lifts the
append-only triggers (they exist exactly to stop this in production; tests
need a clean slate).

``inventory_transactions`` also has a self-referencing FK
(``reversed_transaction_id``), so rows must be unlinked before the table can
be truncated.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import SessionLocal

#: Append-only guards created by the Phase 2 migration.
_TRIGGERS = ("trg_it_no_update", "trg_it_no_delete")

_TRIGGER_DDL = {
    "trg_it_no_update": (
        "CREATE TRIGGER trg_it_no_update BEFORE UPDATE ON inventory_transactions "
        "FOR EACH ROW BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = "
        "'inventory_transactions is append-only: UPDATE forbidden, use reversal transaction'; END"
    ),
    "trg_it_no_delete": (
        "CREATE TRIGGER trg_it_no_delete BEFORE DELETE ON inventory_transactions "
        "FOR EACH ROW BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = "
        "'inventory_transactions is append-only: DELETE forbidden, use reversal transaction'; END"
    ),
}


def wipe_chain(session: Session, *, with_balances: bool = True) -> None:
    """Delete receipts, ledger and the whole upstream PO/PR chain.

    Safe to call on an empty schema. Number sequences are never touched —
    daily document counters are monotonic and gaps are allowed (rule 1).
    """
    ledger_rows = session.execute(
        text("SELECT COUNT(*) FROM inventory_transactions")
    ).scalar_one()
    if ledger_rows:
        for name in _TRIGGERS:
            session.execute(text(f"DROP TRIGGER IF EXISTS {name}"))
        # 自引用 FK：先解链，否则整表删除报 1451
        session.execute(text("UPDATE inventory_transactions SET reversed_transaction_id = NULL"))
        session.execute(text("DELETE FROM inventory_transactions"))
        for name, ddl in _TRIGGER_DDL.items():
            session.execute(text(ddl))

    for table in (
        "stock_reconciliation_items",
        "stock_reconciliations",
        "purchase_receipt_items",
        "purchase_receipts",
        "purchase_order_item_sources",
        "purchase_order_items",
        "purchase_orders",
        "approval_records",
        "purchase_requisition_items",
        "purchase_requisitions",
    ):
        session.execute(text(f"DELETE FROM {table}"))
    if with_balances:
        session.execute(text("DELETE FROM inventory_balances"))


def wipe_business_data() -> None:
    """One-shot wipe of the whole chain *and* master data (own session)."""
    with SessionLocal() as s:
        wipe_chain(s)
        for table in ("inventory_policies", "materials", "suppliers", "warehouses"):
            s.execute(text(f"DELETE FROM {table}"))
        s.commit()
