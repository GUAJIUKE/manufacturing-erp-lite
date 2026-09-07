"""Reality Hardening Sprint 1 / Implementation A: stock reconciliation core.

Adds the approved Design v2 tables:

* ``stock_reconciliations``        count-document header (DRAFT/PENDING/POSTED/...)
* ``stock_reconciliation_items``   lines with the three frozen book snapshots
  (quantity / total_amount / avg_cost), physical count, server-side
  difference and signed adjustment amount.

Plus two additive ENUM extensions (new values appended, existing value order
preserved so stored enum indices never shift):

* ``operation_logs.action``        += STOCK_COUNT_CREATE/SUBMIT/APPROVE/REJECT
* ``inventory_transactions.source_type`` += STOCK_RECONCILIATION

``inventory_transactions.transaction_type`` already carries ADJUST_IN /
ADJUST_OUT (Phase 2 base migration), so no change is needed there; the
existing ``it_sign`` CHECK already constrains those types' sign semantics.

Revision ID: a7b9c1d2e3f4a5b6
Revises:     e5f6a7b8c9d0 (Review Fix §1)
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

#: Alembic revision identifiers.
revision = "a7b9c1d2e3f4a5b6"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# ENUM extension lists (current DB order + appended values)
# ---------------------------------------------------------------------------
_AUDIT_ACTIONS_BEFORE = (
    "LOGIN", "LOGIN_FAILED", "PR_CREATE", "PR_UPDATE", "PR_SUBMIT", "PR_APPROVE",
    "PR_REJECT", "PR_REVISE", "PR_CANCEL", "PO_CREATE", "PO_CONFIRM", "PO_CANCEL",
    "RECEIPT_POST", "RECEIPT_REVERSE", "PERMISSION_CHANGE",
    "MATERIAL_CREATE", "MATERIAL_UPDATE", "MATERIAL_DISABLE", "MATERIAL_ENABLE",
    "SUPPLIER_CREATE", "SUPPLIER_UPDATE", "SUPPLIER_DISABLE", "SUPPLIER_ENABLE",
    "WAREHOUSE_CREATE", "WAREHOUSE_UPDATE", "WAREHOUSE_DISABLE", "WAREHOUSE_ENABLE",
    "INVENTORY_POLICY_CHANGE",
)
_AUDIT_ACTIONS_AFTER = _AUDIT_ACTIONS_BEFORE + (
    "STOCK_COUNT_CREATE", "STOCK_COUNT_SUBMIT", "STOCK_COUNT_APPROVE", "STOCK_COUNT_REJECT",
)

_SOURCE_TYPES_BEFORE = (
    "PURCHASE_RECEIPT", "PURCHASE_RECEIPT_REVERSAL", "MANUAL_ADJUST",
    "PRODUCTION_ISSUE", "PRODUCTION_RECEIPT",
)
_SOURCE_TYPES_AFTER = _SOURCE_TYPES_BEFORE + ("STOCK_RECONCILIATION",)


def _enum_ddl(values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"ENUM({quoted})"


def upgrade() -> None:
    # ---- additive ENUM extensions --------------------------------------
    op.execute(
        f"ALTER TABLE operation_logs "
        f"MODIFY COLUMN action {_enum_ddl(_AUDIT_ACTIONS_AFTER)} NOT NULL"
    )
    op.execute(
        "ALTER TABLE inventory_transactions "
        f"MODIFY COLUMN source_type {_enum_ddl(_SOURCE_TYPES_AFTER)} NULL "
        "COMMENT '来源单据类型'"
    )

    # ---- stock_reconciliations (header) ---------------------------------
    op.create_table(
        "stock_reconciliations",
        sa.Column("reconciliation_no", sa.String(length=32), nullable=False, comment="CNT-20260904-0001"),
        sa.Column("warehouse_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("counted_by", mysql.BIGINT(unsigned=True), nullable=False, comment="盘点人（服务端取自 token）"),
        sa.Column("counted_on", sa.Date(), nullable=False, comment="盘点业务日期（v1 强制 = 今天，RD-001）"),
        sa.Column(
            "status",
            sa.Enum("DRAFT", "PENDING", "POSTED", "REJECTED", "CANCELLED", "REVERSED",
                    name="reconciliationstatus"),
            server_default="DRAFT", nullable=False,
        ),
        sa.Column("reason", sa.String(length=500), nullable=True, comment="单头级盘点原因"),
        sa.Column("remark", sa.String(length=255), nullable=True),
        sa.Column("submitted_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column("posted_at", mysql.DATETIME(fsp=3), nullable=True, comment="过账时间"),
        sa.Column("approved_by", mysql.BIGINT(unsigned=True), nullable=True, comment="审批/过账人"),
        sa.Column("approve_comment", sa.String(length=1000), nullable=True),
        sa.Column("override_self_approval", sa.Boolean(), server_default="0", nullable=False,
                  comment="SoD override 标志（RD-006）"),
        sa.Column("override_reason", sa.String(length=500), nullable=True, comment="override 必填理由（审计用）"),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False,
                  comment="乐观锁版本号（DRAFT 编辑时递增）"),
        sa.Column("created_at", mysql.DATETIME(fsp=3),
                  server_default=sa.text("CURRENT_TIMESTAMP(3)"), nullable=False, comment="Created at (UTC)"),
        sa.Column("updated_at", mysql.DATETIME(fsp=3),
                  server_default=sa.text("CURRENT_TIMESTAMP(3)"), nullable=False, comment="Last updated at (UTC)"),
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False, comment="Primary key"),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"], name="fk_reconcile_wh", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["counted_by"], ["users.id"], name="fk_reconcile_counted_by", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], name="fk_reconcile_approved_by", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stock_reconciliations")),
        sa.UniqueConstraint("reconciliation_no", name="uk_reconciliation_no"),
    )
    op.create_index("ix_reconcile_wh_status", "stock_reconciliations", ["warehouse_id", "status"], unique=False)
    op.create_index("ix_reconcile_counted_on", "stock_reconciliations", ["counted_on"], unique=False)
    op.create_index("ix_reconcile_status", "stock_reconciliations", ["status"], unique=False)

    # ---- stock_reconciliation_items (lines) ------------------------------
    op.create_table(
        "stock_reconciliation_items",
        sa.Column("reconciliation_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False, comment="行号，单内唯一"),
        sa.Column("material_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("book_quantity_snapshot", sa.Numeric(precision=18, scale=4), nullable=False,
                  comment="账面数量快照（创建行时固化，不静默刷新）"),
        sa.Column("book_total_amount_snapshot", sa.Numeric(precision=18, scale=2), nullable=False,
                  comment="账面总金额快照（DA-001 三快照之一）"),
        sa.Column("book_avg_cost_snapshot", sa.Numeric(precision=18, scale=4), nullable=False,
                  comment="账面移动平均价快照（DA-001 三快照之一）"),
        sa.Column("physical_quantity", sa.Numeric(precision=18, scale=4), nullable=False, comment="实盘数量（>= 0）"),
        sa.Column("difference_quantity", sa.Numeric(precision=18, scale=4), server_default="0", nullable=False,
                  comment="服务端计算 = physical - book_quantity_snapshot"),
        sa.Column("valuation_rate", sa.Numeric(precision=18, scale=4), nullable=True,
                  comment="盘盈入账单价（必填且 > 0，DA-002）；盘亏为 NULL"),
        sa.Column("adjustment_amount", sa.Numeric(precision=18, scale=2), server_default="0", nullable=False,
                  comment="带符号调整金额：盘盈 +money(diff×rate)；盘亏 -money(|diff|×avg_snapshot)"),
        sa.Column("remark", sa.String(length=255), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=3),
                  server_default=sa.text("CURRENT_TIMESTAMP(3)"), nullable=False),
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False, comment="Primary key"),
        sa.ForeignKeyConstraint(["reconciliation_id"], ["stock_reconciliations.id"],
                                name="fk_rc_item_reconcile", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["material_id"], ["materials.id"], name="fk_rc_item_mat", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stock_reconciliation_items")),
        sa.UniqueConstraint("reconciliation_id", "line_no", name="uk_rc_line"),
        sa.UniqueConstraint("reconciliation_id", "material_id", name="uk_rc_mat"),
        sa.CheckConstraint("physical_quantity >= 0", name="ck_rc_physical_nonneg"),
        sa.CheckConstraint("book_quantity_snapshot >= 0", name="ck_rc_qty_snapshot_nonneg"),
        sa.CheckConstraint("book_total_amount_snapshot >= 0", name="ck_rc_amount_snapshot_nonneg"),
        sa.CheckConstraint("book_avg_cost_snapshot >= 0", name="ck_rc_avg_snapshot_nonneg"),
        sa.CheckConstraint("valuation_rate IS NULL OR valuation_rate > 0", name="ck_rc_rate_pos"),
    )
    op.create_index("ix_rc_mat", "stock_reconciliation_items", ["material_id"], unique=False)


def downgrade() -> None:
    # 先删表（连同其内部索引/FK 一起），再恢复 ENUM。注意不能先 DROP 供 FK
    # 使用的索引（MySQL 1553：index needed in a foreign key constraint）。
    op.drop_table("stock_reconciliation_items")
    op.drop_table("stock_reconciliations")

    op.execute(
        "ALTER TABLE inventory_transactions "
        f"MODIFY COLUMN source_type {_enum_ddl(_SOURCE_TYPES_BEFORE)} NULL "
        "COMMENT '来源单据类型'"
    )
    op.execute(
        f"ALTER TABLE operation_logs "
        f"MODIFY COLUMN action {_enum_ddl(_AUDIT_ACTIONS_BEFORE)} NOT NULL"
    )
