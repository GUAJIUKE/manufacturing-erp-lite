"""Sprint 1 / Code Review (CR-A-002/009): ledger watermark snapshot column.

Adds an immutable per-line watermark to ``stock_reconciliation_items``:

* ``book_last_transaction_id_snapshot`` BIGINT UNSIGNED NULL — the latest
  ``inventory_transactions.id`` for the (warehouse, material) key at the
  moment the line's book snapshots were captured; NULL when the key has no
  ledger row yet. It backs the POST-time **Ledger Event Guard** (CR-A-001/003):
  any inventory movement after the snapshot — even one later fully compensated
  back to the original quantity/amount — advances the watermark and makes the
  line stale (7005).

The previous Sprint A migration (a7b9c1d2e3f4a5b6) is left untouched — it has
already been applied to dev/test — so this is a separate additive migration.
The type/comment must stay byte-identical to the model to keep ``alembic
check`` drift-free.

Revision ID: d4e5f6a7b8c9d0a1
Revises:     a7b9c1d2e3f4a5b6 (Sprint 1 / Implementation A)
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

#: Alembic revision identifiers.
revision = "d4e5f6a7b8c9d0a1"
down_revision = "a7b9c1d2e3f4a5b6"
branch_labels = None
depends_on = None

_WM_COMMENT = "库存流水水印：快照时 (仓,料) 最新 InventoryTransaction.id；无流水为 NULL（CR-A-002）"


def upgrade() -> None:
    op.add_column(
        "stock_reconciliation_items",
        sa.Column(
            "book_last_transaction_id_snapshot",
            mysql.BIGINT(unsigned=True),
            nullable=True,
            comment=_WM_COMMENT,
        ),
    )
    op.create_check_constraint(
        "ck_rc_wm_null_or_pos",
        "stock_reconciliation_items",
        "book_last_transaction_id_snapshot IS NULL OR book_last_transaction_id_snapshot > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_rc_wm_null_or_pos", "stock_reconciliation_items", type_="check"
    )
    op.drop_column("stock_reconciliation_items", "book_last_transaction_id_snapshot")
