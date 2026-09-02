"""Purchase receipt schemas (Phase 9).

Client-trusted vs server-owned fields (Phase 6 §五 policy, inherited):

* client sends only: ``po_id``, ``warehouse_id``, optional ``receipt_date``,
  ``remark`` and per-line ``po_item_id`` + ``received_quantity``;
* server decides: ``receipt_no`` (RCV-YYYYMMDD-XXXX), ``received_by``
  (current user — never the client), ``status`` (POSTED/REVERSED), per-line
  ``material_id`` (derived from the PO line), ``unit_price`` (snapshot of
  ``po_item.unit_price``, §十三) and ``amount`` (server-computed, §十三).

No update/delete schema exists: a POSTED receipt has already moved stock, so
the only way to correct it is :class:`PurchaseReceiptReverseIn` (§十七).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.utils.enums import ReceiptStatus


class PurchaseReceiptItemCreate(BaseModel):
    """入库明细：只给 PO 明细与本次实收数量，其余服务端推导。"""

    po_item_id: int = Field(gt=0, description="采购订单明细 ID（必须属于指定 PO）")
    received_quantity: Decimal = Field(
        gt=0, decimal_places=4, description="本次入库数量（>0，且不超过该 PO 明细剩余可收数量）"
    )
    remark: str | None = Field(default=None, max_length=255)


class PurchaseReceiptCreate(BaseModel):
    """创建入库单（创建即 POSTED，无 DRAFT，§六）。"""

    po_id: int = Field(gt=0, description="采购订单 ID（必须 CONFIRMED 或 PARTIALLY_RECEIVED）")
    warehouse_id: int = Field(gt=0, description="收货仓库 ID（必须存在且 ACTIVE）")
    receipt_date: date | None = Field(default=None, description="业务收货日期，默认今天")
    remark: str | None = Field(default=None, max_length=255)
    items: list[PurchaseReceiptItemCreate] = Field(min_length=1, description="至少 1 条明细")


class PurchaseReceiptReverseIn(BaseModel):
    """整单冲销（§十八）：reason 必填、trim 后非空、<=1000。"""

    reason: str = Field(max_length=1000, description="冲销原因（必填）")

    @field_validator("reason")
    @classmethod
    def _strip(cls, v: str) -> str:
        value = (v or "").strip()
        if not value:
            raise ValueError("冲销原因不能为空")
        return value


class PurchaseReceiptItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    line_no: int
    po_item_id: int
    material_id: int
    material_code: str | None = None
    material_name: str | None = None
    unit: str | None = None
    ordered_quantity: Decimal | None = None
    received_quantity: Decimal
    unit_price: Decimal
    amount: Decimal
    remark: str | None = None


class PurchaseReceiptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    receipt_no: str
    po_id: int
    po_no: str | None = None
    supplier_name: str | None = None
    warehouse_id: int
    warehouse_code: str | None = None
    warehouse_name: str | None = None
    received_by: int
    received_by_name: str | None = None
    received_at: datetime
    status: ReceiptStatus
    remark: str | None = None
    reversed_by: int | None = None
    reversed_by_name: str | None = None
    reversed_at: datetime | None = None
    reverse_reason: str | None = None
    created_at: datetime
    updated_at: datetime
    items: list[PurchaseReceiptItemOut] = []
