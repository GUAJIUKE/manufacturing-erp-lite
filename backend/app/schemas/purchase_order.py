"""Purchase order schemas (Phase 8).

Client-trusted fields vs server-owned fields:

* ``po_no / buyer_id / status / received_quantity / amount /
  total_amount / version`` are ALWAYS server-owned — they never appear in
  create payloads (Phase 6 §五 policy, inherited by PO).
* ``unit_price`` may be 0 while DRAFT (pricing TBD) but must be > 0 at
  confirm time (Q9, ``PO_UNIT_PRICE_REQUIRED``).
* ``sources`` map PO items back to PR items (§4.5). Empty sources are
  legal (purchasing beyond PR demand, e.g. MOQ) and should be explained in
  the item remark (§4.5 constraint 2).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.utils.enums import PoStatus


class PurchaseOrderSourceCreate(BaseModel):
    """PO 明细 ↔ PR 明细来源（§4.5）：pr_item_id + 转出数量。"""

    pr_item_id: int = Field(gt=0, description="PR 明细 ID（必须属于 APPROVED 的 PR）")
    quantity: Decimal = Field(gt=0, decimal_places=4, description="从该 PR 明细转出的数量（>0）")


class PurchaseOrderItemCreate(BaseModel):
    material_id: int = Field(gt=0, description="物料 ID（必须存在且 ACTIVE）")
    ordered_quantity: Decimal = Field(gt=0, decimal_places=4, description="采购数量（>0）")
    unit_price: Decimal = Field(
        ge=0, decimal_places=4, description="采购单价（>=0；DRAFT 可暂存 0，confirm 时强制 >0，Q9）"
    )
    remark: str | None = Field(default=None, max_length=255)
    sources: list[PurchaseOrderSourceCreate] = Field(
        default_factory=list, description="PR 来源映射；可空（无来源采购需在 remark 说明）"
    )


class PurchaseOrderCreate(BaseModel):
    """创建 PO（DRAFT，R4/R5/R12）：至少一条明细，来源可空。"""

    supplier_id: int = Field(gt=0, description="供应商 ID（必须存在且 ACTIVE，R5）")
    order_date: date | None = Field(
        default=None, description="订单日期，默认今天；同时作为 PO 编号按日取号基准"
    )
    expected_date: date | None = Field(default=None, description="期望到货日期")
    remark: str | None = Field(default=None, max_length=255)
    items: list[PurchaseOrderItemCreate] = Field(min_length=1, description="至少 1 条明细（R12）")


class PurchaseOrderConfirmIn(BaseModel):
    """确认订单（DRAFT → CONFIRMED）：version 必填（乐观锁）。"""

    version: int = Field(ge=1, description="当前版本号（并发控制）")
    comment: str | None = Field(default=None, max_length=500, description="确认备注（可选）")


class PurchaseOrderCancelIn(BaseModel):
    """取消订单（DRAFT/CONFIRMED → CANCELLED）：version 必填（乐观锁）。"""

    version: int = Field(ge=1, description="当前版本号（并发控制）")
    reason: str | None = Field(default=None, max_length=500, description="取消原因（可选）")


class PurchaseOrderSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pr_item_id: int
    quantity: Decimal
    pr_no: str | None = None  # 冗余展示：来源 PR 编号
    pr_item_line_no: int | None = None
    material_code: str | None = None
    material_name: str | None = None


class PurchaseOrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    line_no: int
    material_id: int
    material_code: str | None = None
    material_name: str | None = None
    ordered_quantity: Decimal
    received_quantity: Decimal
    unit_price: Decimal
    amount: Decimal
    remark: str | None = None
    sources: list[PurchaseOrderSourceOut] = []


class PurchaseOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    po_no: str
    supplier_id: int
    supplier_name: str | None = None
    buyer_id: int
    buyer_name: str | None = None
    order_date: date
    expected_date: date | None = None
    status: PoStatus
    total_amount: Decimal
    version: int
    remark: str | None = None
    created_at: datetime
    updated_at: datetime
    items: list[PurchaseOrderItemOut] = []
