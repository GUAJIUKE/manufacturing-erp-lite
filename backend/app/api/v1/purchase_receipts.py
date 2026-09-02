"""Purchase receipt endpoints (Phase 9).

Deliberately minimal surface (§十七 / §二十六):

* ``GET  /purchase-receipts``            list (receipt:view)
* ``POST /purchase-receipts``            post a receipt (receipt:create)
* ``GET  /purchase-receipts/{id}``       detail (receipt:view)
* ``POST /purchase-receipts/{id}/reverse`` whole-receipt reversal (receipt:reverse)

There is **no** PUT/PATCH/DELETE: a POSTED receipt already moved stock, so
correcting a mistake is done by reversing it (red-entry principle). FastAPI
answers those verbs with 405 on its own — no route is registered.

The route layer never touches stock: quantities, balances, ledger rows, PO
status and money all belong to the service (§四十四).
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.deps import CurrentUserDep, DbDep, require_perm
from app.core.response import ApiResponse, PageResult
from app.models import (
    Material,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseReceipt,
    Supplier,
    User,
    Warehouse,
)
from app.schemas.purchase_receipt import (
    PurchaseReceiptCreate,
    PurchaseReceiptItemOut,
    PurchaseReceiptOut,
    PurchaseReceiptReverseIn,
)
from app.services import purchase_receipt_service as receipt_service
from app.utils.enums import ReceiptStatus

router = APIRouter(prefix="/purchase-receipts", tags=["purchase-receipts"])


def _audit_ctx(request: Request, user: CurrentUserDep) -> dict:
    return {
        "user": user,
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
        "request_id": request.headers.get("x-request-id"),
    }


def _to_out(db: Session, receipt: PurchaseReceipt, *, with_items: bool = True) -> PurchaseReceiptOut:
    po = db.get(PurchaseOrder, receipt.po_id)
    supplier = db.get(Supplier, po.supplier_id) if po else None
    warehouse = db.get(Warehouse, receipt.warehouse_id)
    receiver = db.get(User, receipt.received_by)
    reverser = db.get(User, receipt.reversed_by) if receipt.reversed_by else None

    items = []
    if with_items:
        for ri in sorted(receipt.items, key=lambda x: x.line_no):
            mat = db.get(Material, ri.material_id)
            poi = db.get(PurchaseOrderItem, ri.po_item_id)
            items.append(
                PurchaseReceiptItemOut(
                    id=ri.id,
                    line_no=ri.line_no,
                    po_item_id=ri.po_item_id,
                    material_id=ri.material_id,
                    material_code=mat.material_code if mat else None,
                    material_name=mat.material_name if mat else None,
                    unit=mat.unit if mat else None,
                    ordered_quantity=poi.ordered_quantity if poi else None,
                    received_quantity=ri.received_quantity,
                    unit_price=ri.unit_price,
                    amount=ri.amount,
                    remark=ri.remark,
                )
            )

    return PurchaseReceiptOut(
        id=receipt.id,
        receipt_no=receipt.receipt_no,
        po_id=receipt.po_id,
        po_no=po.po_no if po else None,
        supplier_name=supplier.supplier_name if supplier else None,
        warehouse_id=receipt.warehouse_id,
        warehouse_code=warehouse.warehouse_code if warehouse else None,
        warehouse_name=warehouse.warehouse_name if warehouse else None,
        received_by=receipt.received_by,
        received_by_name=(receiver.real_name or receiver.username) if receiver else None,
        received_at=receipt.received_at,
        status=receipt.status,
        remark=receipt.remark,
        reversed_by=receipt.reversed_by,
        reversed_by_name=(reverser.real_name or reverser.username) if reverser else None,
        reversed_at=receipt.reversed_at,
        reverse_reason=receipt.reverse_reason,
        created_at=receipt.created_at,
        updated_at=receipt.updated_at,
        items=items,
    )


@router.get("", summary="采购入库单列表（分页/筛选）")
def list_receipts(
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("receipt:view")),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    receipt_no: str | None = Query(None, description="入库单号模糊搜索"),
    po_no: str | None = Query(None, description="采购订单号模糊搜索"),
    po_id: int | None = Query(None, description="采购订单 ID 精确筛选（全链路追溯）"),
    warehouse_id: int | None = Query(None, description="收货仓库"),
    status: ReceiptStatus | None = Query(None, description="POSTED / REVERSED"),
    receipt_date_from: date | None = Query(None, description="收货日期起（含）"),
    receipt_date_to: date | None = Query(None, description="收货日期止（含）"),
) -> ApiResponse[PageResult[PurchaseReceiptOut]]:
    rows, total = receipt_service.list_receipts(
        db,
        user=user,
        page=page,
        page_size=page_size,
        receipt_no=receipt_no,
        po_no=po_no,
        po_id=po_id,
        warehouse_id=warehouse_id,
        status=status,
        receipt_date_from=receipt_date_from,
        receipt_date_to=receipt_date_to,
    )
    return ApiResponse.ok(
        PageResult(
            items=[_to_out(db, r, with_items=False) for r in rows],
            total=total,
            page=page,
            page_size=page_size,
        )
    )


@router.post("", summary="采购入库过账（创建即 POSTED，RCV-YYYYMMDD-XXXX）")
def create_receipt(
    payload: PurchaseReceiptCreate,
    request: Request,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("receipt:create")),
) -> ApiResponse[PurchaseReceiptOut]:
    receipt = receipt_service.create_receipt(db, payload, **_audit_ctx(request, user))
    db.commit()
    return ApiResponse.ok(_to_out(db, receipt), message="入库过账成功")


@router.get("/{receipt_id}", summary="采购入库单详情")
def get_receipt(
    receipt_id: int,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("receipt:view")),
) -> ApiResponse[PurchaseReceiptOut]:
    receipt = receipt_service.get_receipt(db, receipt_id, user=user)
    return ApiResponse.ok(_to_out(db, receipt))


@router.post("/{receipt_id}/reverse", summary="整单冲销（POSTED → REVERSED，原因必填）")
def reverse_receipt(
    receipt_id: int,
    payload: PurchaseReceiptReverseIn,
    request: Request,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("receipt:reverse")),
) -> ApiResponse[PurchaseReceiptOut]:
    receipt = receipt_service.reverse_receipt(
        db, receipt_id, reason=payload.reason, **_audit_ctx(request, user)
    )
    db.commit()
    return ApiResponse.ok(_to_out(db, receipt), message="已冲销")
