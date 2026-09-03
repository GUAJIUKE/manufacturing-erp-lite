"""Dashboard / management-cockpit read schemas (Phase 11).

Every value returned here is computed by the backend from real business
data (SQL aggregates) — the frontend never totals rows itself. Amounts are
``Decimal`` fields: FastAPI serializes them as strings, so the client must
not round-trip them through JS ``float`` for business display.

Metric definitions & scope rules live in ``docs/dashboard_metrics.md``;
this module only carries wire types.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from app.utils.enums import AuditAction, PoStatus, TxnType


class DashboardSummary(BaseModel):
    """Row-1 KPIs (role-aware; ``None`` scope means the caller sees all).

    ``draft_po_count`` / ``pending_purchase_count`` are buyer-oriented and
    are 0 for roles that cannot perform the action (UI hides the card by
    permission, see the metrics doc).
    """

    #: 待审批采购申请数（用户可见范围内 status=PENDING）
    pending_pr_count: int
    #: 待转采购需求：APPROVED 且存在 converted<requested 明细的 PR 数（distinct）
    pending_purchase_count: int
    #: 待确认采购订单（DRAFT 且归属当前用户）
    draft_po_count: int
    #: 待收货 PO：status IN (CONFIRMED, PARTIALLY_RECEIVED)（可见范围）
    pending_po_count: int
    #: 低库存物料（有策略且 quantity < safety_stock）
    low_stock_count: int
    #: 库存账面总金额（SUM(inventory_balances.total_amount)，Decimal-as-string）
    inventory_total_amount: Decimal


class DashboardTrendPoint(BaseModel):
    """PR 趋势单日点（apply_date 口径，排除 CANCELLED，缺日由后端补 0）。"""

    date: date
    count: int
    amount: Decimal


class DashboardStatusCount(BaseModel):
    """PO 状态分布单行；接口返回全部定义状态（含 count=0）。"""

    status: PoStatus
    count: int


class LowStockRow(BaseModel):
    """低库存预警行（缺口 = safety_stock - quantity > 0）。"""

    warehouse_id: int
    warehouse_code: str
    warehouse_name: str
    material_id: int
    material_code: str
    material_name: str
    unit: str
    quantity: Decimal
    safety_stock: Decimal
    shortage_quantity: Decimal


class TodoItem(BaseModel):
    """待办聚合项。后端只给 type + count，route/label 由前端映射
    （后端不耦合 Vue Router，Phase 11 §十三）。"""

    type: str
    count: int


class ActivityItem(BaseModel):
    """最近业务动态（operation_logs 关键动作，Phase 11 §十六）。"""

    id: int
    action: AuditAction
    operator_name: str | None = None
    document_type: str | None = None
    document_no: str | None = None
    description: str | None = None
    created_at: datetime


class InventoryActivityItem(BaseModel):
    """最近库存动态（inventory_transactions 最近 N 条，§十七）。"""

    id: int
    txn_no: str
    transaction_type: TxnType
    material_id: int
    material_code: str
    material_name: str
    unit: str | None = None
    warehouse_id: int
    warehouse_name: str
    #: 带符号：入库正、冲销负
    quantity: Decimal
    source_type: str | None = None
    source_id: int | None = None
    reference_no: str | None = None
    transaction_at: datetime
