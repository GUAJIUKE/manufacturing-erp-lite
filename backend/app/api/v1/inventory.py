"""Inventory query endpoints (Phase 9).

Read-only by construction:

* ``GET /inventory/balances``     current snapshot + safety-stock policy
* ``GET /inventory/transactions`` append-only ledger

No write endpoint exists for either resource. The balance is a derived
cache, and the ledger is immutable — stock only changes as a side effect of
a business document (here: a purchase receipt or a reversal), always
through the service layer (§四十四).
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.v1.deps import CurrentUserDep, DbDep, require_perm
from app.core.response import ApiResponse, PageResult
from app.models import InventoryTransaction, PurchaseReceipt, User, Warehouse, Material
from app.schemas.inventory import BalanceRow, TransactionOut
from app.services import inventory_service
from app.utils.enums import TxnSourceType, TxnType

router = APIRouter(prefix="/inventory", tags=["inventory"])


def _txn_out(db, txn: InventoryTransaction, receipt_no: str | None) -> TransactionOut:
    warehouse = db.get(Warehouse, txn.warehouse_id)
    material = db.get(Material, txn.material_id)
    operator = db.get(User, txn.created_by) if txn.created_by else None
    return TransactionOut(
        id=txn.id,
        txn_no=txn.txn_no,
        transaction_type=txn.transaction_type,
        warehouse_id=txn.warehouse_id,
        warehouse_code=warehouse.warehouse_code if warehouse else None,
        warehouse_name=warehouse.warehouse_name if warehouse else None,
        material_id=txn.material_id,
        material_code=material.material_code if material else None,
        material_name=material.material_name if material else None,
        unit=material.unit if material else None,
        quantity=txn.quantity,
        unit_cost=txn.unit_cost,
        amount=txn.amount,
        balance_after=txn.balance_after,
        source_type=txn.source_type,
        source_id=txn.source_id,
        source_item_id=txn.source_item_id,
        reference_no=receipt_no,
        reversed_transaction_id=txn.reversed_transaction_id,
        operator_id=txn.created_by,
        operator_name=(operator.real_name or operator.username) if operator else None,
        transaction_at=txn.transaction_at,
        remark=txn.remark,
        created_at=txn.created_at,
    )


@router.get("/balances", summary="当前库存余额（含安全库存联查）")
def list_balances(
    db: DbDep,
    _user: CurrentUserDep,
    _guard: None = Depends(require_perm("inventory:view")),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    warehouse_id: int | None = Query(None),
    material_id: int | None = Query(None),
    material_code: str | None = Query(None, description="物料编码模糊搜索"),
    material_name: str | None = Query(None, description="物料名称模糊搜索"),
    below_safety_stock: bool | None = Query(None, description="true=仅低于安全库存"),
) -> ApiResponse[PageResult[BalanceRow]]:
    rows, total = inventory_service.list_balances(
        db,
        page=page,
        page_size=page_size,
        warehouse_id=warehouse_id,
        material_id=material_id,
        material_code=material_code,
        material_name=material_name,
        below_safety_stock=below_safety_stock,
    )
    return ApiResponse.ok(PageResult(items=rows, total=total, page=page, page_size=page_size))


@router.get("/transactions", summary="库存流水（append-only，按时间倒序）")
def list_transactions(
    db: DbDep,
    _user: CurrentUserDep,
    _guard: None = Depends(require_perm("inventory_txn:view")),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    warehouse_id: int | None = Query(None),
    material_id: int | None = Query(None),
    transaction_type: TxnType | None = Query(None),
    reference_no: str | None = Query(None, description="来源单据号（入库单号）模糊搜索"),
    source_type: TxnSourceType | None = Query(None),
    source_id: int | None = Query(None, description="来源单据 ID（如入库单 ID）"),
    occurred_from: datetime | None = Query(None, description="业务时间起（含）"),
    occurred_to: datetime | None = Query(None, description="业务时间止（含）"),
) -> ApiResponse[PageResult[TransactionOut]]:
    rows, total = inventory_service.list_transactions(
        db,
        page=page,
        page_size=page_size,
        warehouse_id=warehouse_id,
        material_id=material_id,
        transaction_type=transaction_type,
        reference_no=reference_no,
        source_type=source_type,
        source_id=source_id,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
    )
    # 一次性解析来源单据编号，避免逐行 N+1（流水只存 source_id，非 FK）
    receipt_ids = {
        t.source_id
        for t in rows
        if t.source_type
        in (TxnSourceType.PURCHASE_RECEIPT, TxnSourceType.PURCHASE_RECEIPT_REVERSAL)
        and t.source_id
    }
    receipt_no_by_id: dict[int, str] = {}
    if receipt_ids:
        receipt_no_by_id = dict(
            db.execute(
                select(PurchaseReceipt.id, PurchaseReceipt.receipt_no).where(
                    PurchaseReceipt.id.in_(receipt_ids)
                )
            ).all()
        )
    return ApiResponse.ok(
        PageResult(
            items=[_txn_out(db, t, receipt_no_by_id.get(t.source_id)) for t in rows],
            total=total,
            page=page,
            page_size=page_size,
        )
    )
