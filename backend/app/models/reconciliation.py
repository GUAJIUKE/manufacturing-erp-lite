"""Stock reconciliation models (Reality Hardening Sprint 1 / Implementation A).

Implements Design v2 (§3.2 / §3.3): a count document whose items freeze the
book state at count-entry time (the three snapshots), carry the physical
count entered by the warehouse and, after approval & posting, produce signed
``ADJUST_IN`` / ``ADJUST_OUT`` ledger rows and mutate the balance.

Snapshot immutability (Design v2 §6, DA-001; CR-A-001/002/003)
--------------------------------------------------------------
``book_quantity_snapshot`` / ``book_total_amount_snapshot`` /
``book_avg_cost_snapshot`` are captured when the line is added to a DRAFT and
never silently refreshed. ``book_last_transaction_id_snapshot`` is the *ledger
watermark* at that same instant: the latest ``inventory_transactions.id`` for
the (warehouse, material) key, or NULL when no ledger row exists yet. It is
never fabricated — a transaction is never written merely to capture it.

The POST-time Snapshot Guard is therefore two independent layers (CR-A-003):

1. **Ledger Event Guard** — compare the current ledger watermark (read while
   holding the balance X-lock) against the snapshot watermark. Any movement
   after the snapshot, *even one later fully compensated* (e.g. +10 then -10
   returning qty/amount to the snapshot values), pushes the watermark and
   makes the line stale.
2. **Balance State Guard** — compare the locked current balance against the
   quantity AND total amount snapshots.

Any mismatch raises 7005 (RECONCILIATION_BALANCE_CHANGED) and rolls the whole
transaction back.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mysql import BIGINT as BigInteger, DATETIME

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import PKMixin, TimestampMixin
from app.utils.enums import ReconciliationStatus


class StockReconciliation(PKMixin, TimestampMixin, Base):
    """盘点单单头（Design v2 §3.2）。

    状态机（Implementation A 范围）：DRAFT -> PENDING -> POSTED，
    PENDING -> REJECTED -> DRAFT。CANCELLED / REVERSED 枚举保留给 B。
    """

    __tablename__ = "stock_reconciliations"
    __table_args__ = (
        UniqueConstraint("reconciliation_no", name="uk_reconciliation_no"),
        Index("ix_reconcile_wh_status", "warehouse_id", "status"),
        Index("ix_reconcile_counted_on", "counted_on"),
        Index("ix_reconcile_status", "status"),
    )

    reconciliation_no: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="CNT-20260904-0001"
    )
    warehouse_id: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("warehouses.id", name="fk_reconcile_wh", ondelete="RESTRICT"),
        nullable=False,
    )
    counted_by: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("users.id", name="fk_reconcile_counted_by", ondelete="RESTRICT"),
        nullable=False,
        comment="盘点人（服务端取自 token）",
    )
    counted_on: Mapped[date] = mapped_column(
        Date, nullable=False, comment="盘点业务日期（v1 强制 = 今天，RD-001）"
    )
    status: Mapped[ReconciliationStatus] = mapped_column(
        SAEnum(ReconciliationStatus, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        server_default=ReconciliationStatus.DRAFT.value,
    )
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="单头级盘点原因")
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True, comment="过账时间")
    approved_by: Mapped[int | None] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("users.id", name="fk_reconcile_approved_by", ondelete="RESTRICT"),
        nullable=True,
        comment="审批/过账人",
    )
    approve_comment: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    override_self_approval: Mapped[bool] = mapped_column(
        nullable=False, server_default="0", comment="SoD override 标志（RD-006）"
    )
    override_reason: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="override 必填理由（审计用）"
    )
    version: Mapped[int] = mapped_column(
        nullable=False, server_default="1", comment="乐观锁版本号（DRAFT 编辑时递增）"
    )

    items: Mapped[list["StockReconciliationItem"]] = relationship(
        back_populates="reconciliation",
        cascade="all, delete-orphan",
        order_by="StockReconciliationItem.line_no",
        passive_deletes=True,
    )
    warehouse: Mapped["Warehouse"] = relationship()  # noqa: F821  (type-only import below)


class StockReconciliationItem(PKMixin, Base):
    """盘点单明细（Design v2 §3.3）。

    difference / adjustment_amount 均为**服务端权威计算**（前端只读预览）。
    盘盈（diff > 0）行 valuation_rate 必填且 > 0（DA-002）；盘亏行 valuation_rate
    留空，单价取 book_avg_cost_snapshot。
    """

    __tablename__ = "stock_reconciliation_items"
    __table_args__ = (
        UniqueConstraint("reconciliation_id", "line_no", name="uk_rc_line"),
        UniqueConstraint("reconciliation_id", "material_id", name="uk_rc_mat"),
        Index("ix_rc_mat", "material_id"),
        CheckConstraint("physical_quantity >= 0", name="ck_rc_physical_nonneg"),
        CheckConstraint("book_quantity_snapshot >= 0", name="ck_rc_qty_snapshot_nonneg"),
        CheckConstraint("book_total_amount_snapshot >= 0", name="ck_rc_amount_snapshot_nonneg"),
        CheckConstraint("book_avg_cost_snapshot >= 0", name="ck_rc_avg_snapshot_nonneg"),
        CheckConstraint(
            "valuation_rate IS NULL OR valuation_rate > 0",
            name="ck_rc_rate_pos",
        ),
        CheckConstraint(
            "book_last_transaction_id_snapshot IS NULL OR book_last_transaction_id_snapshot > 0",
            name="ck_rc_wm_null_or_pos",
        ),
    )

    reconciliation_id: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("stock_reconciliations.id", name="fk_rc_item_reconcile", ondelete="CASCADE"),
        nullable=False,
    )
    line_no: Mapped[int] = mapped_column(nullable=False, comment="行号，单内唯一")
    material_id: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("materials.id", name="fk_rc_item_mat", ondelete="RESTRICT"),
        nullable=False,
    )
    book_quantity_snapshot: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, comment="账面数量快照（创建行时固化，不静默刷新）"
    )
    book_total_amount_snapshot: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, comment="账面总金额快照（DA-001 三快照之一）"
    )
    book_avg_cost_snapshot: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, comment="账面移动平均价快照（DA-001 三快照之一）"
    )
    book_last_transaction_id_snapshot: Mapped[int | None] = mapped_column(
        BigInteger(unsigned=True), nullable=True,
        comment="库存流水水印：快照时 (仓,料) 最新 InventoryTransaction.id；无流水为 NULL（CR-A-002）",
    )
    physical_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, comment="实盘数量（>= 0）"
    )
    difference_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default="0",
        comment="服务端计算 = physical - book_quantity_snapshot",
    )
    valuation_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), nullable=True, comment="盘盈入账单价（必填且 > 0，DA-002）；盘亏为 NULL"
    )
    adjustment_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, server_default="0",
        comment="带符号调整金额：盘盈 +money(diff×rate)；盘亏 -money(|diff|×avg_snapshot)",
    )
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )

    reconciliation: Mapped["StockReconciliation"] = relationship(
        back_populates="items"
    )
    material: Mapped["Material"] = relationship()  # noqa: F821
