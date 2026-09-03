"""Dashboard / management-cockpit aggregation service (Phase 11).

Design contract (see docs/dashboard_metrics.md for the full metric sheet):

* Aggregation happens in the DATABASE (COUNT / SUM / GROUP BY). No
  ``SELECT all rows then len()/sum() in Python``, no per-row ORM loads,
  no N+1.
* Every KPI honours the same object-level scopes as the business list
  pages — Dashboard is still a business-data query, so it reuses the
  existing visible-range helpers instead of copying a second set of rules:
    - PR scope   -> ``purchase_requisition_service.visible_pr_condition``
    - PO scope   -> ``purchase_order_service.visible_po_id_stmt``
    - low-stock  -> same semantics as ``inventory_service.list_balances``
                    (needs a policy row AND quantity < safety_stock)
* Money is ``Decimal`` end to end. The wire format is a string (FastAPI
  serializes Decimal as string); the client formats, never recomputes.
* Trend calendar gaps are filled server-side with count/amount = 0 so the
  chart never shows a ragged axis.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import (
    InventoryBalance,
    InventoryPolicy,
    InventoryTransaction,
    Material,
    OperationLog,
    PurchaseOrder,
    PurchaseRequisition,
    PurchaseRequisitionItem,
    User,
    Warehouse,
)
from app.schemas.auth import CurrentUser
from app.schemas.dashboard import (
    ActivityItem,
    DashboardStatusCount,
    DashboardSummary,
    DashboardTrendPoint,
    InventoryActivityItem,
    LowStockRow,
    TodoItem,
)
from app.services import purchase_order_service, purchase_requisition_service
from app.utils.enums import (
    AuditAction,
    PoStatus,
    PrStatus,
    RoleCode,
    TxnSourceType,
)

#: Key business events shown on the "最近采购动态" timeline. Deliberately
#: excludes LOGIN / LOGIN_FAILED / master-data CRUD / PERMISSION_CHANGE so
#: the dashboard stays a business cockpit, not an audit-log browser.
_RECENT_ACTIONS = frozenset(
    {
        AuditAction.PR_CREATE,
        AuditAction.PR_SUBMIT,
        AuditAction.PR_APPROVE,
        AuditAction.PR_REJECT,
        AuditAction.PR_REVISE,
        AuditAction.PR_CANCEL,
        AuditAction.PO_CREATE,
        AuditAction.PO_CONFIRM,
        AuditAction.PO_CANCEL,
        AuditAction.RECEIPT_POST,
        AuditAction.RECEIPT_REVERSE,
    }
)

#: Roles allowed to perform PO conversion / confirmation / creation.
_PO_EXEC_ROLES = frozenset({RoleCode.ADMIN.value, RoleCode.BUYER.value})

#: Roles allowed to perform PR approval.
_PR_APPROVE_ROLES = frozenset(
    {RoleCode.ADMIN.value, RoleCode.DEPT_MANAGER.value}
)

#: Roles surfaced the "待收货 PO" todo. WAREHOUSE posts receipts
#: (receipt:create); BUYER tracks confirmed-but-not-received deliveries of
#: their own POs; ADMIN supervises. APPLICANT / DEPT_MANAGER merely hold
#: po:view (to follow their own requisition chain) and have no receiving
#: duty, so they must NOT see a PO_RECEIVE todo item.
_PO_RECEIVE_TODO_ROLES = frozenset(
    {RoleCode.ADMIN.value, RoleCode.BUYER.value, RoleCode.WAREHOUSE.value}
)


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _today() -> date:
    return datetime.now().date()


def _pr_scope(db: Session, user: CurrentUser):
    """PR visible-range condition (None = full scope)."""
    return purchase_requisition_service.visible_pr_condition(db, user)


def _po_scope(db: Session, user: CurrentUser):
    """PO visible id subquery (None = full scope)."""
    return purchase_order_service.visible_po_id_stmt(db, user)


def _has_perm(user: CurrentUser, code: str) -> bool:
    return code in user.permissions


# ----------------------------------------------------------------------
# Summary KPI counters (single pass, pure SQL aggregates)
# ----------------------------------------------------------------------
def _count_pending_prs(db: Session, user: CurrentUser) -> int:
    """待审批 PR：用户可见范围内 status=PENDING（口径与 PR 列表一致）。

    无 pr:view 者不计（0），前端按 pr:approve 权限决定是否显示卡片。
    """
    if not _has_perm(user, "pr:view"):
        return 0
    cond = _pr_scope(db, user)
    stmt = select(func.count()).select_from(PurchaseRequisition).where(
        PurchaseRequisition.status == PrStatus.PENDING
    )
    if cond is not None:
        stmt = stmt.where(cond)
    return db.execute(stmt).scalar_one()


def _count_pending_purchase(db: Session, user: CurrentUser) -> int:
    """待转采购需求（distinct PR，Phase 11 §十四）。

    不按 status == APPROVED 简单计数：系统支持拆单，PR 可能在 APPROVED
    下仍留部分明细未转（converted_quantity < requested_quantity）。全转
    完后状态已由服务层原子翻为 CONVERTED，自然不计入。
    """
    if not _has_perm(user, "pr:view") or not _has_perm(user, "po:view"):
        return 0
    cond = _pr_scope(db, user)
    exists_item = (
        select(PurchaseRequisitionItem.id)
        .where(
            PurchaseRequisitionItem.pr_id == PurchaseRequisition.id,
            PurchaseRequisitionItem.converted_quantity
            < PurchaseRequisitionItem.requested_quantity,
        )
        .exists()
    )
    stmt = (
        select(func.count(func.distinct(PurchaseRequisition.id)))
        .select_from(PurchaseRequisition)
        .where(
            PurchaseRequisition.status == PrStatus.APPROVED,
            exists_item,
        )
    )
    if cond is not None:
        stmt = stmt.where(cond)
    return db.execute(stmt).scalar_one()


def _count_draft_pos(db: Session, user: CurrentUser) -> int:
    """待确认 PO（DRAFT）。

    口径 = 当前用户可执行「确认」的 DRAFT PO 数量：BUYER 只看自己名下
    （与 confirm 的对象级规则 buyer_or_admin 一致）；ADMIN 可越权确认任意
    DRAFT PO，故统计全部；其余角色无 po:confirm 权限返回 0（前端显隐由
    权限控制，见 docs/dashboard_metrics.md）。
    """
    if not _has_perm(user, "po:confirm"):
        return 0
    stmt = (
        select(func.count())
        .select_from(PurchaseOrder)
        .where(PurchaseOrder.status == PoStatus.DRAFT)
    )
    if user.role_code == RoleCode.BUYER.value:
        stmt = stmt.where(PurchaseOrder.buyer_id == user.id)
    elif user.role_code == RoleCode.ADMIN.value:
        pass  # admin 越权确认全部 DRAFT
    else:
        return 0
    return db.execute(stmt).scalar_one()


def _count_pending_pos(db: Session, user: CurrentUser) -> int:
    """待收货 PO：已确认但未全部收货，status IN (CONFIRMED, PARTIALLY_RECEIVED)
    （Phase 11 §七）。可见范围与 PO 列表页一致。
    """
    if not _has_perm(user, "po:view"):
        return 0
    sub = _po_scope(db, user)
    stmt = (
        select(func.count())
        .select_from(PurchaseOrder)
        .where(
            PurchaseOrder.status.in_(
                [PoStatus.CONFIRMED, PoStatus.PARTIALLY_RECEIVED]
            )
        )
    )
    if sub is not None:
        stmt = stmt.where(PurchaseOrder.id.in_(sub))
    return db.execute(stmt).scalar_one()


def _count_low_stock(db: Session, user: CurrentUser) -> int:
    """低库存：有策略行且 quantity < safety_stock（与库存页
    below_safety_stock=true 完全一致；无策略不算、等于不算）。"""
    if not _has_perm(user, "inventory:view"):
        return 0
    stmt = (
        select(func.count())
        .select_from(InventoryBalance)
        .join(
            InventoryPolicy,
            (InventoryPolicy.warehouse_id == InventoryBalance.warehouse_id)
            & (InventoryPolicy.material_id == InventoryBalance.material_id),
        )
        .where(InventoryBalance.quantity < InventoryPolicy.safety_stock)
    )
    return db.execute(stmt).scalar_one()


def _sum_inventory_amount(db: Session, user: CurrentUser) -> Decimal:
    """库存账面总金额 = SUM(inventory_balances.total_amount)（权威值，
    不按最新采购价 × 数量重算）。"""
    if not _has_perm(user, "inventory:view"):
        return Decimal("0")
    val = db.execute(
        select(func.coalesce(func.sum(InventoryBalance.total_amount), 0)).select_from(
            InventoryBalance
        )
    ).scalar_one()
    return Decimal(val)


def dashboard_summary(db: Session, user: CurrentUser) -> DashboardSummary:
    return DashboardSummary(
        pending_pr_count=_count_pending_prs(db, user),
        pending_purchase_count=_count_pending_purchase(db, user),
        draft_po_count=_count_draft_pos(db, user),
        pending_po_count=_count_pending_pos(db, user),
        low_stock_count=_count_low_stock(db, user),
        inventory_total_amount=_sum_inventory_amount(db, user),
    )


# ----------------------------------------------------------------------
# PR trend (apply_date; CANCELLED excluded; calendar gaps filled to 0)
# ----------------------------------------------------------------------
def pr_trend(
    db: Session, user: CurrentUser, *, days: int
) -> list[DashboardTrendPoint]:
    """PR 趋势：最近 ``days`` 天按 apply_date 分组（Phase 11 §十）。

    口径：排除 CANCELLED（展示有效采购需求趋势）；金额为 PR 头
    total_estimated_amount 的 SUM（Decimal，2 位）。缺日由后端补 0。
    """
    if not _has_perm(user, "pr:view"):
        return []
    end = _today()
    start = end - timedelta(days=days - 1)
    cond = _pr_scope(db, user)
    stmt = (
        select(
            PurchaseRequisition.apply_date,
            func.count(),
            func.coalesce(func.sum(PurchaseRequisition.total_estimated_amount), 0),
        )
        .where(
            PurchaseRequisition.apply_date >= start,
            PurchaseRequisition.apply_date <= end,
            PurchaseRequisition.status != PrStatus.CANCELLED,
        )
        .group_by(PurchaseRequisition.apply_date)
    )
    if cond is not None:
        stmt = stmt.where(cond)
    rows = {
        d: (int(c), Decimal(a))
        for d, c, a in db.execute(stmt).all()
    }
    out: list[DashboardTrendPoint] = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        count, amount = rows.get(day, (0, Decimal("0")))
        out.append(
            DashboardTrendPoint(date=day, count=count, amount=amount)
        )
    return out


# ----------------------------------------------------------------------
# PO status distribution (all defined statuses incl. zero)
# ----------------------------------------------------------------------
def po_status_distribution(
    db: Session, user: CurrentUser
) -> list[DashboardStatusCount]:
    """PO 状态分布（Phase 11 §十一）。返回全部定义状态，count=0 也返回，
    保证前端图表结构稳定。可见范围与 PO 列表页一致。"""
    if not _has_perm(user, "po:view"):
        return [DashboardStatusCount(status=s, count=0) for s in PoStatus]
    sub = _po_scope(db, user)
    stmt = (
        select(PurchaseOrder.status, func.count())
        .select_from(PurchaseOrder)
        .group_by(PurchaseOrder.status)
    )
    if sub is not None:
        stmt = stmt.where(PurchaseOrder.id.in_(sub))
    counts = dict(db.execute(stmt).all())
    return [
        DashboardStatusCount(status=s, count=counts.get(s, 0))
        for s in PoStatus
    ]


# ----------------------------------------------------------------------
# Low-stock top list (shortage desc)
# ----------------------------------------------------------------------
def low_stock_list(
    db: Session, user: CurrentUser, *, limit: int
) -> list[LowStockRow]:
    """低库存 Top N（Phase 11 §十二）。缺口 = safety_stock - quantity > 0，
    按绝对缺口倒序。语义与库存页 below_safety_stock=true 及 low_stock_count
    完全一致。"""
    if not _has_perm(user, "inventory:view"):
        return []
    stmt = (
        select(
            InventoryBalance.warehouse_id,
            Warehouse.warehouse_code,
            Warehouse.warehouse_name,
            InventoryBalance.material_id,
            Material.material_code,
            Material.material_name,
            Material.unit,
            InventoryBalance.quantity,
            InventoryPolicy.safety_stock,
            (InventoryPolicy.safety_stock - InventoryBalance.quantity).label(
                "shortage"
            ),
        )
        .join(Warehouse, Warehouse.id == InventoryBalance.warehouse_id)
        .join(Material, Material.id == InventoryBalance.material_id)
        .join(
            InventoryPolicy,
            (InventoryPolicy.warehouse_id == InventoryBalance.warehouse_id)
            & (InventoryPolicy.material_id == InventoryBalance.material_id),
        )
        .where(InventoryBalance.quantity < InventoryPolicy.safety_stock)
        .order_by((InventoryPolicy.safety_stock - InventoryBalance.quantity).desc())
        .limit(limit)
    )
    out: list[LowStockRow] = []
    for row in db.execute(stmt).all():
        out.append(
            LowStockRow(
                warehouse_id=row.warehouse_id,
                warehouse_code=row.warehouse_code,
                warehouse_name=row.warehouse_name,
                material_id=row.material_id,
                material_code=row.material_code,
                material_name=row.material_name,
                unit=row.unit,
                quantity=row.quantity,
                safety_stock=row.safety_stock,
                shortage_quantity=row.shortage,
            )
        )
    return out


# ----------------------------------------------------------------------
# Todos (backend only emits type + count; route/label is a frontend map)
# ----------------------------------------------------------------------
def dashboard_todos(db: Session, user: CurrentUser) -> list[TodoItem]:
    """按角色/权限聚合待办（Phase 11 §十三）。无对应待办的角色自然不出现
    对应条目（前端按 permission 控制，后端按角色语义返回）。"""
    todos: list[TodoItem] = []
    if user.role_code in _PR_APPROVE_ROLES:
        n = _count_pending_prs(db, user)
        if n > 0:
            todos.append(TodoItem(type="PR_APPROVAL", count=n))
    if user.role_code in _PO_EXEC_ROLES:
        n = _count_pending_purchase(db, user)
        if n > 0:
            todos.append(TodoItem(type="PR_TO_PO", count=n))
        n = _count_draft_pos(db, user)
        if n > 0:
            todos.append(TodoItem(type="PO_CONFIRM", count=n))
    if user.role_code in _PO_RECEIVE_TODO_ROLES:
        n = _count_pending_pos(db, user)
        if n > 0:
            todos.append(TodoItem(type="PO_RECEIVE", count=n))
    return todos


# ----------------------------------------------------------------------
# Recent business activities (operation_logs, key actions only)
# ----------------------------------------------------------------------
def recent_activities(
    db: Session, user: CurrentUser, *, limit: int
) -> list[ActivityItem]:
    """最近关键业务事件（Phase 11 §十六）。来源 operation_logs（不建新表），
    只筛选 _RECENT_ACTIONS 关键动作。operator 名字取日志快照；描述缺失时
    前端以动作 + 单据号拼装，保证时间轴可读。"""
    if not _has_perm(user, "dashboard:view"):
        return []
    rows = db.execute(
        select(OperationLog)
        .where(OperationLog.action.in_(_RECENT_ACTIONS))
        .order_by(OperationLog.id.desc())
        .limit(limit)
    ).scalars().all()
    return [
        ActivityItem(
            id=log.id,
            action=log.action,
            operator_name=log.username_snapshot,
            document_type=log.document_type,
            document_no=log.document_no,
            description=log.description,
            created_at=log.created_at,
        )
        for log in rows
    ]


# ----------------------------------------------------------------------
# Recent inventory movements (append-only ledger tail)
# ----------------------------------------------------------------------
def inventory_activities(
    db: Session, user: CurrentUser, *, limit: int
) -> list[InventoryActivityItem]:
    """最近库存动态（Phase 11 §十七）：inventory_transactions 最近 N 条。
    带符号 quantity（入库正、冲销负）；一次性解析来源单据号避免 N+1。"""
    if not _has_perm(user, "inventory_txn:view"):
        return []
    rows = db.execute(
        select(
            InventoryTransaction,
            Material.material_code,
            Material.material_name,
            Material.unit,
            Warehouse.warehouse_name,
        )
        .join(Material, Material.id == InventoryTransaction.material_id)
        .join(Warehouse, Warehouse.id == InventoryTransaction.warehouse_id)
        .order_by(InventoryTransaction.id.desc())
        .limit(limit)
    ).all()
    source_ids = {
        t.source_id
        for t, _mc, _mn, _u, _w in rows
        if t.source_type
        in (TxnSourceType.PURCHASE_RECEIPT, TxnSourceType.PURCHASE_RECEIPT_REVERSAL)
        and t.source_id is not None
    }
    ref_map: dict[int, str] = {}
    if source_ids:
        from app.models import PurchaseReceipt

        ref_map = dict(
            db.execute(
                select(PurchaseReceipt.id, PurchaseReceipt.receipt_no).where(
                    PurchaseReceipt.id.in_(source_ids)
                )
            ).all()
        )
    out: list[InventoryActivityItem] = []
    for txn, mat_code, mat_name, unit, wh_name in rows:
        out.append(
            InventoryActivityItem(
                id=txn.id,
                txn_no=txn.txn_no,
                transaction_type=txn.transaction_type,
                material_id=txn.material_id,
                material_code=mat_code,
                material_name=mat_name,
                unit=unit,
                warehouse_id=txn.warehouse_id,
                warehouse_name=wh_name,
                quantity=txn.quantity,
                source_type=txn.source_type.value if txn.source_type else None,
                source_id=txn.source_id,
                reference_no=ref_map.get(txn.source_id) if txn.source_id else None,
                transaction_at=txn.transaction_at,
            )
        )
    return out
