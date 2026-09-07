"""Stock reconciliation schemas (Reality Hardening Sprint 1 / Implementation A).

Client-trusted vs server-owned fields (project policy, inherited from Phase 6):

* client sends only: ``warehouse_id``, header ``reason/remark`` and per-line
  ``material_id`` + ``physical_quantity`` (+ optional ``valuation_rate`` /
  ``remark``). ``version`` is echoed back for optimistic locking on PUT.
* server decides: ``reconciliation_no`` (CNT-YYYYMMDD-XXXX), ``counted_by``
  (current user), ``counted_on`` (server today, RD-001), ``status``, the three
  book snapshots, ``difference_quantity`` and ``adjustment_amount`` (all
  Decimal, computed server-side — the frontend's difference is preview only).

The approve (post) payload carries the SoD override fields. There is no
cancel / reverse schema in Implementation A (deferred to B).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.utils.enums import ReconciliationStatus


class ReconciliationItemLine(BaseModel):
    """盘点行输入：只给物料与实盘数，其余服务端推导。"""

    material_id: int = Field(gt=0, description="被盘物料 ID（同一单内不可重复）")
    physical_quantity: Decimal = Field(
        ge=0, decimal_places=4, description="实盘数量（>= 0；禁止负数）"
    )
    valuation_rate: Decimal | None = Field(
        default=None,
        ge=0,
        description="盘盈入账单价：diff>0 时必填且 > 0（后端校验，DA-002）；盘亏行留空",
    )
    remark: str | None = Field(default=None, max_length=255)


class ReconciliationCreate(BaseModel):
    """创建盘点单（DRAFT，服务端固化三快照）。"""

    warehouse_id: int = Field(gt=0, description="盘点仓库 ID（必须存在且 ACTIVE）")
    reason: str | None = Field(default=None, max_length=500)
    remark: str | None = Field(default=None, max_length=255)
    items: list[ReconciliationItemLine] = Field(min_length=1, description="至少 1 条明细")


class ReconciliationUpdate(BaseModel):
    """编辑 DRAFT：整单替换行集合（保留旧行快照、新行取新快照）。"""

    version: int = Field(ge=1, description="乐观锁版本号（来自详情）")
    reason: str | None = Field(default=None, max_length=500)
    remark: str | None = Field(default=None, max_length=255)
    items: list[ReconciliationItemLine] = Field(min_length=1, description="替换后的行集合")


class ReconciliationSubmitIn(BaseModel):
    """提交审批（DRAFT -> PENDING）。"""

    version: int = Field(ge=1, description="乐观锁版本号")


class ReconciliationApproveIn(BaseModel):
    """审批并过账（PENDING -> POSTED，审批即过账，Design v2 §4.2）。

    ``override_self_approval`` 仅在盘点人 = 审批人（SoD）时生效，且必须携带
    ``override_reason``（RD-006）。
    """

    approve_comment: str | None = Field(default=None, max_length=1000)
    override_self_approval: bool = False
    override_reason: str | None = Field(default=None, max_length=500)

    @field_validator("override_reason")
    @classmethod
    def _strip_override_reason(cls, v: str | None) -> str | None:
        if v is None:
            return None
        value = v.strip()
        return value or None


class ReconciliationRejectIn(BaseModel):
    """驳回（PENDING -> REJECTED），意见必填。"""

    comment: str = Field(max_length=1000, description="驳回意见（必填）")

    @field_validator("comment")
    @classmethod
    def _strip(cls, v: str) -> str:
        value = (v or "").strip()
        if not value:
            raise ValueError("驳回意见不能为空")
        return value


class ReconciliationItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    line_no: int
    material_id: int
    material_code: str | None = None
    material_name: str | None = None
    unit: str | None = None
    book_quantity_snapshot: Decimal
    book_total_amount_snapshot: Decimal
    book_avg_cost_snapshot: Decimal
    physical_quantity: Decimal
    difference_quantity: Decimal
    valuation_rate: Decimal | None = None
    adjustment_amount: Decimal
    remark: str | None = None


class ReconciliationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reconciliation_no: str
    warehouse_id: int
    warehouse_code: str | None = None
    warehouse_name: str | None = None
    counted_by: int
    counted_by_name: str | None = None
    counted_on: date
    status: ReconciliationStatus
    reason: str | None = None
    remark: str | None = None
    submitted_at: datetime | None = None
    posted_at: datetime | None = None
    approved_by: int | None = None
    approved_by_name: str | None = None
    approve_comment: str | None = None
    override_self_approval: bool = False
    override_reason: str | None = None
    version: int
    item_count: int = 0
    created_at: datetime
    updated_at: datetime
    items: list[ReconciliationItemOut] = []
