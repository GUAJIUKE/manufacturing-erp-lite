"""Purchase requisition schemas (Phase 6).

Client-trusted fields vs server-owned fields:

* ``pr_no / applicant_id / department_id / status / converted_quantity /
  estimated_amount / total_estimated_amount`` are ALWAYS server-owned —
  they never appear in create/update payloads (Phase 6 §五).
* ``apply_date`` is client-optional (defaults to today) and doubles as the
  business date that drives the PR-YYYYMMDD-#### sequence day counter.
* ``version`` is required on update (optimistic lock, Phase 6 §十一).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.utils.enums import ApprovalAction, DocumentType, PrStatus


class PurchaseRequisitionItemCreate(BaseModel):
    material_id: int = Field(gt=0, description="物料 ID（必须存在且 ACTIVE）")
    requested_quantity: Decimal = Field(gt=0, decimal_places=4, description="申请数量（>0）")
    estimated_unit_price: Decimal = Field(
        ge=0, decimal_places=4, description="预估单价（>=0，允许为 0）"
    )
    required_date: date | None = Field(default=None, description="需求日期（可空）")
    remark: str | None = Field(default=None, max_length=255)

    # converted_quantity / estimated_amount 均服务端控制，客户端不可传。


class PurchaseRequisitionCreate(BaseModel):
    """Create requires at least one item (Phase 6 §五.3, preferred)."""

    apply_date: date | None = Field(
        default=None, description="申请日期，默认今天；同时作为 PR 编号按日取号基准"
    )
    reason: str | None = Field(default=None, max_length=500, description="申请事由")
    items: list[PurchaseRequisitionItemCreate] = Field(
        min_length=1, description="至少 1 条明细（首个业务单据不允许空单创建）"
    )


class PurchaseRequisitionItemUpdate(BaseModel):
    """``id`` present → update existing line; absent → append new line.

    Existing lines not referenced by the payload are deleted. All in one
    transaction (Phase 6 §六 / §七).
    """

    id: int | None = Field(default=None, description="明细 ID（稳定标识，更新时用于定位）")
    material_id: int = Field(gt=0)
    requested_quantity: Decimal = Field(gt=0, decimal_places=4)
    estimated_unit_price: Decimal = Field(ge=0, decimal_places=4)
    required_date: date | None = None
    remark: str | None = Field(default=None, max_length=255)


class PurchaseRequisitionUpdate(BaseModel):
    """Header + items replaced together; ``version`` is mandatory (乐观锁)."""

    version: int = Field(ge=1, description="当前版本号（并发控制，服务端校验后递增）")
    apply_date: date | None = Field(default=None, description="不传则保持原值")
    reason: str | None = Field(default=None, max_length=500, description="不传则保持原值")
    items: list[PurchaseRequisitionItemUpdate] = Field(min_length=1)


class PurchaseRequisitionItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    line_no: int
    material_id: int
    material_code: str | None = None
    material_name: str | None = None
    requested_quantity: Decimal
    converted_quantity: Decimal
    estimated_unit_price: Decimal
    estimated_amount: Decimal
    required_date: date | None = None
    remark: str | None = None


class PurchaseRequisitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pr_no: str
    applicant_id: int
    applicant_name: str | None = None
    department_id: int
    department_name: str | None = None
    apply_date: date
    reason: str | None = None
    status: PrStatus
    total_estimated_amount: Decimal
    submitted_at: datetime | None = None
    version: int
    remark: str | None = None
    created_at: datetime
    updated_at: datetime
    items: list[PurchaseRequisitionItemOut] = []


# ----------------------------------------------------------------------
# Phase 7: approval workflow
# ----------------------------------------------------------------------
class PurchaseRequisitionApproveIn(BaseModel):
    """审批通过：version 必填（乐观锁），comment 可选。"""

    version: int = Field(ge=1, description="当前版本号（并发控制）")
    comment: str | None = Field(default=None, max_length=1000, description="审批意见（通过时可选）")


class PurchaseRequisitionRejectIn(BaseModel):
    """驳回：comment 必填，trim 后不能为空（Phase 7 §九 / §十六）。"""

    version: int = Field(ge=1, description="当前版本号（并发控制）")
    comment: str = Field(max_length=1000, description="驳回原因（必填）")

    @field_validator("comment")
    @classmethod
    def _comment_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("驳回原因不能为空")
        return v


class PurchaseRequisitionReviseIn(BaseModel):
    """被驳回后重新编辑（REJECTED -> DRAFT）：仅 version 必填。"""

    version: int = Field(ge=1, description="当前版本号（并发控制）")


class ApprovalRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_type: DocumentType
    document_no: str | None = None
    step_name: str | None = None
    approver_id: int
    approver_name: str | None = None
    action: ApprovalAction
    from_status: str | None = None
    to_status: str | None = None
    comment: str | None = None
    created_at: datetime
