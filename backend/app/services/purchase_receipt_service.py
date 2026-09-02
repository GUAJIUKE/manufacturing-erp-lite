"""Purchase receipt service (Phase 9): receiving + reversal.

Four concepts are kept strictly apart (Phase 9 §二):

=============== ==================================================
PO              purchasing intent (ordered / received quantities)
Receipt         one physical receiving event (business fact)
Transaction     append-only stock ledger (history of truth)
Balance         derived current snapshot (cache, never authority)
=============== ==================================================

Everything below runs inside the caller's transaction (§十六): the API
commits once, so a failure anywhere — including on the second line of a
multi-line receipt — leaves no receipt, no PO quantity change, no ledger
row and no balance change (tested in ``test_purchase_receipt.py``).

Concurrency (§八 / §十四)
-------------------------
* PO receiving: **conditional UPDATE** ``received_quantity + :qty <=
  ordered_quantity`` + ``rowcount`` check. Never SELECT-then-decide, which
  would let two warehouse clerks both see the same remaining quantity and
  over-receive.
* Balance: ``INSERT ... ON DUPLICATE KEY UPDATE id = LAST_INSERT_ID(id)``
  followed by ``SELECT ... FOR UPDATE`` (see :mod:`app.services.inventory_service`).
* Lock order (Review Fix §2): **all** balance locks are taken first, in one
  pre-sorted pass over ``(warehouse_id, material_id)`` ascending via
  ``inventory_service.lock_balances`` — in ``create_receipt`` they precede
  even the receipt-header insert (whose FK checks take shared locks on the
  PO / warehouse rows), so balance locks are the first row locks of the
  transaction. PO lines are CAS-updated sorted by ``po_item_id``. Only
  ``reverse_receipt`` deviates: it first claims its *own* receipt row
  atomically (status flip, §二十一), then locks balances in the same
  canonical order. Every order is global, so two receipts touching the same
  parts can never deadlock by locking in opposite order.

Reversal (§十八 / §十九)
------------------------
Whole-receipt only, atomic status claim first (``WHERE status = POSTED``),
stock rolled back by the **original** receipt amount (never by the current
average cost), and the PO status recomputed from the item quantities
(§九 / §二十二) instead of hard-coded.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.exceptions import (
    ConflictException,
    ErrorCode,
    NotFoundException,
    PermissionDeniedException,
)
from app.models import (
    InventoryTransaction,
    Material,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseReceipt,
    PurchaseReceiptItem,
    Supplier,
    User,
    Warehouse,
)
from app.schemas.auth import CurrentUser
from app.schemas.purchase_receipt import PurchaseReceiptCreate
from app.services import audit_service, numbering_service
from app.services import inventory_service, purchase_order_service
from app.utils import money
from app.utils.enums import (
    ActiveStatus,
    AuditAction,
    PoStatus,
    ReceiptStatus,
    RoleCode,
    SequenceKey,
    TxnSourceType,
    TxnType,
)

_MODULE = "receipt"
_DOCUMENT_TYPE = "PURCHASE_RECEIPT"

#: PO states that still accept goods (§五.2 - §五.5).
_RECEIVABLE_STATUSES = frozenset({PoStatus.CONFIRMED, PoStatus.PARTIALLY_RECEIVED})

#: Roles that see every receipt: admin runs the system, warehouse performs
#: receiving for the whole company (§二十七).
_FULL_SCOPE_ROLES = frozenset({RoleCode.ADMIN.value, RoleCode.WAREHOUSE.value})


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _load(db: Session, receipt_id: int) -> PurchaseReceipt:
    receipt = db.get(PurchaseReceipt, receipt_id)
    if receipt is None:
        raise NotFoundException("入库单不存在", code=ErrorCode.RECEIPT_NOT_FOUND)
    return receipt


def _receivable_po(db: Session, po_id: int) -> PurchaseOrder:
    po = db.get(PurchaseOrder, po_id)
    if po is None:
        raise NotFoundException("采购订单不存在", code=ErrorCode.PO_NOT_FOUND)
    if po.status not in _RECEIVABLE_STATUSES:
        raise ConflictException(
            f"采购订单 {po.po_no} 状态为 {po.status.value}，不可收货"
            "（仅 CONFIRMED / PARTIALLY_RECEIVED 允许）",
            code=ErrorCode.PO_NOT_RECEIVABLE,
        )
    return po


def _active_warehouse(db: Session, warehouse_id: int) -> Warehouse:
    warehouse = db.get(Warehouse, warehouse_id)
    if warehouse is None:
        raise NotFoundException("仓库不存在", code=ErrorCode.NOT_FOUND)
    if warehouse.status != ActiveStatus.ACTIVE:
        raise ConflictException(
            f"仓库 {warehouse.warehouse_code} 已停用，禁止收货",
            code=ErrorCode.MASTER_DATA_DISABLED,
        )
    return warehouse


def _assert_material_active(db: Session, material_id: int) -> Material:
    """§二十九：收货前物料必须 ACTIVE（停用主数据不再产生新库存业务）。

    冲销路径刻意不调用本函数——撤销历史错误业务不应被当前主数据状态阻断。
    """
    material = db.get(Material, material_id)
    if material is None:
        raise NotFoundException("物料不存在", code=ErrorCode.NOT_FOUND)
    if material.status != ActiveStatus.ACTIVE:
        raise ConflictException(
            f"物料 {material.material_code} 已停用，禁止收货",
            code=ErrorCode.MASTER_DATA_DISABLED,
        )
    return material


def recompute_po_status(db: Session, po: PurchaseOrder) -> PoStatus:
    """Derive the PO status from its items' received quantities (§九).

    Never hard-codes "reversal → PARTIALLY_RECEIVED": after every receipt
    and every reversal the status is recomputed from scratch, so reversing
    the last shipment correctly walks RECEIVED → PARTIALLY_RECEIVED →
    CONFIRMED (§二十二).
    """
    items = db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.po_id == po.id)
    ).scalars().all()
    if not items:
        return po.status
    all_zero = all(i.received_quantity == 0 for i in items)
    all_full = all(i.received_quantity == i.ordered_quantity for i in items)
    if all_zero:
        target = PoStatus.CONFIRMED
    elif all_full:
        target = PoStatus.RECEIVED
    else:
        target = PoStatus.PARTIALLY_RECEIVED
    if target != po.status:
        db.execute(
            update(PurchaseOrder)
            .where(PurchaseOrder.id == po.id)
            .values(status=target)
            .execution_options(synchronize_session=False)
        )
        po.status = target
        db.flush()
    return target


def _visible_po_stmt(db: Session, user: CurrentUser):
    """Object-level read scope for receipts (§二十七)。

    Returns a PO-id subquery, or ``None`` when the role sees everything.
    BUYER only sees receipts of POs they own; APPLICANT / DEPT_MANAGER
    reuse the PR-chain scope already defined for POs in Phase 8.
    """
    if user.role_code in _FULL_SCOPE_ROLES:
        return None
    if user.role_code == RoleCode.BUYER.value:
        return select(PurchaseOrder.id).where(PurchaseOrder.buyer_id == user.id)
    return purchase_order_service.visible_po_id_stmt(db, user)


def _assert_visible(db: Session, receipt: PurchaseReceipt, user: CurrentUser) -> None:
    sub = _visible_po_stmt(db, user)
    if sub is None:
        return
    row = db.execute(
        select(PurchaseReceipt.id)
        .where(PurchaseReceipt.id == receipt.id, PurchaseReceipt.po_id.in_(sub))
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        raise PermissionDeniedException("无权查看该入库单", code=ErrorCode.PERMISSION_DENIED)


# ----------------------------------------------------------------------
# Create receipt (§五 / §十六)
# ----------------------------------------------------------------------
def create_receipt(
    db: Session,
    data: PurchaseReceiptCreate,
    *,
    user: CurrentUser,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> PurchaseReceipt:
    """Post a receiving event: header + items + PO quantities + ledger +
    balances + PO status + audit, all in the caller's transaction."""
    if not data.items:
        raise ConflictException("入库单至少需要一条明细", code=ErrorCode.RECEIPT_EMPTY_ITEMS)

    # --- 预校验：PO / 仓库 / 明细归属 / 物料 / 数量 -------------------
    po = _receivable_po(db, data.po_id)
    warehouse = _active_warehouse(db, data.warehouse_id)

    seen: set[int] = set()
    for item in data.items:
        if item.po_item_id in seen:
            raise ConflictException(
                "同一入库单中不允许重复引用同一采购订单明细",
                code=ErrorCode.RECEIPT_DUPLICATE_ITEM,
            )
        seen.add(item.po_item_id)
        if item.received_quantity <= 0:
            raise ConflictException(
                "入库数量必须大于 0", code=ErrorCode.RECEIPT_QUANTITY_POSITIVE
            )

    po_items: dict[int, PurchaseOrderItem] = {}
    for item in data.items:
        poi = db.get(PurchaseOrderItem, item.po_item_id)
        if poi is None:
            raise NotFoundException(
                "采购订单明细不存在", code=ErrorCode.PO_ITEM_NOT_FOUND
            )
        if poi.po_id != po.id:
            raise ConflictException(
                f"采购订单明细 {poi.line_no} 不属于采购订单 {po.po_no}",
                code=ErrorCode.RECEIPT_ITEM_NOT_IN_PO,
            )
        _assert_material_active(db, poi.material_id)  # material_id 服务端推导
        po_items[poi.id] = poi

    receipt_date: date = data.receipt_date or date.today()
    now = datetime.now(timezone.utc)
    received_at = datetime.combine(receipt_date, now.time())

    # --- 锁顺序（Review Fix §2）：余额锁必须是本事务的第一组行锁 -------
    # 全量去重 + (warehouse_id, material_id) 升序一次性取齐（lock_balances
    # 内部保证）。若先插入单头再锁余额，单头 INSERT 的 FK 检查会对 PO /
    # 仓库行加 S 锁并持有到 COMMIT——两个并发入库同一 PO 时可能形成
    # "create 持 S(PO) 等余额 / 对方持余额等重算所需 X(PO)" 的交叉等待
    # （InnoDB 死锁）。余额锁前置后，事务内后续所有行锁（单头 FK S 锁、
    # PO 行 CAS、序列行）都排在统一的有序余额锁之后，交叉等待不复存在。
    keys, locks = inventory_service.lock_balances(
        db,
        [(warehouse.id, poi.material_id) for poi in po_items.values()],
    )
    running_qty: dict[tuple[int, int], Decimal] = {k: locks[k].quantity for k in keys}
    agg: dict[tuple[int, int], inventory_service.BalanceDelta] = {
        k: inventory_service.BalanceDelta() for k in keys
    }

    receipt_no = numbering_service.next_daily_code(
        db, SequenceKey.PURCHASE_RECEIPT, "RCV", receipt_date
    )
    receipt = PurchaseReceipt(
        receipt_no=receipt_no,
        po_id=po.id,
        warehouse_id=warehouse.id,
        received_by=user.id,  # 服务端确定，客户端不可伪造
        received_at=received_at,
        status=ReceiptStatus.POSTED,  # 无 DRAFT：创建即过账（§六）
        remark=data.remark,
    )
    db.add(receipt)
    db.flush()

    # --- 逐明细：PO CAS → 入库明细 → 库存流水（po_item_id 升序） -------
    for line_no, item in enumerate(sorted(data.items, key=lambda x: x.po_item_id), start=1):
        poi = po_items[item.po_item_id]
        qty = item.received_quantity

        result = db.execute(
            update(PurchaseOrderItem)
            .where(
                PurchaseOrderItem.id == poi.id,
                PurchaseOrderItem.received_quantity + qty
                <= PurchaseOrderItem.ordered_quantity,
            )
            .values(received_quantity=PurchaseOrderItem.received_quantity + qty)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 0:
            # 锁定读穿透 REPEATABLE READ 快照，给出准确的剩余数量（§八）
            db.refresh(poi, with_for_update=True)
            remaining = poi.ordered_quantity - poi.received_quantity
            raise ConflictException(
                f"明细 {poi.line_no} 入库数量 {qty} 超过剩余可收数量 {remaining}"
                "（可能已被其他入库单占用）",
                code=ErrorCode.RECEIPT_EXCEEDS_REMAINING,
            )
        poi.received_quantity = poi.received_quantity + qty

        unit_price = poi.unit_price  # 成本快照，取自 PO 明细（§十三）
        amount = money.line_amount(qty, unit_price)
        ri = PurchaseReceiptItem(
            receipt_id=receipt.id,
            po_item_id=poi.id,
            line_no=line_no,
            material_id=poi.material_id,  # 冗余自 PO 明细，不由客户端指定
            received_quantity=qty,
            unit_price=unit_price,
            amount=amount,
            remark=item.remark,
        )
        db.add(ri)
        db.flush()

        key = (warehouse.id, poi.material_id)
        running_qty[key] = running_qty[key] + qty
        inventory_service.write_transaction(
            db,
            txn_type=TxnType.PURCHASE_IN,
            warehouse_id=warehouse.id,
            material_id=poi.material_id,
            quantity=qty,
            unit_cost=unit_price,
            amount=amount,
            balance_after=running_qty[key],
            occurred_at=received_at,
            operator_id=user.id,
            source_type=TxnSourceType.PURCHASE_RECEIPT,
            source_id=receipt.id,
            source_item_id=ri.id,
            remark=(data.remark or None),
        )
        agg[key].quantity += qty
        agg[key].amount += amount

    # --- 余额写入（同一锁序） ----------------------------------------
    for key in keys:
        balance = locks[key]
        inventory_service.apply_inbound(
            db,
            balance=balance,
            quantity=agg[key].quantity,
            amount=agg[key].amount,
        )
        balance.last_transaction_at = received_at
    db.flush()

    old_status = po.status
    new_status = recompute_po_status(db, po)

    audit_service.write_audit(
        db,
        action=AuditAction.RECEIPT_POST,
        module=_MODULE,
        username_snapshot=user.username,
        document_type=_DOCUMENT_TYPE,
        document_id=receipt.id,
        document_no=receipt.receipt_no,
        description=(
            f"采购入库过账 {receipt.receipt_no}：PO {po.po_no} → 仓库 "
            f"{warehouse.warehouse_code}，{len(data.items)} 条明细；"
            f"PO 状态 {old_status.value} → {new_status.value}"
        ),
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    return receipt


# ----------------------------------------------------------------------
# Reverse (§十八 - §二十二)
# ----------------------------------------------------------------------
def reverse_receipt(
    db: Session,
    receipt_id: int,
    *,
    reason: str,
    user: CurrentUser,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> PurchaseReceipt:
    """Reverse a whole POSTED receipt.

    Ordering matters: the status flip is claimed atomically FIRST, so two
    concurrent reversals can never both proceed (§二十一). Business data is
    then rolled back using the original receipt amounts (§十九).
    """
    receipt = _load(db, receipt_id)
    if receipt.status == ReceiptStatus.REVERSED:
        raise ConflictException(
            "入库单已冲销，不能重复冲销", code=ErrorCode.RECEIPT_ALREADY_REVERSED
        )
    if receipt.status != ReceiptStatus.POSTED:
        raise ConflictException(
            f"入库单状态为 {receipt.status.value}，不可冲销",
            code=ErrorCode.RECEIPT_NOT_POSTED,
        )

    now = datetime.now(timezone.utc)
    claimed = db.execute(
        update(PurchaseReceipt)
        .where(
            PurchaseReceipt.id == receipt_id,
            PurchaseReceipt.status == ReceiptStatus.POSTED,
        )
        .values(
            status=ReceiptStatus.REVERSED,
            reversed_by=user.id,
            reversed_at=now,
            reverse_reason=reason,
        )
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount == 0:
        raise ConflictException(
            "入库单已被其他操作冲销，请刷新后重试",
            code=ErrorCode.RECEIPT_ALREADY_REVERSED,
        )
    receipt.status = ReceiptStatus.REVERSED
    receipt.reversed_by = user.id
    receipt.reversed_at = now
    receipt.reverse_reason = reason
    db.refresh(receipt)

    po = db.get(PurchaseOrder, receipt.po_id)
    items = sorted(receipt.items, key=lambda x: x.po_item_id)

    # 余额锁：与入库同序，全量去重 + (warehouse_id, material_id) 升序
    # 一次取齐（Review Fix §2，lock_balances 统一入口）。
    keys, locks = inventory_service.lock_balances(
        db,
        [(receipt.warehouse_id, ri.material_id) for ri in items],
    )
    running_qty: dict[tuple[int, int], Decimal] = {k: locks[k].quantity for k in keys}
    agg: dict[tuple[int, int], inventory_service.BalanceDelta] = {
        k: inventory_service.BalanceDelta() for k in keys
    }

    for ri in items:
        poi = db.get(PurchaseOrderItem, ri.po_item_id)
        if poi is None:
            raise NotFoundException(
                "采购订单明细不存在", code=ErrorCode.PO_ITEM_NOT_FOUND
            )
        result = db.execute(
            update(PurchaseOrderItem)
            .where(
                PurchaseOrderItem.id == poi.id,
                PurchaseOrderItem.received_quantity >= ri.received_quantity,
            )
            .values(
                received_quantity=PurchaseOrderItem.received_quantity
                - ri.received_quantity
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 0:
            raise ConflictException(
                f"回退采购订单明细 {poi.line_no} 的收货数量失败（数据异常或已被并发冲销）",
                code=ErrorCode.CONFLICT,
            )
        poi.received_quantity = poi.received_quantity - ri.received_quantity

        # 原始流水：按来源定位，冲销金额取原始记录而非当前平均成本（§十九）
        original = db.execute(
            select(InventoryTransaction)
            .where(
                InventoryTransaction.source_type == TxnSourceType.PURCHASE_RECEIPT,
                InventoryTransaction.source_id == receipt.id,
                InventoryTransaction.source_item_id == ri.id,
            )
            .limit(1)
        ).scalar_one_or_none()
        if original is None:
            raise ConflictException(
                "找不到原始入库流水，无法冲销（数据异常，请人工核查）",
                code=ErrorCode.INVENTORY_BALANCE_MISMATCH,
            )
        already = db.execute(
            select(InventoryTransaction.id)
            .where(InventoryTransaction.reversed_transaction_id == original.id)
            .limit(1)
        ).scalar_one_or_none()
        if already is not None:
            raise ConflictException(
                "该入库流水已被冲销，不能重复冲销",
                code=ErrorCode.RECEIPT_ALREADY_REVERSED,
            )

        key = (receipt.warehouse_id, ri.material_id)
        running_qty[key] = running_qty[key] - ri.received_quantity
        inventory_service.write_transaction(
            db,
            txn_type=TxnType.PURCHASE_IN_REVERSAL,
            warehouse_id=receipt.warehouse_id,
            material_id=ri.material_id,
            quantity=-ri.received_quantity,
            unit_cost=original.unit_cost,
            amount=-original.amount,
            balance_after=running_qty[key],
            occurred_at=now,
            operator_id=user.id,
            source_type=TxnSourceType.PURCHASE_RECEIPT_REVERSAL,
            source_id=receipt.id,
            source_item_id=ri.id,
            reversed_transaction_id=original.id,
            remark=f"冲销 {receipt.receipt_no}：{reason}"[:500],
        )
        agg[key].quantity += ri.received_quantity
        agg[key].amount += original.amount

    for key in keys:
        balance = locks[key]
        inventory_service.apply_outbound(
            db,
            balance=balance,
            quantity=agg[key].quantity,
            amount=agg[key].amount,
        )
        balance.last_transaction_at = now
    db.flush()

    old_status = po.status if po else None
    new_status = recompute_po_status(db, po) if po else None

    audit_service.write_audit(
        db,
        action=AuditAction.RECEIPT_REVERSE,
        module=_MODULE,
        username_snapshot=user.username,
        document_type=_DOCUMENT_TYPE,
        document_id=receipt.id,
        document_no=receipt.receipt_no,
        description=(
            f"冲销采购入库 {receipt.receipt_no}：原因：{reason}"
            + (
                f"；PO {po.po_no} 状态 {old_status.value} → {new_status.value}"
                if po
                else ""
            )
        ),
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    return receipt


# ----------------------------------------------------------------------
# Read
# ----------------------------------------------------------------------
def get_receipt(db: Session, receipt_id: int, *, user: CurrentUser) -> PurchaseReceipt:
    receipt = _load(db, receipt_id)
    _assert_visible(db, receipt, user)
    return receipt


def list_receipts(
    db: Session,
    *,
    user: CurrentUser,
    page: int,
    page_size: int,
    receipt_no: str | None = None,
    po_no: str | None = None,
    po_id: int | None = None,
    warehouse_id: int | None = None,
    status: ReceiptStatus | None = None,
    receipt_date_from: date | None = None,
    receipt_date_to: date | None = None,
) -> tuple[list[PurchaseReceipt], int]:
    from sqlalchemy import func  # local import keeps the module header lean

    stmt = select(PurchaseReceipt)
    count_stmt = select(func.count()).select_from(PurchaseReceipt)

    sub = _visible_po_stmt(db, user)
    if sub is not None:
        stmt = stmt.where(PurchaseReceipt.po_id.in_(sub))
        count_stmt = count_stmt.where(PurchaseReceipt.po_id.in_(sub))
    if po_id is not None:
        cond = PurchaseReceipt.po_id == po_id
        stmt, count_stmt = stmt.where(cond), count_stmt.where(cond)
    if receipt_no:
        cond = PurchaseReceipt.receipt_no.like(f"%{receipt_no}%")
        stmt, count_stmt = stmt.where(cond), count_stmt.where(cond)
    if po_no:
        po_ids = select(PurchaseOrder.id).where(PurchaseOrder.po_no.like(f"%{po_no}%"))
        cond = PurchaseReceipt.po_id.in_(po_ids)
        stmt, count_stmt = stmt.where(cond), count_stmt.where(cond)
    if warehouse_id is not None:
        cond = PurchaseReceipt.warehouse_id == warehouse_id
        stmt, count_stmt = stmt.where(cond), count_stmt.where(cond)
    if status is not None:
        cond = PurchaseReceipt.status == status
        stmt, count_stmt = stmt.where(cond), count_stmt.where(cond)
    if receipt_date_from is not None:
        cond = PurchaseReceipt.received_at >= datetime.combine(
            receipt_date_from, datetime.min.time()
        )
        stmt, count_stmt = stmt.where(cond), count_stmt.where(cond)
    if receipt_date_to is not None:
        cond = PurchaseReceipt.received_at <= datetime.combine(
            receipt_date_to, datetime.max.time()
        )
        stmt, count_stmt = stmt.where(cond), count_stmt.where(cond)

    total = db.execute(count_stmt).scalar_one()
    rows = db.execute(
        stmt.order_by(PurchaseReceipt.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).scalars().all()
    return list(rows), total
