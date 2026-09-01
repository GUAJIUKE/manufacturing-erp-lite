"""Phase 6: purchase requisition business-document changes.

Four schema changes needed by the PR module (Phase 6):

1. ``purchase_requisitions`` gains the optimistic-lock column ``version``
   (Phase 6 §十一) and ``submitted_at`` (set on submit, Phase 6 §九);
   ``total_estimated_amount`` is narrowed from DECIMAL(18,4) to
   DECIMAL(18,2) to match the money policy (Phase 6 §一 / §八).

2. ``purchase_requisition_items.estimated_amount`` was a persisted generated
   column computed at 4 decimals. Phase 6 moves the calculation to the
   service layer with ROUND_HALF_UP to 2 decimals (Phase 6 §八), so the
   generated column is dropped and re-added as a plain column. MySQL has no
   ALTER for generated columns — drop + add is required.

3. ``purchase_requisition_items`` gets a CHECK that ``estimated_unit_price``
   is non-negative (``pri_price_nonneg``), mirroring the PO item rule.

4. ``operation_logs`` gains ``document_no`` so audit rows can carry the
   business document number (e.g. PR-20260901-0001, Phase 6 §十五), and the
   ``action`` ENUM is extended with PR_CREATE / PR_UPDATE.

Revision ID: f2a7d3b5c9e1 (Phase 6, purchase requisition)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

#: Alembic revision identifiers.
revision = "f2a7d3b5c9e1"
down_revision = "9f2e7c1a4b8d"
branch_labels = None
depends_on = None

#: Full action value set (24 from Phase 5 + PR_CREATE / PR_UPDATE).
_AUDIT_ACTIONS = (
    "LOGIN",
    "LOGIN_FAILED",
    "PR_CREATE",
    "PR_UPDATE",
    "PR_SUBMIT",
    "PR_APPROVE",
    "PR_REJECT",
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

#: Value set before this migration (Phase 5).
_PREVIOUS_ACTIONS = (
    "LOGIN",
    "LOGIN_FAILED",
    "PR_SUBMIT",
    "PR_APPROVE",
    "PR_REJECT",
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

_PRICE_CHECK = "pri_price_nonneg"


def _enum_ddl(values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"ENUM({quoted})"


def upgrade() -> None:
    # 1. PR header: version + submitted_at + money scale 18,2
    op.add_column(
        "purchase_requisitions",
        sa.Column(
            "submitted_at",
            DATETIME(fsp=3),
            nullable=True,
            comment="提交时间（UTC，submit 时写入）",
        ),
    )
    op.add_column(
        "purchase_requisitions",
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default="1",
            comment="乐观锁版本号（更新/提交/取消时递增）",
        ),
    )
    op.alter_column(
        "purchase_requisitions",
        "total_estimated_amount",
        existing_type=sa.Numeric(18, 4),
        type_=sa.Numeric(18, 2),
        existing_nullable=False,
        existing_server_default=sa.text("0"),
        comment="明细预估金额合计（服务端汇总，ROUND_HALF_UP）",
    )

    # 2. PR item: generated column -> plain service-computed column (18,2)
    op.drop_column("purchase_requisition_items", "estimated_amount")
    op.add_column(
        "purchase_requisition_items",
        sa.Column(
            "estimated_amount",
            sa.Numeric(18, 2),
            nullable=False,
            server_default="0",
            comment="预估金额（服务端计算：ROUND_HALF_UP(qty × price, 2)，非生成列）",
        ),
    )

    # 3. PR item: non-negative unit price CHECK
    op.create_check_constraint(
        _PRICE_CHECK,
        "purchase_requisition_items",
        "estimated_unit_price >= 0",
    )

    # 4. audit: document_no column + extended action ENUM
    op.add_column(
        "operation_logs",
        sa.Column(
            "document_no",
            sa.String(32),
            nullable=True,
            comment="关联单据编号（如 PR-20260901-0001）",
        ),
    )
    op.execute(
        f"ALTER TABLE operation_logs "
        f"MODIFY COLUMN action {_enum_ddl(_AUDIT_ACTIONS)} NOT NULL"
    )


def downgrade() -> None:
    op.execute(
        f"ALTER TABLE operation_logs "
        f"MODIFY COLUMN action {_enum_ddl(_PREVIOUS_ACTIONS)} NOT NULL"
    )
    op.drop_column("operation_logs", "document_no")
    op.drop_constraint(_PRICE_CHECK, "purchase_requisition_items", type_="check")
    op.drop_column("purchase_requisition_items", "estimated_amount")
    op.add_column(
        "purchase_requisition_items",
        sa.Column(
            "estimated_amount",
            sa.Numeric(18, 4),
            sa.Computed("ROUND(requested_quantity * estimated_unit_price, 4)", persisted=True),
            nullable=False,
        ),
    )
    op.alter_column(
        "purchase_requisitions",
        "total_estimated_amount",
        existing_type=sa.Numeric(18, 2),
        type_=sa.Numeric(18, 4),
        existing_nullable=False,
        existing_server_default=sa.text("0"),
        comment="明细预估金额合计（服务端汇总）",
    )
    op.drop_column("purchase_requisitions", "version")
    op.drop_column("purchase_requisitions", "submitted_at")
