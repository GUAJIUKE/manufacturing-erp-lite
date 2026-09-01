"""Purchase domain models: PR, PO, PO-PR source mapping, approval records.

Maps 1:1 to docs/database-design.md §4.1 - §4.5 and §6.1.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Numeric,

    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mysql import BIGINT as BigInteger, DATETIME, SMALLINT

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import PKMixin, TimestampMixin
from app.utils.enums import ApprovalAction, DocumentType, PrStatus, PoStatus


class PurchaseRequisition(PKMixin, TimestampMixin, Base):
    """采购申请单头（§4.1）"""

    __tablename__ = "purchase_requisitions"
    __table_args__ = (
        UniqueConstraint("pr_no", name="uk_pr_no"),
        Index("ix_pr_status", "status"),
        Index("ix_pr_applicant", "applicant_id"),
        Index("ix_pr_dept", "department_id"),
        Index("ix_pr_date", "apply_date"),
        # Phase 7 审批中心高频查询（department_id + status=PENDING）：联合索引
        # 优于两个单列各自扫描 + index merge（Phase 7 §二十二）。
        Index("ix_pr_dept_status", "department_id", "status"),
    )

    pr_no: Mapped[str] = mapped_column(String(32), nullable=False, comment="PR-20260901-0001")
    applicant_id: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("users.id", name="fk_pr_applicant", ondelete="RESTRICT"),
        nullable=False,
    )
    department_id: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("departments.id", name="fk_pr_dept", ondelete="RESTRICT"),
        nullable=False,
        comment="申请部门（单据快照，不随调岗漂移）",
    )
    apply_date: Mapped[date] = mapped_column(Date, nullable=False, comment="申请日期")
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="申请事由")
    status: Mapped[PrStatus] = mapped_column(
        SAEnum(PrStatus, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        server_default=PrStatus.DRAFT.value,
    )
    total_estimated_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, server_default="0", comment="明细预估金额合计（服务端汇总，ROUND_HALF_UP）"
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DATETIME(fsp=3), nullable=True, comment="提交时间（UTC，submit 时写入）"
    )
    version: Mapped[int] = mapped_column(
        nullable=False, server_default="1", comment="乐观锁版本号（更新/提交/取消时递增）"
    )
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("users.id", name="fk_pr_created_by_users"),
        nullable=True,
    )
    updated_by: Mapped[int | None] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("users.id", name="fk_pr_updated_by_users"),
        nullable=True,
    )

    items: Mapped[list["PurchaseRequisitionItem"]] = relationship(
        back_populates="requisition",
        cascade="all, delete-orphan",
        order_by="PurchaseRequisitionItem.line_no",
        passive_deletes=True,
    )
    approvals: Mapped[list["ApprovalRecord"]] = relationship(
        primaryjoin="and_(ApprovalRecord.document_type=='PURCHASE_REQUISITION', "
        "ApprovalRecord.document_id==PurchaseRequisition.id)",
        viewonly=True,
        foreign_keys="[ApprovalRecord.document_id]",
    )


class PurchaseRequisitionItem(PKMixin, TimestampMixin, Base):
    """采购申请明细（§4.2，Q3 拆单核心）"""

    __tablename__ = "purchase_requisition_items"
    __table_args__ = (
        UniqueConstraint("pr_id", "line_no", name="uk_pri_line"),
        Index("ix_pri_mat", "material_id"),
        Index("ix_pri_pr", "pr_id"),
        CheckConstraint("requested_quantity > 0", name="pri_qty_positive"),
        CheckConstraint("estimated_unit_price >= 0", name="pri_price_nonneg"),
        CheckConstraint(
            "converted_quantity >= 0 AND converted_quantity <= requested_quantity",
            name="pri_converted_not_exceed",
        ),
    )

    pr_id: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("purchase_requisitions.id", name="fk_pri_pr", ondelete="CASCADE"),
        nullable=False,
    )
    line_no: Mapped[int] = mapped_column(nullable=False, comment="行号，单内唯一")
    material_id: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("materials.id", name="fk_pri_mat", ondelete="RESTRICT"),
        nullable=False,
    )
    requested_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, comment="申请数量")
    converted_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default="0", comment="已转 PO 数量（Q3）"
    )
    estimated_unit_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default="0", comment="预估单价，允许为 0（Q9）"
    )
    estimated_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        server_default="0",
        comment="预估金额（服务端计算：ROUND_HALF_UP(qty × price, 2)，非生成列）",
    )
    required_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="需求日期")
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)

    requisition: Mapped["PurchaseRequisition"] = relationship(back_populates="items")
    material: Mapped["Material"] = relationship()


class PurchaseOrder(PKMixin, TimestampMixin, Base):
    """采购订单单头（§4.3）"""

    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint("po_no", name="uk_po_no"),
        Index("ix_po_supplier", "supplier_id"),
        Index("ix_po_buyer", "buyer_id"),
        Index("ix_po_status", "status"),
        Index("ix_po_date", "order_date"),
    )

    po_no: Mapped[str] = mapped_column(String(32), nullable=False, comment="PO-20260901-0001")
    supplier_id: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("suppliers.id", name="fk_po_supplier", ondelete="RESTRICT"),
        nullable=False,
        comment="供应商（必填）",
    )
    buyer_id: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("users.id", name="fk_po_buyer", ondelete="RESTRICT"),
        nullable=False,
        comment="采购员",
    )
    order_date: Mapped[date] = mapped_column(Date, nullable=False, comment="订单日期")
    expected_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="期望到货日期")
    status: Mapped[PoStatus] = mapped_column(
        SAEnum(PoStatus, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        server_default=PoStatus.DRAFT.value,
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default="0", comment="明细金额合计（服务端汇总）"
    )
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("users.id", name="fk_po_created_by_users"),
        nullable=True,
    )
    updated_by: Mapped[int | None] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("users.id", name="fk_po_updated_by_users"),
        nullable=True,
    )

    items: Mapped[list["PurchaseOrderItem"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="PurchaseOrderItem.line_no",
        passive_deletes=True,
    )
    supplier: Mapped["Supplier"] = relationship()
    buyer: Mapped["User"] = relationship(foreign_keys="PurchaseOrder.buyer_id")


class PurchaseOrderItem(PKMixin, TimestampMixin, Base):
    """采购订单明细（§4.4，Q5 超收防护）"""

    __tablename__ = "purchase_order_items"
    __table_args__ = (
        UniqueConstraint("po_id", "line_no", name="uk_poi_line"),
        Index("ix_poi_mat", "material_id"),
        Index("ix_poi_po", "po_id"),
        CheckConstraint("ordered_quantity > 0", name="poi_ordered_positive"),
        CheckConstraint(
            "received_quantity >= 0 AND received_quantity <= ordered_quantity",
            name="poi_received_not_exceed",
        ),
        CheckConstraint("unit_price >= 0", name="poi_price_nonneg"),
    )

    po_id: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("purchase_orders.id", name="fk_poi_po", ondelete="CASCADE"),
        nullable=False,
    )
    line_no: Mapped[int] = mapped_column(nullable=False, comment="行号")
    material_id: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("materials.id", name="fk_poi_mat", ondelete="RESTRICT"),
        nullable=False,
    )
    ordered_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, comment="采购数量")
    received_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default="0", comment="累计已收数量"
    )
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default="0", comment="采购单价（confirm 时强制 > 0）"
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        Computed("ROUND(ordered_quantity * unit_price, 4)", persisted=True),
        nullable=False,
        comment="金额（生成列）",
    )
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)

    order: Mapped["PurchaseOrder"] = relationship(back_populates="items")
    material: Mapped["Material"] = relationship()
    sources: Mapped[list["PurchaseOrderItemSource"]] = relationship(
        back_populates="po_item",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class PurchaseOrderItemSource(PKMixin, Base):
    """PO 明细 ↔ PR 明细来源映射（§4.5，Q4）

    一个 PO Item 可合并多个 PR Item；一个 PR Item 可拆给多个 PO Item。
    UNIQUE(po_item_id, pr_item_id) 防止同一来源重复累加绕过校验。
    """

    __tablename__ = "purchase_order_item_sources"
    __table_args__ = (
        UniqueConstraint("po_item_id", "pr_item_id", name="uk_pois"),
        Index("ix_pois_pri", "pr_item_id"),
        CheckConstraint("quantity > 0", name="pois_qty_positive"),
    )

    po_item_id: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("purchase_order_items.id", name="fk_pois_poi", ondelete="CASCADE"),
        nullable=False,
    )
    pr_item_id: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("purchase_requisition_items.id", name="fk_pois_pri", ondelete="RESTRICT"),
        nullable=False,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, comment="从该 PR 明细转出的数量")
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )

    po_item: Mapped["PurchaseOrderItem"] = relationship(back_populates="sources")
    pr_item: Mapped["PurchaseRequisitionItem"] = relationship()


class ApprovalRecord(PKMixin, Base):
    """审批记录（§6.1，Q11 单级审批）

    同一 step_no 同一 action 允许出现多条：REJECTED → DRAFT → 重新提交 → 再次审批
    是正确的历史轨迹（Q1），故不加唯一约束。
    """

    __tablename__ = "approval_records"
    __table_args__ = (
        Index("ix_ar_doc", "document_type", "document_id"),
        Index("ix_ar_approver", "approver_id"),
        Index("ix_ar_time", "created_at"),
    )

    document_type: Mapped[DocumentType] = mapped_column(
        SAEnum(DocumentType, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    document_id: Mapped[int] = mapped_column(BigInteger(unsigned=True), nullable=False, comment="单据 ID（非 FK）")
    document_no: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="单据编号冗余（如 PR-20260901-0001），便于审计查询（Phase 7 §三）"
    )
    step_no: Mapped[int] = mapped_column(
        SMALLINT(unsigned=True), nullable=False, server_default="1", comment="审批级别，v1 恒为 1"
    )
    step_name: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="步骤名，如 部门主管审批")
    approver_id: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("users.id", name="fk_ar_approver", ondelete="RESTRICT"),
        nullable=False,
    )
    action: Mapped[ApprovalAction] = mapped_column(
        SAEnum(ApprovalAction, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    from_status: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="审批动作前状态（Phase 7 §三）"
    )
    to_status: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="审批动作后状态（Phase 7 §三）"
    )
    result_status: Mapped[str] = mapped_column(String(32), nullable=False, comment="动作执行后单据状态快照（与 to_status 同步）")
    comment: Mapped[str | None] = mapped_column(String(1000), nullable=True, comment="审批意见，驳回时必填")
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )
