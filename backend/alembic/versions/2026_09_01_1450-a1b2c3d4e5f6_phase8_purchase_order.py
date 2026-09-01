"""Phase 8: purchase order (PO) business-document changes.

Four schema changes needed by the PO module (Phase 8):

1. ``purchase_orders`` gains the optimistic-lock column ``version``
   (PO update / confirm / cancel all bump it, Phase 8 §六), and
   ``total_amount`` is narrowed from DECIMAL(18,4) to DECIMAL(18,2) to
   match the money policy (Phase 6 §一 / §八, inherited by PO).

2. ``purchase_order_items.amount`` was a persisted generated column
   computed at 4 decimals. Phase 8 moves the calculation to the service
   layer with ROUND_HALF_UP to 2 decimals (same policy as PR
   ``estimated_amount``, Phase 6 §八), so the generated column is dropped
   and re-added as a plain column. MySQL has no ALTER for generated
   columns — drop + add is required.

3. ``operation_logs.action`` ENUM is extended with PO_CANCEL
   (Phase 8 §九). Value order matches the Python ``AuditAction`` enum.

Revision ID: a1b2c3d4e5f6 (Phase 8, purchase order)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

#: Alembic revision identifiers.
revision = "a1b2c3d4e5f6"
down_revision = "b7c4d9e1a3f6"
branch_labels = None
depends_on = None

#: Full action value set (27 from Phase 7 + PO_CANCEL).
_AUDIT_ACTIONS = (
    "LOGIN",
    "LOGIN_FAILED",
    "PR_CREATE",
    "PR_UPDATE",
    "PR_SUBMIT",
    "PR_APPROVE",
    "PR_REJECT",
    "PR_REVISE",
    "PR_CANCEL",
    "PO_CREATE",
    "PO_CONFIRM",
    "PO_CANCEL",
    "RECEIPT_POST",
    "RECEIPT_REVERSE",
    "PERMISSION_CHANGE",
    "MATERIAL_CREATE",
    "MATERIAL_UPDATE",
    "MATERIAL_DISABLE",
    "MATERIAL_ENABLE",
    "SUPPLIER_CREATE",
    "SUPPLIER_UPDATE",
    "SUPPLIER_DISABLE",
    "SUPPLIER_ENABLE",
    "WAREHOUSE_CREATE",
    "WAREHOUSE_UPDATE",
    "WAREHOUSE_DISABLE",
    "WAREHOUSE_ENABLE",
    "INVENTORY_POLICY_CHANGE",
)

#: Value set before this migration (Phase 7).
_PREVIOUS_ACTIONS = (
    "LOGIN",
    "LOGIN_FAILED",
    "PR_CREATE",
    "PR_UPDATE",
    "PR_SUBMIT",
    "PR_APPROVE",
    "PR_REJECT",
    "PR_REVISE",
    "PR_CANCEL",
    "PO_CREATE",
    "PO_CONFIRM",
    "RECEIPT_POST",
    "RECEIPT_REVERSE",
    "PERMISSION_CHANGE",
    "MATERIAL_CREATE",
    "MATERIAL_UPDATE",
    "MATERIAL_DISABLE",
    "MATERIAL_ENABLE",
    "SUPPLIER_CREATE",
    "SUPPLIER_UPDATE",
    "SUPPLIER_DISABLE",
    "SUPPLIER_ENABLE",
    "WAREHOUSE_CREATE",
    "WAREHOUSE_UPDATE",
    "WAREHOUSE_DISABLE",
    "WAREHOUSE_ENABLE",
    "INVENTORY_POLICY_CHANGE",
)


def _enum_ddl(values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"ENUM({quoted})"


def upgrade() -> None:
    # 1. PO header: version + money scale 18,2
    op.add_column(
        "purchase_orders",
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default="1",
            comment="乐观锁版本号（更新/确认/取消时递增）",
        ),
    )
    op.alter_column(
        "purchase_orders",
        "total_amount",
        existing_type=sa.Numeric(18, 4),
        type_=sa.Numeric(18, 2),
        existing_nullable=False,
        existing_server_default=sa.text("0"),
        comment="明细金额合计（服务端汇总，ROUND_HALF_UP）",
    )

    # 2. PO item: generated column -> plain service-computed column (18,2)
    op.drop_column("purchase_order_items", "amount")
    op.add_column(
        "purchase_order_items",
        sa.Column(
            "amount",
            sa.Numeric(18, 2),
            nullable=False,
            server_default="0",
            comment="金额（服务端计算：ROUND_HALF_UP(ordered_quantity × unit_price, 2)，非生成列）",
        ),
    )

    # 3. audit: PO_CANCEL action
    op.execute(
        f"ALTER TABLE operation_logs "
        f"MODIFY COLUMN action {_enum_ddl(_AUDIT_ACTIONS)} NOT NULL"
    )


def downgrade() -> None:
    op.execute(
        f"ALTER TABLE operation_logs "
        f"MODIFY COLUMN action {_enum_ddl(_PREVIOUS_ACTIONS)} NOT NULL"
    )
    op.drop_column("purchase_order_items", "amount")
    op.add_column(
        "purchase_order_items",
        sa.Column(
            "amount",
            sa.Numeric(18, 4),
            sa.Computed("ROUND(ordered_quantity * unit_price, 4)", persisted=True),
            nullable=False,
            comment="金额（生成列）",
        ),
    )
    op.alter_column(
        "purchase_orders",
        "total_amount",
        existing_type=sa.Numeric(18, 2),
        type_=sa.Numeric(18, 4),
        existing_nullable=False,
        existing_server_default=sa.text("0"),
        comment="明细金额合计（服务端汇总）",
    )
    op.drop_column("purchase_orders", "version")
