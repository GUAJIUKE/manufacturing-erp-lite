"""Inventory service (Phase 9): balances + append-only ledger + costing.

Two distinct concepts, never conflated (Phase 9 §二):

* :class:`InventoryTransaction` — the **ledger**. Append-only, signed
  quantity (inbound > 0, reversal < 0), immutable (MySQL triggers reject
  UPDATE/DELETE, architecture rule 3). Errors are corrected by writing a
  reversal row that points back via ``reversed_transaction_id``.
* :class:`InventoryBalance` — the **snapshot**. A derived cache keyed by
  ``UNIQUE(warehouse_id, material_id)``, mutated inside the same transaction
  that writes the ledger. ``SUM(inventory_transactions.quantity)`` must
  always reconcile with ``inventory_balances.quantity``.

Concurrency (Phase 9 §十四)
---------------------------
The balance row is never read-then-written in Python without a lock. Every
mutation goes through :func:`lock_balance`, which

1. issues ``INSERT ... ON DUPLICATE KEY UPDATE id = LAST_INSERT_ID(id)`` —
   a MySQL upsert that takes an **exclusive lock on the existing row** on
   the duplicate branch, so two transactions racing to create the very
   first row for a (warehouse, material) serialise instead of one of them
   getting a duplicate-key error (and the unique index stays the backstop);
2. then ``SELECT ... FOR UPDATE`` to read the committed values.

Holding that row lock until COMMIT is what makes the moving-average update
safe: the second inbound waits, then computes from the first one's result
instead of overwriting it (no lost update).

Lock ordering (Phase 9 §十五)
-----------------------------
Callers must sort the keys they touch by ``(warehouse_id, material_id)``
ascending before locking. All balance locks inside one transaction are
therefore acquired in one global order, which removes the classic
A-locks-1-then-2 / B-locks-2-then-1 deadlock.

Costing (Phase 9 §十二 / §十九)
------------------------------
``total_amount`` is authoritative (2 decimals, ROUND_HALF_UP);
``average_unit_cost`` is derived (4 decimals) and only a display /
issue-price helper. Reversals roll back the **original** receipt amount —
never ``current average_cost × qty`` — because later receipts at a
different price must not distort the reversal (§十九).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictException, ErrorCode, NotFoundException
from app.models import (
    InventoryBalance,
    InventoryPolicy,
    InventoryTransaction,
    Material,
    PurchaseReceipt,
    Warehouse,
)
from app.schemas.inventory import BalanceRow
from app.services import numbering_service
from app.utils import money
from app.utils.enums import SequenceKey, TxnSourceType, TxnType

#: Types that add stock (positive quantity) vs remove stock (negative).
_OUTBOUND_TYPES = frozenset({TxnType.PURCHASE_IN_REVERSAL, TxnType.ADJUST_OUT, TxnType.PRODUCTION_OUT})


class BalanceDelta:
    """Per-(warehouse, material) aggregate of one business operation.

    A single receipt may contain several lines for the same material (two
    PO lines of the same part), so quantity/amount are accumulated per key
    and the balance is written once per key.
    """

    __slots__ = ("quantity", "amount")

    def __init__(self) -> None:
        self.quantity = Decimal("0")
        self.amount = Decimal("0")


def sort_keys(keys: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Canonical lock order: (warehouse_id, material_id) ascending (§十五)."""
    return sorted(set(keys))


# ----------------------------------------------------------------------
# Balance locking (§十四)
# ----------------------------------------------------------------------
_UPSERT_LOCK_SQL = text(
    """
    INSERT INTO inventory_balances
        (warehouse_id, material_id, quantity, total_amount, average_unit_cost, version, created_at, updated_at)
    VALUES
        (:warehouse_id, :material_id, 0, 0, 0, 0, NOW(3), NOW(3))
    ON DUPLICATE KEY UPDATE id = LAST_INSERT_ID(id)
    """
)


def lock_balance(db: Session, warehouse_id: int, material_id: int) -> InventoryBalance:
    """Return the balance row for ``(warehouse_id, material_id)``, X-locked.

    Creates the row when it does not exist. The upsert's duplicate branch
    takes an exclusive lock on the existing row, so concurrent first-time
    creation of the same key cannot produce a duplicate-key error (and the
    ``uk_ib`` unique index remains the final backstop).
    """
    db.execute(
        _UPSERT_LOCK_SQL, {"warehouse_id": warehouse_id, "material_id": material_id}
    )
    row = db.execute(
        select(InventoryBalance)
        .where(
            InventoryBalance.warehouse_id == warehouse_id,
            InventoryBalance.material_id == material_id,
        )
        .with_for_update()
    ).scalar_one()
    return row


def _new_average(total_amount: Decimal, quantity: Decimal) -> Decimal:
    """Moving-average unit cost; 0 when the balance is empty (§二十)."""
    if quantity <= 0:
        return Decimal("0")
    return money.unit_cost(total_amount / quantity)


def apply_inbound(
    db: Session,
    *,
    balance: InventoryBalance,
    quantity: Decimal,
    amount: Decimal,
) -> None:
    """Add stock to an already-locked balance and recompute the average cost.

    ``quantity`` and ``amount`` are the *signed* deltas of one transaction
    (both positive for PURCHASE_IN). Caller owns the lock (§十四).
    """
    if quantity < 0:
        raise ConflictException(
            "入库流水数量必须为正（冲销请使用 PREVERSAL 类型）",
            code=ErrorCode.VALIDATION_ERROR,
        )
    new_quantity = balance.quantity + quantity
    new_total = money.money(balance.total_amount + amount)
    if new_quantity < 0 or new_total < 0:
        raise ConflictException(
            "库存余额不足，操作将导致负库存", code=ErrorCode.INVENTORY_NEGATIVE
        )
    balance.quantity = new_quantity
    balance.total_amount = new_total
    balance.average_unit_cost = _new_average(new_total, new_quantity)
    balance.version = (balance.version or 0) + 1
    db.flush()


def apply_outbound(
    db: Session,
    *,
    balance: InventoryBalance,
    quantity: Decimal,
    amount: Decimal,
) -> None:
    """Remove stock from an already-locked balance (reversal, §二十).

    ``quantity`` is the positive magnitude; ``amount`` is the **original**
    transaction amount to roll back (never current average × qty, §十九).
    """
    if quantity <= 0:
        raise ConflictException(
            "冲销数量必须大于 0", code=ErrorCode.VALIDATION_ERROR
        )
    new_quantity = balance.quantity - quantity
    new_total = money.money(balance.total_amount - amount)
    if new_quantity < 0:
        raise ConflictException(
            "库存数量不足，无法冲销（库存可能已被后续业务消耗）",
            code=ErrorCode.INVENTORY_NEGATIVE,
        )
    if new_total < 0:
        raise ConflictException(
            "库存金额不足，无法冲销（金额与流水不一致，请人工核查）",
            code=ErrorCode.INVENTORY_BALANCE_MISMATCH,
        )
    balance.quantity = new_quantity
    balance.total_amount = new_total
    # 归零时强制清 0，避免移动平均尾差残留（database-design §5.3）
    balance.average_unit_cost = _new_average(new_total, new_quantity)
    balance.version = (balance.version or 0) + 1
    db.flush()


# ----------------------------------------------------------------------
# Ledger (append-only, §十 / §二十三)
# ----------------------------------------------------------------------
def _next_txn_no(db: Session, when: date) -> str:
    seq = numbering_service.next_sequence_value(
        db, SequenceKey.INVENTORY_TRANSACTION, when
    )
    return f"TXN-{when:%Y%m%d}-{seq:06d}"


def write_transaction(
    db: Session,
    *,
    txn_type: TxnType,
    warehouse_id: int,
    material_id: int,
    quantity: Decimal,
    unit_cost: Decimal,
    amount: Decimal,
    balance_after: Decimal,
    occurred_at: datetime,
    operator_id: int,
    source_type: TxnSourceType | None = None,
    source_id: int | None = None,
    source_item_id: int | None = None,
    reversed_transaction_id: int | None = None,
    remark: str | None = None,
) -> InventoryTransaction:
    """Append one ledger row. Never UPDATE / DELETE afterwards (rule 3).

    ``quantity`` is signed: positive for inbound types, negative for
    ``PURCHASE_IN_REVERSAL`` / outbound types. ``amount`` carries the same
    sign so ``SUM(amount)`` reconciles with ``SUM(quantity)``.
    """
    if txn_type in _OUTBOUND_TYPES and quantity >= 0:
        raise ConflictException(
            "出库/冲销类流水必须使用负数数量", code=ErrorCode.VALIDATION_ERROR
        )
    if txn_type not in _OUTBOUND_TYPES and quantity <= 0:
        raise ConflictException(
            "入库类流水必须使用正数数量", code=ErrorCode.VALIDATION_ERROR
        )
    if unit_cost < 0:
        raise ConflictException("计价单价不能为负数", code=ErrorCode.VALIDATION_ERROR)

    txn = InventoryTransaction(
        txn_no=_next_txn_no(db, occurred_at.date()),
        transaction_type=txn_type,
        warehouse_id=warehouse_id,
        material_id=material_id,
        quantity=quantity,
        unit_cost=unit_cost,
        amount=amount,
        balance_after=balance_after,
        source_type=source_type,
        source_id=source_id,
        source_item_id=source_item_id,
        reversed_transaction_id=reversed_transaction_id,
        transaction_at=occurred_at,
        remark=remark,
        created_by=operator_id,
    )
    db.add(txn)
    db.flush()
    return txn


# ----------------------------------------------------------------------
# Queries
# ----------------------------------------------------------------------
def list_balances(
    db: Session,
    *,
    page: int,
    page_size: int,
    warehouse_id: int | None = None,
    material_id: int | None = None,
    material_code: str | None = None,
    material_name: str | None = None,
    below_safety_stock: bool | None = None,
) -> tuple[list[BalanceRow], int]:
    """Current stock with the safety-stock policy joined in (§二十四).

    Semantics chosen for Phase 9 (documented, uniform):
    * no ``inventory_policies`` row → ``safety_stock = None`` and
      ``is_below_safety_stock = False`` (no policy, no alarm);
    * otherwise ``is_below_safety_stock = quantity < safety_stock``.
    """
    stmt = (
        select(InventoryBalance, Warehouse, Material, InventoryPolicy.safety_stock)
        .join(Warehouse, Warehouse.id == InventoryBalance.warehouse_id)
        .join(Material, Material.id == InventoryBalance.material_id)
        .outerjoin(
            InventoryPolicy,
            (InventoryPolicy.warehouse_id == InventoryBalance.warehouse_id)
            & (InventoryPolicy.material_id == InventoryBalance.material_id),
        )
    )
    count_stmt = (
        select(func.count())
        .select_from(InventoryBalance)
        .join(Warehouse, Warehouse.id == InventoryBalance.warehouse_id)
        .join(Material, Material.id == InventoryBalance.material_id)
    )

    if warehouse_id is not None:
        stmt = stmt.where(InventoryBalance.warehouse_id == warehouse_id)
        count_stmt = count_stmt.where(InventoryBalance.warehouse_id == warehouse_id)
    if material_id is not None:
        stmt = stmt.where(InventoryBalance.material_id == material_id)
        count_stmt = count_stmt.where(InventoryBalance.material_id == material_id)
    if material_code:
        like = f"%{material_code}%"
        stmt = stmt.where(Material.material_code.like(like))
        count_stmt = count_stmt.where(
            InventoryBalance.material_id.in_(
                select(Material.id).where(Material.material_code.like(like))
            )
        )
    if material_name:
        like = f"%{material_name}%"
        stmt = stmt.where(Material.material_name.like(like))
        count_stmt = count_stmt.where(
            InventoryBalance.material_id.in_(
                select(Material.id).where(Material.material_name.like(like))
            )
        )
    if below_safety_stock is not None:
        # 无策略行时 safety_stock 视为"不告警"，故 below=True 只返回有策略且低于安全库存的行
        cond = InventoryPolicy.safety_stock.is_not(None) & (
            InventoryBalance.quantity < InventoryPolicy.safety_stock
        )
        if below_safety_stock:
            stmt = stmt.where(cond)
            count_stmt = count_stmt.outerjoin(
                InventoryPolicy,
                (InventoryPolicy.warehouse_id == InventoryBalance.warehouse_id)
                & (InventoryPolicy.material_id == InventoryBalance.material_id),
            ).where(cond)
        else:
            stmt = stmt.where(~cond)
            count_stmt = count_stmt.outerjoin(
                InventoryPolicy,
                (InventoryPolicy.warehouse_id == InventoryBalance.warehouse_id)
                & (InventoryPolicy.material_id == InventoryBalance.material_id),
            ).where(~cond)

    total = db.execute(count_stmt).scalar_one()
    rows = db.execute(
        stmt.order_by(InventoryBalance.warehouse_id, InventoryBalance.material_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    out: list[BalanceRow] = []
    for balance, warehouse, material, safety_stock in rows:
        out.append(
            BalanceRow(
                warehouse_id=warehouse.id,
                warehouse_code=warehouse.warehouse_code,
                warehouse_name=warehouse.warehouse_name,
                material_id=material.id,
                material_code=material.material_code,
                material_name=material.material_name,
                unit=material.unit,
                quantity=balance.quantity,
                average_unit_cost=balance.average_unit_cost,
                total_amount=balance.total_amount,
                safety_stock=safety_stock,
                is_below_safety_stock=(
                    False if safety_stock is None else balance.quantity < safety_stock
                ),
                last_transaction_at=balance.last_transaction_at,
            )
        )
    return out, total


def list_transactions(
    db: Session,
    *,
    page: int,
    page_size: int,
    warehouse_id: int | None = None,
    material_id: int | None = None,
    transaction_type: TxnType | None = None,
    reference_no: str | None = None,
    source_type: TxnSourceType | None = None,
    source_id: int | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
) -> tuple[list[InventoryTransaction], int]:
    """Ledger query, newest first (§二十五).

    Ordering is ``transaction_at DESC, id DESC`` — a receipt created for a
    back-dated business day would otherwise jump around, and ``id`` keeps
    the order stable for same-timestamp rows.
    """
    stmt = select(InventoryTransaction)
    count_stmt = select(func.count()).select_from(InventoryTransaction)

    if warehouse_id is not None:
        cond = InventoryTransaction.warehouse_id == warehouse_id
        stmt, count_stmt = stmt.where(cond), count_stmt.where(cond)
    if material_id is not None:
        cond = InventoryTransaction.material_id == material_id
        stmt, count_stmt = stmt.where(cond), count_stmt.where(cond)
    if transaction_type is not None:
        cond = InventoryTransaction.transaction_type == transaction_type
        stmt, count_stmt = stmt.where(cond), count_stmt.where(cond)
    if reference_no:
        # reference_no 是来源单据编号（这里是入库单 receipt_no）。流水只存
        # source_id（非 FK，见 data-integrity-review §2），故反查单据表。
        like = f"%{reference_no}%"
        receipt_ids = select(PurchaseReceipt.id).where(PurchaseReceipt.receipt_no.like(like))
        cond = or_(
            InventoryTransaction.txn_no.like(like),
            (
                InventoryTransaction.source_type.in_(
                    [TxnSourceType.PURCHASE_RECEIPT, TxnSourceType.PURCHASE_RECEIPT_REVERSAL]
                )
                & InventoryTransaction.source_id.in_(receipt_ids)
            ),
        )
        stmt, count_stmt = stmt.where(cond), count_stmt.where(cond)
    if source_type is not None:
        cond = InventoryTransaction.source_type == source_type
        stmt, count_stmt = stmt.where(cond), count_stmt.where(cond)
    if source_id is not None:
        cond = InventoryTransaction.source_id == source_id
        stmt, count_stmt = stmt.where(cond), count_stmt.where(cond)
    if occurred_from is not None:
        cond = InventoryTransaction.transaction_at >= occurred_from
        stmt, count_stmt = stmt.where(cond), count_stmt.where(cond)
    if occurred_to is not None:
        cond = InventoryTransaction.transaction_at <= occurred_to
        stmt, count_stmt = stmt.where(cond), count_stmt.where(cond)

    total = db.execute(count_stmt).scalar_one()
    rows = db.execute(
        stmt.order_by(InventoryTransaction.transaction_at.desc(), InventoryTransaction.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).scalars().all()
    return list(rows), total


def get_balance(db: Session, warehouse_id: int, material_id: int) -> InventoryBalance:
    balance = db.execute(
        select(InventoryBalance).where(
            InventoryBalance.warehouse_id == warehouse_id,
            InventoryBalance.material_id == material_id,
        )
    ).scalar_one_or_none()
    if balance is None:
        raise NotFoundException("库存余额不存在", code=ErrorCode.NOT_FOUND)
    return balance
