"""Stock reconciliation service (Reality Hardening Sprint 1 / Implementation A).

Implements the approved Design v2 core flow inside the caller's transaction
(the API commits once):

    Create (DRAFT + three book snapshots)
      -> Edit physical count (DRAFT, version CAS)
      -> Submit (DRAFT -> PENDING)
      -> Approve/Post (PENDING -> POSTED: claim -> lock balances ->
                       Snapshot Guard -> ADJUST_IN/OUT ledger -> balance ->
                       audit)
      -> Reject (PENDING -> REJECTED)

Key invariants implemented here (Design v2 + DA-001/002/012 + OQ-11/12):

* difference / adjustment_amount are computed **server-side** with Decimal;
  the frontend only previews them.
* ADJUST_IN (盘盈) requires an explicit ``valuation_rate > 0`` on every
  positive-difference line — including Book=0/Physical>0. The frontend may
  prefill a *one-time* suggestion from ``book_avg_cost_snapshot`` (OQ-11);
  the backend never silently falls back to the average cost.
* ADJUST_OUT (盘亏) values at ``book_avg_cost_snapshot`` (the snapshot /
  current inventory avg — the POST guard guarantees they are equal).
* Snapshot Guard (OQ-12): compare **both** current ``quantity`` vs
  ``book_quantity_snapshot`` AND current ``total_amount`` vs
  ``book_total_amount_snapshot``; stale if either differs -> 7005, whole
  transaction rolls back. avg_cost is NOT an independent staleness input.
* Self-approval (SoD) is forbidden by default; an ADMIN override requires
  ``override_self_approval`` + ``override_reason`` and is audited (RD-006).
* POST is one DB transaction: if any line fails (e.g. material B stale),
  nothing is posted — no ADJUST row, no balance mutation, document stays
  non-POSTED (Design v2 §33/§11).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.exceptions import (
    ConflictException,
    ErrorCode,
    NotFoundException,
    ReconciliationAlreadyProcessedException,
    ReconciliationBalanceChangedException,
    ReconciliationInvalidStatusException,
    ReconciliationNotFoundException,
    ReconciliationOverrideReasonRequiredException,
    ReconciliationSelfApprovalException,
    ReconciliationValuationRateRequiredException,
    ReconciliationVersionConflictException,
)
from app.models import (
    InventoryBalance,
    InventoryTransaction,
    Material,
    Permission,
    RolePermission,
    StockReconciliation,
    StockReconciliationItem,
    User,
    Warehouse,
)
from app.schemas.auth import CurrentUser
from app.schemas.reconciliation import (
    ReconciliationApproveIn,
    ReconciliationCreate,
    ReconciliationItemLine,
    ReconciliationUpdate,
)
from app.services import audit_service, inventory_service, numbering_service
from app.utils import money
from app.utils.enums import (
    ActiveStatus,
    AuditAction,
    ReconciliationStatus,
    SequenceKey,
    TxnSourceType,
    TxnType,
)

_MODULE = "reconcile"
_DOCUMENT_TYPE = "STOCK_RECONCILIATION"
_PREFIX = "CNT"
#: Explicit permission that gates SoD self-approval override (CR-A-007) — the
#: service checks this permission, never a hard-coded role identity.
_PERM_SELF_APPROVE_OVERRIDE = "reconcile:self_approve_override"

_ZERO = Decimal("0")
_Q4 = Decimal("0.0001")
#: Statuses reachable in Implementation A (CANCELLED / REVERSED reserved for B).
_DRAFT = ReconciliationStatus.DRAFT
_PENDING = ReconciliationStatus.PENDING
_POSTED = ReconciliationStatus.POSTED
_REJECTED = ReconciliationStatus.REJECTED


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load(db: Session, doc_id: int) -> StockReconciliation:
    doc = db.get(StockReconciliation, doc_id)
    if doc is None:
        raise ReconciliationNotFoundException()
    return doc


def _has_permission(db: Session, role_id: int, perm_code: str) -> bool:
    """Role-permission check inside the service (CR-A-007).

    Mirrors ``api.v1.deps.get_role_permissions`` membership but scoped to one
    code so business logic can gate on a permission — not on ``role == ADMIN``.
    """
    row = db.execute(
        select(Permission.perm_code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role_id, Permission.perm_code == perm_code)
        .limit(1)
    ).scalar_one_or_none()
    return row is not None


def _active_warehouse(db: Session, warehouse_id: int) -> Warehouse:
    wh = db.get(Warehouse, warehouse_id)
    if wh is None:
        raise NotFoundException("仓库不存在", code=ErrorCode.NOT_FOUND)
    if wh.status != ActiveStatus.ACTIVE:
        raise ConflictException(
            f"仓库 {wh.warehouse_code} 已停用，禁止创建盘点",
            code=ErrorCode.MASTER_DATA_DISABLED,
        )
    return wh


def _assert_material_active(db: Session, material_id: int) -> Material:
    """建行时物料必须存在且 ACTIVE（新增/编辑 DRAFT 行时校验）。

    提交/过账路径刻意不调用本函数：历史纠错不被当前主数据停用阻断
    （Design v2 §4.3 四十二，与 reverse_receipt 同款原则）。
    """
    mat = db.get(Material, material_id)
    if mat is None:
        raise NotFoundException("物料不存在", code=ErrorCode.NOT_FOUND)
    if mat.status != ActiveStatus.ACTIVE:
        raise ConflictException(
            f"物料 {mat.material_code} 已停用，禁止盘点",
            code=ErrorCode.MASTER_DATA_DISABLED,
        )
    return mat


def _snapshot(
    db: Session, warehouse_id: int, material_id: int
) -> tuple[Decimal, Decimal, Decimal, int | None]:
    """Read the current book state + ledger watermark for the snapshot.

    A missing balance row is 0 (Design v2 §3.3 / §6.2). The watermark
    (CR-A-002) is the max append-only ``inventory_transactions.id`` for the
    key, or None when the key has no ledger row. Both reads are plain SELECTs
    on purpose: building a DRAFT must never fabricate a balance row nor a
    transaction — balance rows are only created by ``lock_balance`` at POST
    time for rows that actually move stock.
    """
    row = db.execute(
        select(InventoryBalance).where(
            InventoryBalance.warehouse_id == warehouse_id,
            InventoryBalance.material_id == material_id,
        )
    ).scalar_one_or_none()
    watermark = db.execute(
        select(func.max(InventoryTransaction.id)).where(
            InventoryTransaction.warehouse_id == warehouse_id,
            InventoryTransaction.material_id == material_id,
        )
    ).scalar_one_or_none()
    if row is None:
        return _ZERO, Decimal("0.00"), _ZERO, watermark
    return row.quantity, row.total_amount, row.average_unit_cost, watermark


def _q4(value: Decimal) -> Decimal:
    """Normalize a quantity/rate to 4 decimals so in-memory Decimal
    serialization is stable ('97' vs '97.0000' drift)."""
    return value.quantize(_Q4)


def _amount_for(line: ReconciliationItemLine, *, snap_qty: Decimal,
                snap_avg: Decimal) -> tuple[Decimal, Decimal | None, Decimal]:
    """Server-authoritative line derivation -> (difference, rate, signed amount).

    * diff > 0 (盘盈): valuation_rate must be provided and > 0 (DA-002);
      amount = +money(diff x rate).
    * diff < 0 (盘亏): authoritative rate = snapshot avg; any client-sent
      rate is ignored (server decides); amount = -money(|diff| x avg).
    * diff = 0: no rate, no amount.
    """
    diff = _q4(line.physical_quantity) - snap_qty
    diff = _q4(diff)
    if diff > 0:
        rate = line.valuation_rate
        if rate is None or rate <= 0:
            raise ReconciliationValuationRateRequiredException()
        amount = money.money(diff * rate)
        return diff, _q4(rate), amount
    if diff < 0:
        rate = None  # 盘亏由快照均价权威决定，忽略客户端输入
        amount = -money.money(-diff * snap_avg)
        return diff, rate, amount
    return _ZERO, None, _ZERO


def _ensure_valid(
    db: Session, warehouse_id: int, lines: list[ReconciliationItemLine]
) -> list[tuple[ReconciliationItemLine, Decimal, Decimal, Decimal, int | None]]:
    """Validate a full line set & return per-line (snap_qty, snap_total, snap_avg, watermark).

    - duplicate material ids are rejected (uk_rc_mat backstop);
    - physical < 0 rejected (schema ge=0 + DB CHECK; double-checked here);
    - a new material line requires the material to be ACTIVE (add-time rule).
    """
    if not lines:
        raise ConflictException("盘点单至少需要一条明细", code=ErrorCode.RECONCILIATION_EMPTY_ITEMS)
    seen: set[int] = set()
    out: list[tuple[ReconciliationItemLine, Decimal, Decimal, Decimal, int | None]] = []
    for line in lines:
        if line.material_id in seen:
            raise ConflictException(
                "同一盘点单中不允许重复录入同一物料",
                code=ErrorCode.CONFLICT,
            )
        seen.add(line.material_id)
        if line.physical_quantity < 0:
            raise ConflictException(
                "实盘数量不能为负数",
                code=ErrorCode.RECONCILIATION_PHYSICAL_NEGATIVE,
            )
        _assert_material_active(db, line.material_id)
        out.append((line, *_snapshot(db, warehouse_id, line.material_id)))
    return out


# ----------------------------------------------------------------------
# Create / Update / Submit
# ----------------------------------------------------------------------
def create_reconciliation(
    db: Session,
    data: ReconciliationCreate,
    *,
    user: CurrentUser,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> StockReconciliation:
    """Create a DRAFT count document with frozen three-snapshots (RD-001)."""
    warehouse = _active_warehouse(db, data.warehouse_id)
    resolved = _ensure_valid(db, warehouse.id, data.items)

    counted_on = date.today()  # v1: backdated reconciliation is forbidden
    doc = StockReconciliation(
        reconciliation_no=numbering_service.next_daily_code(
            db, SequenceKey.STOCK_RECONCILIATION, _PREFIX, counted_on
        ),
        warehouse_id=warehouse.id,
        counted_by=user.id,
        counted_on=counted_on,
        status=_DRAFT,
        reason=data.reason,
        remark=data.remark,
        version=1,
    )
    db.add(doc)
    db.flush()

    for line_no, (line, snap_qty, snap_total, snap_avg, snap_wm) in enumerate(resolved, start=1):
        diff, rate, amount = _amount_for(line, snap_qty=snap_qty, snap_avg=snap_avg)
        db.add(
            StockReconciliationItem(
                reconciliation_id=doc.id,
                line_no=line_no,
                material_id=line.material_id,
                book_quantity_snapshot=snap_qty,
                book_total_amount_snapshot=snap_total,
                book_avg_cost_snapshot=snap_avg,
                book_last_transaction_id_snapshot=snap_wm,  # 流水水印（CR-A-002）
                physical_quantity=_q4(line.physical_quantity),
                difference_quantity=diff,
                valuation_rate=rate,
                adjustment_amount=amount,
                remark=line.remark,
            )
        )
    db.flush()

    audit_service.write_audit(
        db,
        action=AuditAction.STOCK_COUNT_CREATE,
        module=_MODULE,
        username_snapshot=user.username,
        document_type=_DOCUMENT_TYPE,
        document_id=doc.id,
        document_no=doc.reconciliation_no,
        description=(
            f"创建库存盘点 {doc.reconciliation_no}：仓库 {warehouse.warehouse_code}，"
            f"{len(resolved)} 条明细"
        ),
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    return doc


def update_reconciliation(
    db: Session,
    doc_id: int,
    data: ReconciliationUpdate,
    *,
    user: CurrentUser,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> StockReconciliation:
    """Edit a DRAFT — or revise a REJECTED document back to DRAFT and edit.

    Snapshot semantics (Design v2 §6.2): a line that stays for the same
    material keeps its captured snapshot; only newly added materials get a
    fresh snapshot. Removed lines are dropped (re-adding takes a new
    snapshot — the only legal way to "refresh").

    Concurrency (Design v2 §34): a DB-level conditional UPDATE on
    ``(id, version, status in (DRAFT, REJECTED))`` is the final CAS — two
    concurrent editors can never both win (pattern mirrors PR update).
    """
    doc = _load(db, doc_id)
    if doc.status not in (_DRAFT, _REJECTED):
        raise ReconciliationInvalidStatusException("仅 DRAFT（或 REJECTED 修订）的盘点单可编辑")
    if data.version != doc.version:
        raise ReconciliationVersionConflictException()

    _active_warehouse(db, doc.warehouse_id)  # 仓被停用则不可继续编辑/建单

    was_rejected = doc.status == _REJECTED
    doc.reason = data.reason
    doc.remark = data.remark
    existing = {item.material_id: item for item in doc.items}

    # 语义（Design v2 §4.3 四十二）：保留既有行 = 完成既有盘点，不被停用阻断；
    # 新增行 = 盘点创建期动作，物料必须 ACTIVE 并取当前快照。
    seen: set[int] = set()
    rebuilt: list[StockReconciliationItem] = []
    for line_no, line in enumerate(data.items, start=1):
        if line.material_id in seen:
            raise ConflictException(
                "同一盘点单中不允许重复录入同一物料",
                code=ErrorCode.CONFLICT,
            )
        seen.add(line.material_id)
        if line.physical_quantity < 0:
            raise ConflictException(
                "实盘数量不能为负数",
                code=ErrorCode.RECONCILIATION_PHYSICAL_NEGATIVE,
            )
        item = existing.get(line.material_id)
        if item is None:
            _assert_material_active(db, line.material_id)  # 仅新增行要求 ACTIVE
            snap_qty, snap_total, snap_avg, snap_wm = _snapshot(
                db, doc.warehouse_id, line.material_id
            )
            diff, rate, amount = _amount_for(line, snap_qty=snap_qty, snap_avg=snap_avg)
            item = StockReconciliationItem(
                reconciliation_id=doc.id,
                line_no=line_no,
                material_id=line.material_id,
                book_quantity_snapshot=snap_qty,
                book_total_amount_snapshot=snap_total,
                book_avg_cost_snapshot=snap_avg,
                book_last_transaction_id_snapshot=snap_wm,  # 流水水印（CR-A-002）
                physical_quantity=_q4(line.physical_quantity),
                difference_quantity=diff,
                valuation_rate=rate,
                adjustment_amount=amount,
                remark=line.remark,
            )
        else:
            # 既有行：保留固化快照，仅更新实盘/估值率/备注（不静默刷新快照）
            diff, rate, amount = _amount_for(
                line,
                snap_qty=item.book_quantity_snapshot,
                snap_avg=item.book_avg_cost_snapshot,
            )
            item.line_no = line_no
            item.physical_quantity = _q4(line.physical_quantity)
            item.difference_quantity = diff
            item.valuation_rate = rate
            item.adjustment_amount = amount
            item.remark = line.remark
        rebuilt.append(item)
    doc.items = rebuilt  # delete-orphan 移除不再保留的行

    # 原子乐观锁判定（version + 状态双条件；REJECTED -> DRAFT 修订在此完成）
    result = db.execute(
        update(StockReconciliation)
        .where(
            StockReconciliation.id == doc_id,
            StockReconciliation.version == data.version,
            StockReconciliation.status.in_([_DRAFT, _REJECTED]),
        )
        .values(
            status=_DRAFT,
            reason=doc.reason,
            remark=doc.remark,
            approve_comment=None,  # 进入新一轮 DRAFT，清掉上一轮驳回/审批意见
            version=StockReconciliation.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        raise ReconciliationVersionConflictException(
            "盘点单已被其他操作修改，请刷新后重试"
        )
    doc.status = _DRAFT
    if was_rejected:
        doc.approve_comment = None
    doc.version = data.version + 1
    db.flush()

    audit_service.write_audit(
        db,
        action=AuditAction.STOCK_COUNT_CREATE,
        module=_MODULE,
        username_snapshot=user.username,
        document_type=_DOCUMENT_TYPE,
        document_id=doc.id,
        document_no=doc.reconciliation_no,
        description=(
            f"编辑库存盘点 {doc.reconciliation_no}"
            + ("（驳回后修订）" if was_rejected else "")
            + f"：{len(rebuilt)} 条明细（version {doc.version}）"
        ),
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    return doc


def submit_reconciliation(
    db: Session,
    doc_id: int,
    *,
    version: int,
    user: CurrentUser,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> StockReconciliation:
    """DRAFT -> PENDING (version CAS + atomic status flip)."""
    doc = _load(db, doc_id)
    if doc.status != _DRAFT:
        raise ReconciliationInvalidStatusException("仅 DRAFT 状态的盘点单可提交")
    if version != doc.version:
        raise ReconciliationVersionConflictException()
    if not doc.items:
        raise ConflictException("盘点单至少需要一条明细", code=ErrorCode.RECONCILIATION_EMPTY_ITEMS)

    now = _now()
    claimed = db.execute(
        update(StockReconciliation)
        .where(
            StockReconciliation.id == doc_id,
            StockReconciliation.status == _DRAFT,
        )
        .values(
            status=_PENDING,
            submitted_at=now,
            version=StockReconciliation.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount == 0:
        raise ReconciliationAlreadyProcessedException()
    db.refresh(doc)

    audit_service.write_audit(
        db,
        action=AuditAction.STOCK_COUNT_SUBMIT,
        module=_MODULE,
        username_snapshot=user.username,
        document_type=_DOCUMENT_TYPE,
        document_id=doc.id,
        document_no=doc.reconciliation_no,
        description=f"提交库存盘点 {doc.reconciliation_no} 审批",
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    return doc


# ----------------------------------------------------------------------
# Approve == Post (Design v2 §4.2: no separate APPROVED state)
# ----------------------------------------------------------------------
def approve_reconciliation(
    db: Session,
    doc_id: int,
    payload: ReconciliationApproveIn,
    *,
    user: CurrentUser,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> StockReconciliation:
    """Approve AND post in one transaction (PENDING -> POSTED).

    Order inside the transaction (Design v2 §15; CR-A-003):
    1. atomic status claim (idempotency gate)
    2. SoD self-approval check — override gated on the explicit permission
       ``reconcile:self_approve_override`` (CR-A-007), mandatory reason
    3. validate all items
    4. ``lock_balances`` in the canonical (warehouse_id, material_id) order
    5. under the held X-locks, read each key's current ledger watermark
    6. Snapshot Guard per differing line:
       a. Ledger Event Guard — current watermark vs snapshot watermark
       b. Balance State Guard — quantity AND total_amount (OQ-12)
    7. append ADJUST_IN / ADJUST_OUT ledger rows (signed, §7)
    8. apply to balances (same lock order), recompute moving average
    9. mark POSTED, audit, single COMMIT by the caller
    """
    doc = _load(db, doc_id)
    if doc.status != _PENDING:
        # 已被并发审批/驳回等处理后，语义上视作"已处理"，让用户刷新
        raise ReconciliationInvalidStatusException(
            f"盘点单状态为 {doc.status.value}，不可审批过账"
        )

    # --- SoD (§9 / RD-006 / CR-A-007) ---------------------------------------
    # 判据是显式权限 reconcile:self_approve_override（seed 授 ADMIN），而非在
    # 业务服务里硬编码 role == ADMIN；override 仍需标志位 + 必填理由 + 审计。
    override_active = False
    if doc.counted_by == user.id:
        if not _has_permission(db, user.role_id, _PERM_SELF_APPROVE_OVERRIDE):
            raise ReconciliationSelfApprovalException(
                "盘点人不能审批本人盘点"
                f"（自审 override 需要权限 {_PERM_SELF_APPROVE_OVERRIDE}）"
            )
        if not payload.override_self_approval:
            raise ReconciliationSelfApprovalException()
        if not payload.override_reason:
            raise ReconciliationOverrideReasonRequiredException()
        override_active = True

    # --- 校验全部明细（diff 行率/负数等；POSTED 前最后一次权威计算） ------
    items = sorted(doc.items, key=lambda x: x.line_no)
    for item in items:
        if item.physical_quantity < 0:
            raise ConflictException(
                "实盘数量不能为负数", code=ErrorCode.RECONCILIATION_PHYSICAL_NEGATIVE
            )
        if item.difference_quantity > 0 and (
            item.valuation_rate is None or item.valuation_rate <= 0
        ):
            raise ReconciliationValuationRateRequiredException()

    # --- 状态认领（CAS；并发重复 approve 只有一个成功） --------------------
    now = _now()
    claimed = db.execute(
        update(StockReconciliation)
        .where(
            StockReconciliation.id == doc_id,
            StockReconciliation.status == _PENDING,
        )
        .values(
            status=_POSTED,
            posted_at=now,
            approved_by=user.id,
            approve_comment=payload.approve_comment,
            override_self_approval=(1 if override_active else 0),
            override_reason=(payload.override_reason if override_active else None),
            version=StockReconciliation.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount == 0:
        raise ReconciliationAlreadyProcessedException(
            "盘点单已被其他操作审批/处理，请刷新后重试"
        )
    db.refresh(doc)

    # --- 余额锁 + Snapshot Guard（Event + State）+ 流水 + 余额（diff != 0 行）
    # uk_rc_mat 保证单内物料唯一，故每个 (warehouse, material) 至多一行 ——
    # 逐行直接 apply，不需要聚合（聚合语义保留给未来同键多行的扩展）。
    moving = [(doc.warehouse_id, it.material_id) for it in items if it.difference_quantity != 0]
    keys: list[tuple[int, int]] = []
    locks: dict[tuple[int, int], InventoryBalance] = {}
    watermark_now: dict[int, int] = {}
    if moving:
        keys, locks = inventory_service.lock_balances(db, moving)
        # Event Guard 的当前水印：在持有全部余额 X 锁之后读取。任何写流水者
        # （Receipt / Reversal / 另一张盘点）都必须先取得同一把余额锁才能追加
        # 流水（CR-A-004），故锁在手 ⇒ 并发流水不可能插在水印读取与过账之间。
        wm_rows = db.execute(
            select(InventoryTransaction.material_id, func.max(InventoryTransaction.id))
            .where(
                InventoryTransaction.warehouse_id == doc.warehouse_id,
                InventoryTransaction.material_id.in_([m for (_w, m) in moving]),
            )
            .group_by(InventoryTransaction.material_id)
        ).all()
        watermark_now = {m: max_id for m, max_id in wm_rows}

    running_qty: dict[tuple[int, int], Decimal] = {
        k: locks[k].quantity for k in keys
    }

    touched: list[tuple[int, int]] = []
    for item in items:
        diff = item.difference_quantity
        if diff == 0:
            continue  # 零差异：过账不产生流水（Design v2 §4.3 四十）
        key = (doc.warehouse_id, item.material_id)
        balance = locks[key]

        # --- Snapshot Guard = 1) Ledger Event Guard + 2) Balance State Guard -
        # 1) Event Guard（CR-A-001/003）：快照后该键**任何**库存流水都会推高
        #    水印 —— 即便被同量反向补偿回到原状态（100 -> +10 -> -10 -> 100）
        #    也不放行，因为盘点窗口期内发生过 movement，基准已失效。
        wm_snapshot = item.book_last_transaction_id_snapshot or 0
        wm_current = watermark_now.get(item.material_id, 0)
        if wm_current != wm_snapshot:
            raise ReconciliationBalanceChangedException(
                f"物料 {item.material_id} 在盘点窗口期内发生库存流水"
                f"（水印 {wm_snapshot} → {wm_current}），盘点基准失效（stale），"
                "请刷新库存并重新盘点"
            )
        # 2) State Guard（OQ-12：quantity AND total_amount 双比较）
        if balance.quantity != item.book_quantity_snapshot:
            raise ReconciliationBalanceChangedException(
                f"物料 {item.material_id} 账面数量已由 {item.book_quantity_snapshot} "
                f"变为 {balance.quantity}，盘点基准漂移（stale）"
            )
        if balance.total_amount != item.book_total_amount_snapshot:
            raise ReconciliationBalanceChangedException(
                f"物料 {item.material_id} 账面金额已由 {item.book_total_amount_snapshot} "
                f"变为 {balance.total_amount}，盘点基准漂移（stale）"
            )

        if diff > 0:
            txn_type = TxnType.ADJUST_IN
            unit_cost = item.valuation_rate
        else:
            txn_type = TxnType.ADJUST_OUT
            unit_cost = item.book_avg_cost_snapshot

        running_qty[key] = running_qty[key] + diff
        inventory_service.write_transaction(
            db,
            txn_type=txn_type,
            warehouse_id=doc.warehouse_id,
            material_id=item.material_id,
            quantity=diff,  # 带符号：盘盈正 / 盘亏负
            unit_cost=unit_cost,
            amount=item.adjustment_amount,  # 带符号，服务端权威
            balance_after=running_qty[key],
            occurred_at=now,
            operator_id=user.id,
            source_type=TxnSourceType.STOCK_RECONCILIATION,
            source_id=doc.id,
            source_item_id=item.id,
            remark=f"{doc.reconciliation_no} 盘点调整"
            + (f"：{item.remark}" if item.remark else ""),
        )
        # 立即应用到余额（同锁序）：盘盈 apply_inbound、盘亏 apply_outbound
        if diff > 0:
            inventory_service.apply_inbound(
                db, balance=balance, quantity=diff, amount=item.adjustment_amount
            )
        else:
            inventory_service.apply_outbound(
                db, balance=balance, quantity=-diff, amount=-item.adjustment_amount
            )
        balance.last_transaction_at = now
        touched.append(key)
    db.flush()

    audit_service.write_audit(
        db,
        action=AuditAction.STOCK_COUNT_APPROVE,
        module=_MODULE,
        username_snapshot=user.username,
        document_type=_DOCUMENT_TYPE,
        document_id=doc.id,
        document_no=doc.reconciliation_no,
        description=(
            f"审批过账库存盘点 {doc.reconciliation_no}：{len(items)} 条明细，"
            f"{len(touched)} 条产生库存调整"
            + (f"；SoD override：{payload.override_reason}" if override_active else "")
        ),
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    return doc


def reject_reconciliation(
    db: Session,
    doc_id: int,
    *,
    comment: str,
    user: CurrentUser,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> StockReconciliation:
    """PENDING -> REJECTED（驳回意见必填）。REJECTED -> DRAFT 走 PUT。"""
    doc = _load(db, doc_id)
    if doc.status != _PENDING:
        raise ReconciliationInvalidStatusException(
            f"盘点单状态为 {doc.status.value}，不可驳回"
        )

    now = _now()
    claimed = db.execute(
        update(StockReconciliation)
        .where(
            StockReconciliation.id == doc_id,
            StockReconciliation.status == _PENDING,
        )
        .values(
            status=_REJECTED,
            approve_comment=comment,
            version=StockReconciliation.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount == 0:
        raise ReconciliationAlreadyProcessedException()
    db.refresh(doc)

    audit_service.write_audit(
        db,
        action=AuditAction.STOCK_COUNT_REJECT,
        module=_MODULE,
        username_snapshot=user.username,
        document_type=_DOCUMENT_TYPE,
        document_id=doc.id,
        document_no=doc.reconciliation_no,
        description=f"驳回库存盘点 {doc.reconciliation_no}：{comment}"[:500],
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    return doc


# ----------------------------------------------------------------------
# Read
# ----------------------------------------------------------------------
def get_reconciliation(db: Session, doc_id: int) -> StockReconciliation:
    return _load(db, doc_id)


def list_reconciliations(
    db: Session,
    *,
    page: int,
    page_size: int,
    reconciliation_no: str | None = None,
    warehouse_id: int | None = None,
    status: ReconciliationStatus | None = None,
    counted_on_from: date | None = None,
    counted_on_to: date | None = None,
) -> tuple[list[StockReconciliation], int, dict[int, int]]:
    """Paged list, newest first, with a per-document item count map."""
    stmt = select(StockReconciliation)
    count_stmt = select(func.count()).select_from(StockReconciliation)

    if reconciliation_no:
        cond = StockReconciliation.reconciliation_no.like(f"%{reconciliation_no}%")
        stmt, count_stmt = stmt.where(cond), count_stmt.where(cond)
    if warehouse_id is not None:
        cond = StockReconciliation.warehouse_id == warehouse_id
        stmt, count_stmt = stmt.where(cond), count_stmt.where(cond)
    if status is not None:
        cond = StockReconciliation.status == status
        stmt, count_stmt = stmt.where(cond), count_stmt.where(cond)
    if counted_on_from is not None:
        cond = StockReconciliation.counted_on >= counted_on_from
        stmt, count_stmt = stmt.where(cond), count_stmt.where(cond)
    if counted_on_to is not None:
        cond = StockReconciliation.counted_on <= counted_on_to
        stmt, count_stmt = stmt.where(cond), count_stmt.where(cond)

    total = db.execute(count_stmt).scalar_one()
    rows = db.execute(
        stmt.order_by(StockReconciliation.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).scalars().all()

    counts: dict[int, int] = {}
    if rows:
        ids = [r.id for r in rows]
        counts = dict(
            db.execute(
                select(
                    StockReconciliationItem.reconciliation_id,
                    func.count(),
                )
                .where(StockReconciliationItem.reconciliation_id.in_(ids))
                .group_by(StockReconciliationItem.reconciliation_id)
            ).all()
        )
    return list(rows), total, counts
