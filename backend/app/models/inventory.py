"""Inventory domain models: receipts, balances, transactions.

Maps 1:1 to docs/database-design.md §5.1 - §5.4.
``inventory_transactions`` is an append-only ledger (enforced by MySQL
triggers created in the Alembic migration, not by the ORM).
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
from sqlalchemy.dialects.mysql import BIGINT as BigInteger, DATETIME, INTEGER

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import PKMixin, TimestampMixin
from app.utils.enums import ReceiptStatus, TxnSourceType, TxnType


class PurchaseReceipt(PKMixin, TimestampMixin, Base):
    """采购入库单头（§5.1，Q6）

    第一阶段无 DRAFT：事务内创建即 POSTED（实物操作不可逆）。
    """

    __tablename__ = "purchase_receipts"
    __table_args__ = (
        UniqueConstraint("receipt_no", name="uk_receipt_no"),
        Index("ix_receipt_po", "po_id"),
        Index("ix_receipt_wh", "warehouse_id"),
        Index("ix_receipt_status", "status"),
    )

    receipt_no: Mapped[str] = mapped_column(String(32), nullable=False, comment="RCV-20260901-0001")
    po_id: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("purchase_orders.id", name="fk_receipt_po", ondelete="RESTRICT"),
        nullable=False,
    )
    warehouse_id: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("warehouses.id", name="fk_receipt_wh", ondelete="RESTRICT"),
        nullable=False,
    )
    received_by: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("users.id", name="fk_receipt_user", ondelete="RESTRICT"),
        nullable=False,
        comment="收货人",
    )
    received_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, comment="收货时间")
    status: Mapped[ReceiptStatus] = mapped_column(
        SAEnum(ReceiptStatus, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        server_default=ReceiptStatus.POSTED.value,
    )
    reversed_by: Mapped[int | None] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("users.id", name="fk_receipt_reversed_by_users"),
        nullable=True,
        comment="冲销人",
    )
    reversed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True, comment="冲销时间")
    reverse_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True, comment="冲销原因（必填）")
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)

    items: Mapped[list["PurchaseReceiptItem"]] = relationship(
        back_populates="receipt",
        cascade="all, delete-orphan",
        order_by="PurchaseReceiptItem.line_no",
        passive_deletes=True,
    )
    po: Mapped["PurchaseOrder"] = relationship()


class PurchaseReceiptItem(PKMixin, Base):
    """采购入库明细（§5.2）

    unit_price 是成本单价快照（取自 PO 明细），库存成本金额固化在入库时点。
    """

    __tablename__ = "purchase_receipt_items"
    __table_args__ = (
        UniqueConstraint("receipt_id", "line_no", name="uk_ri_line"),
        UniqueConstraint("receipt_id", "po_item_id", name="uk_ri_poi"),
        Index("ix_ri_poi", "po_item_id"),
        Index("ix_ri_mat", "material_id"),
        CheckConstraint("received_quantity > 0", name="ri_qty_positive"),
        CheckConstraint("unit_price >= 0", name="ri_price_nonneg"),
    )

    receipt_id: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("purchase_receipts.id", name="fk_ri_receipt", ondelete="CASCADE"),
        nullable=False,
    )
    po_item_id: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("purchase_order_items.id", name="fk_ri_poi", ondelete="RESTRICT"),
        nullable=False,
    )
    line_no: Mapped[int] = mapped_column(nullable=False, comment="行号")
    material_id: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("materials.id", name="fk_ri_mat", ondelete="RESTRICT"),
        nullable=False,
        comment="物料（冗余自 PO 明细，便于库存记账）",
    )
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, comment="本次入库数量")
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, comment="成本单价快照（取自 po_item.unit_price）"
    )
    # 与 PO 明细 amount 同策略（Phase 8 §一）：生成列改为服务端计算列，
    # 金额精度统一 2 位 ROUND_HALF_UP（money.line_amount），DB 不做隐式舍入。
    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        server_default="0",
        comment="入库金额（服务端计算：ROUND_HALF_UP(received_quantity × unit_price, 2)，非生成列）",
    )
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )

    receipt: Mapped["PurchaseReceipt"] = relationship(back_populates="items")
    po_item: Mapped["PurchaseOrderItem"] = relationship()


class InventoryBalance(PKMixin, TimestampMixin, Base):
    """库存余额（§5.3，Q7 移动加权平均 / Q8 禁止负库存）

    余额行首次入库时通过 INSERT ... ON DUPLICATE KEY UPDATE 创建。
    ``version`` 乐观锁版本号用于并发控制。
    """

    __tablename__ = "inventory_balances"
    __table_args__ = (
        UniqueConstraint("warehouse_id", "material_id", name="uk_ib"),
        Index("ix_ib_mat", "material_id"),
        CheckConstraint("quantity >= 0", name="ib_qty_nonneg"),
        CheckConstraint("total_amount >= 0", name="ib_amount_nonneg"),
        CheckConstraint("average_unit_cost >= 0", name="ib_avg_nonneg"),
    )

    warehouse_id: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("warehouses.id", name="fk_ib_wh", ondelete="RESTRICT"),
        nullable=False,
    )
    material_id: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("materials.id", name="fk_ib_mat", ondelete="RESTRICT"),
        nullable=False,
    )
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default="0", comment="账面数量（>= 0，Q8）"
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, server_default="0", comment="账面总金额（权威值，ROUND_HALF_UP 2 位）"
    )
    average_unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default="0", comment="移动加权平均单价"
    )
    version: Mapped[int] = mapped_column(
        INTEGER(unsigned=True), nullable=False, server_default="0", comment="乐观锁版本号"
    )
    last_transaction_at: Mapped[datetime | None] = mapped_column(
        DATETIME(fsp=3), nullable=True, comment="最近变动时间"
    )

    warehouse: Mapped["Warehouse"] = relationship()
    material: Mapped["Material"] = relationship()


class InventoryTransaction(PKMixin, Base):
    """库存流水（§5.4，append-only ledger，架构规则 3）

    - quantity 带符号：入库为正、出库为负；CHECK 强制类型与符号一致
    - amount 与 quantity 同符号（Review Fix §1）：PURCHASE_IN 的
      quantity/amount 均 > 0，PURCHASE_IN_REVERSAL 均 < 0 —— 因此
      SUM(quantity) == balance.quantity 且 SUM(amount) == balance.total_amount
    - unit_cost 恒 >= 0（成本单价不是带符号量）
    - 创建后禁止 UPDATE / DELETE（MySQL 触发器强制，迁移中创建）
    - 错误通过反向流水（PURCHASE_IN_REVERSAL）纠正，原始记录保留
    """

    __tablename__ = "inventory_transactions"
    __table_args__ = (
        UniqueConstraint("txn_no", name="uk_txn_no"),
        Index("ix_it_wh_mat", "warehouse_id", "material_id"),
        Index("ix_it_mat", "material_id"),
        Index("ix_it_source", "source_type", "source_id"),
        Index("ix_it_type", "transaction_type"),
        Index("ix_it_time", "transaction_at"),
        Index("ix_it_reversed", "reversed_transaction_id"),
        # amount 与 quantity 同号：入库正、出库/冲销负（含 0 边界，杜绝
        # 极小 qty×unit_cost 舍入为 0.00 的合法行被误拒 —— 业务上正常
        # 入库 amount 必为正、冲销必为负，见 Review Fix §1 文档）
        CheckConstraint(
            "(transaction_type IN ('PURCHASE_IN','ADJUST_IN','PRODUCTION_IN')"
            " AND quantity > 0 AND amount >= 0)"
            " OR (transaction_type IN ('PURCHASE_IN_REVERSAL','ADJUST_OUT','PRODUCTION_OUT')"
            " AND quantity < 0 AND amount <= 0)",
            name="it_sign",
        ),
        CheckConstraint("unit_cost >= 0", name="it_cost_nonneg"),
    )

    txn_no: Mapped[str] = mapped_column(String(32), nullable=False, comment="TXN-20260901-000001")
    transaction_type: Mapped[TxnType] = mapped_column(
        SAEnum(TxnType, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    warehouse_id: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("warehouses.id", name="fk_it_wh", ondelete="RESTRICT"),
        nullable=False,
    )
    material_id: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("materials.id", name="fk_it_mat", ondelete="RESTRICT"),
        nullable=False,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, comment="带符号：入库正、出库负")
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default="0", comment="计价单价")
    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, server_default="0", comment="计价金额（quantity × unit_cost 带符号，ROUND_HALF_UP 2 位）"
    )
    balance_after: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, comment="流水后余额快照，审计用"
    )
    source_type: Mapped[TxnSourceType | None] = mapped_column(
        SAEnum(TxnSourceType, values_callable=lambda e: [m.value for m in e]),
        nullable=True,
        comment="来源单据类型",
    )
    source_id: Mapped[int | None] = mapped_column(
        BigInteger(unsigned=True), nullable=True, comment="来源单据 ID（非 FK）"
    )
    source_item_id: Mapped[int | None] = mapped_column(
        BigInteger(unsigned=True), nullable=True, comment="来源单据明细 ID"
    )
    reversed_transaction_id: Mapped[int | None] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("inventory_transactions.id", name="fk_it_reversed"),
        nullable=True,
        comment="Q6：指向被冲销的原始流水",
    )
    transaction_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, comment="业务发生时间")
    remark: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("users.id", name="fk_it_created_by_users"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )
