"""Phase 9: purchase receipt + inventory money-scale alignment.

Everything Phase 9 needs structurally already exists (the four warehouse
tables were created in the Phase 2 base migration, and the ENUM values
``PURCHASE_IN`` / ``PURCHASE_IN_REVERSAL`` / ``RECEIPT_POST`` /
``RECEIPT_REVERSE`` are already in place). This migration only aligns the
money columns with the project-wide policy and widens the reversal reason:

1. ``purchase_receipt_items.amount`` was a persisted generated column
   rounded to 4 decimals. Phase 9 moves the calculation to the service
   layer with ROUND_HALF_UP to 2 decimals (same treatment PO item
   ``amount`` got in Phase 8), so the generated column is dropped and
   re-added as a plain column. MySQL has no ALTER for generated columns —
   drop + add is required.

2. ``inventory_balances.total_amount`` and ``inventory_transactions.amount``
   follow the money policy (2 decimals, ROUND_HALF_UP) instead of 4.
   ``inventory_balances.average_unit_cost`` stays at 4 decimals because it
   is a unit price, not an amount (Phase 9 §十二).

3. ``purchase_receipts.reverse_reason`` is widened from VARCHAR(500) to
   VARCHAR(1000) so the service can validate the documented 1000-char
   limit without the DB truncating/erroring first.

4. Comments are kept byte-identical to the ORM models (Phase 6 lesson:
   a comment drift makes ``alembic check`` report a false difference).

No ENUM change is required: ``TxnType``, ``ReceiptStatus`` and
``AuditAction`` already carry every value Phase 9 uses.

Revision ID: c3f8a1d2b7e9 (Phase 9, purchase receipt & inventory)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

#: Alembic revision identifiers.
revision = "c3f8a1d2b7e9"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. receipt item: generated column (18,4) -> plain service-computed (18,2)
    op.drop_column("purchase_receipt_items", "amount")
    op.add_column(
        "purchase_receipt_items",
        sa.Column(
            "amount",
            sa.Numeric(18, 2),
            nullable=False,
            server_default="0",
            comment="入库金额（服务端计算：ROUND_HALF_UP(received_quantity × unit_price, 2)，非生成列）",
        ),
    )

    # 2. money columns -> 2 decimals (18,2)
    op.alter_column(
        "inventory_balances",
        "total_amount",
        existing_type=sa.Numeric(18, 4),
        type_=sa.Numeric(18, 2),
        existing_nullable=False,
        existing_server_default=sa.text("0"),
        comment="账面总金额（权威值，ROUND_HALF_UP 2 位）",
    )
    op.alter_column(
        "inventory_transactions",
        "amount",
        existing_type=sa.Numeric(18, 4),
        type_=sa.Numeric(18, 2),
        existing_nullable=False,
        existing_server_default=sa.text("0"),
        comment="计价金额（quantity × unit_cost 带符号，ROUND_HALF_UP 2 位）",
    )

    # 3. receipt header: wider reversal reason + RCV numbering comment
    op.alter_column(
        "purchase_receipts",
        "reverse_reason",
        existing_type=sa.String(length=500),
        type_=sa.String(length=1000),
        existing_nullable=True,
        comment="冲销原因（必填）",
    )
    op.alter_column(
        "purchase_receipts",
        "receipt_no",
        existing_type=sa.String(length=32),
        existing_nullable=False,
        comment="RCV-20260901-0001",
    )
    # 入库单编号前缀由 REC 改为 RCV（Phase 9 §三），序列键注释同步
    op.alter_column(
        "number_sequences",
        "sequence_key",
        existing_type=sa.String(length=32),
        existing_nullable=False,
        comment="PR/PO/RCV/TXN/MAT/SUP/WH",
    )


def downgrade() -> None:
    op.alter_column(
        "number_sequences",
        "sequence_key",
        existing_type=sa.String(length=32),
        existing_nullable=False,
        comment="PR/PO/REC/TXN/MAT/SUP/WH",
    )
    op.alter_column(
        "purchase_receipts",
        "receipt_no",
        existing_type=sa.String(length=32),
        existing_nullable=False,
        comment="REC-20260901-0001",
    )
    op.alter_column(
        "purchase_receipts",
        "reverse_reason",
        existing_type=sa.String(length=1000),
        type_=sa.String(length=500),
        existing_nullable=True,
        comment="冲销原因（必填）",
    )
    op.alter_column(
        "inventory_transactions",
        "amount",
        existing_type=sa.Numeric(18, 2),
        type_=sa.Numeric(18, 4),
        existing_nullable=False,
        existing_server_default=sa.text("0"),
        comment="计价金额（quantity * unit_cost，带符号）",
    )
    op.alter_column(
        "inventory_balances",
        "total_amount",
        existing_type=sa.Numeric(18, 2),
        type_=sa.Numeric(18, 4),
        existing_nullable=False,
        existing_server_default=sa.text("0"),
        comment="账面总金额",
    )
    op.drop_column("purchase_receipt_items", "amount")
    op.add_column(
        "purchase_receipt_items",
        sa.Column(
            "amount",
            sa.Numeric(18, 4),
            sa.Computed("ROUND(received_quantity * unit_price, 4)", persisted=True),
            nullable=False,
            comment="入库金额（生成列）",
        ),
    )
