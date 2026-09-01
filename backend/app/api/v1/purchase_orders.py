"""Purchase order endpoints (Phase 8).

Business-document surface: list / detail / create (PR -> PO conversion) /
confirm / cancel.

* No PUT/DELETE in this phase: DRAFT edits and deletions are deferred —
  confirm requires unit_price > 0, and a wrongly-created PO is cancelled
  (DRAFT/CONFIRMED -> CANCELLED), never deleted (Phase 6 §十 policy).
* No status writes in the API layer — every status change goes through the
  service's transition map (Phase 6 §十二 policy).
* Object-level checks live in the service (BUYER owns their POs,
  APPLICANT/DEPT_MANAGER only see their own PR chain); RBAC guards below
  are only the first layer (Phase 8 §四).
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.v1.deps import CurrentUserDep, DbDep, require_perm
from app.core.response import ApiResponse, PageResult
from app.models import (
    Department,
    Material,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderItemSource,
    PurchaseRequisition,
    PurchaseRequisitionItem,
    Supplier,
    User,
)
from app.schemas.purchase_order import (
    PurchaseOrderCancelIn,
    PurchaseOrderConfirmIn,
    PurchaseOrderCreate,
    PurchaseOrderItemOut,
    PurchaseOrderOut,
    PurchaseOrderSourceOut,
)
from app.services import purchase_order_service as po_service
from app.utils.enums import PoStatus

router = APIRouter(prefix="/purchase-orders", tags=["purchase-orders"])


def _audit_ctx(request: Request, user: CurrentUserDep) -> dict:
    return {
        "user": user,
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
        "request_id": request.headers.get("x-request-id"),
    }


def _source_out(db: Session, src: PurchaseOrderItemSource, poi: PurchaseOrderItem) -> PurchaseOrderSourceOut:
    pri = db.get(PurchaseRequisitionItem, src.pr_item_id)
    pr = db.get(PurchaseRequisition, pri.pr_id) if pri else None
    mat = db.get(Material, poi.material_id)
    return PurchaseOrderSourceOut(
        id=src.id,
        pr_item_id=src.pr_item_id,
        quantity=src.quantity,
        pr_no=pr.pr_no if pr else None,
        pr_item_line_no=pri.line_no if pri else None,
        material_code=mat.material_code if mat else None,
        material_name=mat.material_name if mat else None,
    )


def _to_out(db: Session, po: PurchaseOrder, *, with_items: bool = True) -> PurchaseOrderOut:
    supplier = db.get(Supplier, po.supplier_id)
    buyer = db.get(User, po.buyer_id)
    items = []
    if with_items:
        for it in po.items:
            mat = it.material
            items.append(
                PurchaseOrderItemOut(
                    id=it.id,
                    line_no=it.line_no,
                    material_id=it.material_id,
                    material_code=mat.material_code if mat else None,
                    material_name=mat.material_name if mat else None,
                    ordered_quantity=it.ordered_quantity,
                    received_quantity=it.received_quantity,
                    unit_price=it.unit_price,
                    amount=it.amount,
                    remark=it.remark,
                    sources=[_source_out(db, s, it) for s in it.sources],
                )
            )
    return PurchaseOrderOut(
        id=po.id,
        po_no=po.po_no,
        supplier_id=po.supplier_id,
        supplier_name=supplier.supplier_name if supplier else None,
        buyer_id=po.buyer_id,
        buyer_name=(buyer.real_name or buyer.username) if buyer else None,
        order_date=po.order_date,
        expected_date=po.expected_date,
        status=po.status,
        total_amount=po.total_amount,
        version=po.version,
        remark=po.remark,
        created_at=po.created_at,
        updated_at=po.updated_at,
        items=items,
    )


@router.get("", summary="采购订单列表（分页/筛选）")
def list_pos(
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("po:view")),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    po_no: str | None = Query(None, description="PO 编号模糊搜索"),
    supplier_id: int | None = Query(None, description="供应商精确筛选"),
    status: PoStatus | None = Query(None, description="订单状态"),
    order_date_from: date | None = Query(None, description="订单日期起（含）"),
    order_date_to: date | None = Query(None, description="订单日期止（含）"),
) -> ApiResponse[PageResult[PurchaseOrderOut]]:
    rows, total = po_service.list_pos(
        db,
        user=user,
        page=page,
        page_size=page_size,
        po_no=po_no,
        supplier_id=supplier_id,
        status=status,
        order_date_from=order_date_from,
        order_date_to=order_date_to,
    )
    return ApiResponse.ok(
        PageResult(
            items=[_to_out(db, po, with_items=False) for po in rows],
            total=total,
            page=page,
            page_size=page_size,
        )
    )


@router.post("", summary="创建采购订单（基于 APPROVED 的 PR 转换，自动编号 PO-YYYYMMDD-0001）")
def create_po(
    payload: PurchaseOrderCreate,
    request: Request,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("po:create")),
) -> ApiResponse[PurchaseOrderOut]:
    po = po_service.create_po(db, payload, **_audit_ctx(request, user))
    db.commit()
    return ApiResponse.ok(_to_out(db, po), message="创建成功")


@router.get("/{po_id}", summary="采购订单详情")
def get_po(
    po_id: int,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("po:view")),
) -> ApiResponse[PurchaseOrderOut]:
    po = po_service.get_po(db, po_id, user=user)
    return ApiResponse.ok(_to_out(db, po))


@router.post("/{po_id}/confirm", summary="确认采购订单（DRAFT → CONFIRMED，单价必须 > 0）")
def confirm_po(
    po_id: int,
    payload: PurchaseOrderConfirmIn,
    request: Request,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("po:confirm")),
) -> ApiResponse[PurchaseOrderOut]:
    po = po_service.confirm_po(
        db, po_id, version=payload.version, comment=payload.comment, **_audit_ctx(request, user)
    )
    db.commit()
    return ApiResponse.ok(_to_out(db, po), message="已确认")


@router.post("/{po_id}/cancel", summary="取消采购订单（DRAFT/CONFIRMED → CANCELLED，未收货方可取消）")
def cancel_po(
    po_id: int,
    payload: PurchaseOrderCancelIn,
    request: Request,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("po:cancel")),
) -> ApiResponse[PurchaseOrderOut]:
    po = po_service.cancel_po(
        db, po_id, version=payload.version, reason=payload.reason, **_audit_ctx(request, user)
    )
    db.commit()
    return ApiResponse.ok(_to_out(db, po), message="已取消")
