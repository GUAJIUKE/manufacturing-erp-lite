"""Stock reconciliation endpoints (Reality Hardening Sprint 1 / Implementation A).

Approved Design v2 surface (§16 / §36 of the sprint task):

* ``GET  /stock-reconciliations``            list (reconcile:view)
* ``POST /stock-reconciliations``            create DRAFT (reconcile:create)
* ``GET  /stock-reconciliations/{id}``       detail (reconcile:view)
* ``PUT  /stock-reconciliations/{id}``       edit DRAFT (reconcile:update)
* ``POST /stock-reconciliations/{id}/submit``   DRAFT -> PENDING (reconcile:submit)
* ``POST /stock-reconciliations/{id}/approve``  PENDING -> POSTED, approve == post
* ``POST /stock-reconciliations/{id}/reject``   PENDING -> REJECTED (reconcile:reject)

Deliberately NOT in Implementation A: cancel, reverse (Implementation B),
settings/freeze and diagnostics. The route layer never touches stock — all
ledger / balance / money logic lives in the service (§20 rule).
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.v1.deps import CurrentUserDep, DbDep, require_perm
from app.core.response import ApiResponse, PageResult
from app.models import Material, StockReconciliation, StockReconciliationItem, User, Warehouse
from app.schemas.reconciliation import (
    ReconciliationApproveIn,
    ReconciliationCreate,
    ReconciliationItemOut,
    ReconciliationOut,
    ReconciliationRejectIn,
    ReconciliationSubmitIn,
    ReconciliationUpdate,
)
from app.services import stock_reconciliation_service as recon_service
from app.utils.enums import ReconciliationStatus

router = APIRouter(prefix="/stock-reconciliations", tags=["stock-reconciliations"])


def _audit_ctx(request: Request, user: CurrentUserDep) -> dict:
    return {
        "user": user,
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
        "request_id": request.headers.get("x-request-id"),
    }


def _user_name(db: Session, user_id: int | None) -> str | None:
    if user_id is None:
        return None
    u = db.get(User, user_id)
    if u is None:
        return None
    return u.real_name or u.username


def _to_item(db: Session, item: StockReconciliationItem) -> ReconciliationItemOut:
    mat = db.get(Material, item.material_id)
    return ReconciliationItemOut(
        id=item.id,
        line_no=item.line_no,
        material_id=item.material_id,
        material_code=mat.material_code if mat else None,
        material_name=mat.material_name if mat else None,
        unit=mat.unit if mat else None,
        book_quantity_snapshot=item.book_quantity_snapshot,
        book_total_amount_snapshot=item.book_total_amount_snapshot,
        book_avg_cost_snapshot=item.book_avg_cost_snapshot,
        physical_quantity=item.physical_quantity,
        difference_quantity=item.difference_quantity,
        valuation_rate=item.valuation_rate,
        adjustment_amount=item.adjustment_amount,
        remark=item.remark,
    )


def _to_out(
    db: Session,
    doc: StockReconciliation,
    *,
    with_items: bool = True,
    item_count: int | None = None,
) -> ReconciliationOut:
    wh = db.get(Warehouse, doc.warehouse_id)
    items = []
    if with_items:
        items = [_to_item(db, it) for it in sorted(doc.items, key=lambda x: x.line_no)]
    if item_count is None:
        item_count = len(items)
    return ReconciliationOut(
        id=doc.id,
        reconciliation_no=doc.reconciliation_no,
        warehouse_id=doc.warehouse_id,
        warehouse_code=wh.warehouse_code if wh else None,
        warehouse_name=wh.warehouse_name if wh else None,
        counted_by=doc.counted_by,
        counted_by_name=_user_name(db, doc.counted_by),
        counted_on=doc.counted_on,
        status=doc.status,
        reason=doc.reason,
        remark=doc.remark,
        submitted_at=doc.submitted_at,
        posted_at=doc.posted_at,
        approved_by=doc.approved_by,
        approved_by_name=_user_name(db, doc.approved_by),
        approve_comment=doc.approve_comment,
        override_self_approval=bool(doc.override_self_approval),
        override_reason=doc.override_reason,
        version=doc.version,
        item_count=item_count,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        items=items,
    )


@router.get("", summary="库存盘点列表（分页/筛选）")
def list_reconciliations(
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("reconcile:view")),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    reconciliation_no: str | None = Query(None, description="盘点单号模糊搜索"),
    warehouse_id: int | None = Query(None, description="盘点仓库"),
    status: ReconciliationStatus | None = Query(None, description="DRAFT/PENDING/POSTED/REJECTED"),
    counted_on_from: date | None = Query(None, description="盘点日期起（含）"),
    counted_on_to: date | None = Query(None, description="盘点日期止（含）"),
) -> ApiResponse[PageResult[ReconciliationOut]]:
    rows, total, counts = recon_service.list_reconciliations(
        db,
        page=page,
        page_size=page_size,
        reconciliation_no=reconciliation_no,
        warehouse_id=warehouse_id,
        status=status,
        counted_on_from=counted_on_from,
        counted_on_to=counted_on_to,
    )
    return ApiResponse.ok(
        PageResult(
            items=[
                _to_out(db, r, with_items=False, item_count=counts.get(r.id, 0)) for r in rows
            ],
            total=total,
            page=page,
            page_size=page_size,
        )
    )


@router.post("", summary="创建库存盘点（DRAFT，快照固化）")
def create_reconciliation(
    payload: ReconciliationCreate,
    request: Request,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("reconcile:create")),
) -> ApiResponse[ReconciliationOut]:
    doc = recon_service.create_reconciliation(db, payload, **_audit_ctx(request, user))
    db.commit()
    return ApiResponse.ok(_to_out(db, doc), message="盘点单已创建（草稿）")


@router.get("/{doc_id}", summary="库存盘点详情")
def get_reconciliation(
    doc_id: int,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("reconcile:view")),
) -> ApiResponse[ReconciliationOut]:
    doc = recon_service.get_reconciliation(db, doc_id)
    return ApiResponse.ok(_to_out(db, doc))


@router.put("/{doc_id}", summary="编辑盘点草稿（DRAFT，整单替换行）")
def update_reconciliation(
    doc_id: int,
    payload: ReconciliationUpdate,
    request: Request,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("reconcile:update")),
) -> ApiResponse[ReconciliationOut]:
    doc = recon_service.update_reconciliation(db, doc_id, payload, **_audit_ctx(request, user))
    db.commit()
    return ApiResponse.ok(_to_out(db, doc), message="盘点草稿已更新")


@router.post("/{doc_id}/submit", summary="提交审批（DRAFT → PENDING）")
def submit_reconciliation(
    doc_id: int,
    payload: ReconciliationSubmitIn,
    request: Request,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("reconcile:submit")),
) -> ApiResponse[ReconciliationOut]:
    doc = recon_service.submit_reconciliation(
        db, doc_id, version=payload.version, **_audit_ctx(request, user)
    )
    db.commit()
    return ApiResponse.ok(_to_out(db, doc), message="已提交审批")


@router.post("/{doc_id}/approve", summary="审批并过账（PENDING → POSTED，审批即过账）")
def approve_reconciliation(
    doc_id: int,
    payload: ReconciliationApproveIn,
    request: Request,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("reconcile:approve")),
) -> ApiResponse[ReconciliationOut]:
    doc = recon_service.approve_reconciliation(db, doc_id, payload, **_audit_ctx(request, user))
    db.commit()
    return ApiResponse.ok(_to_out(db, doc), message="已审批过账（库存已调整）")


@router.post("/{doc_id}/reject", summary="驳回（PENDING → REJECTED，意见必填）")
def reject_reconciliation(
    doc_id: int,
    payload: ReconciliationRejectIn,
    request: Request,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("reconcile:reject")),
) -> ApiResponse[ReconciliationOut]:
    doc = recon_service.reject_reconciliation(
        db, doc_id, comment=payload.comment, **_audit_ctx(request, user)
    )
    db.commit()
    return ApiResponse.ok(_to_out(db, doc), message="已驳回")
