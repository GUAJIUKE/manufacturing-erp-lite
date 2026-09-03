"""Dashboard / management-cockpit endpoints (Phase 11).

Read-only aggregation over the real business data. Every number honours
the same object-level scopes as the list pages (see dashboard_service);
the frontend only renders what the backend computes.

Endpoints:

* ``GET /dashboard/summary``                 row-1 KPI counters
* ``GET /dashboard/pr-trend?days=30``        PR trend (7/30/90, apply_date)
* ``GET /dashboard/po-status-distribution``  PO status donut (all states)
* ``GET /dashboard/low-stock?limit=5``       low-stock top list
* ``GET /dashboard/todos``                   role-aware todo items
* ``GET /dashboard/recent-activities``       key business events timeline
* ``GET /dashboard/inventory-activities``    recent inventory movements

All endpoints require ``dashboard:view`` (seeded for every demo role).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import (
    DbDep,
    get_current_user,
    get_role_permissions,
    require_perm,
)
from app.core.response import ApiResponse
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
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _principal(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: DbDep,
) -> CurrentUser:
    """Attach the role's permission codes (mirrors /auth/me). Dashboard
    KPI visibility is permission-driven, so the service needs real perms."""
    perms = sorted(get_role_permissions(db, user.role_id))
    return user.model_copy(update={"permissions": perms})


PrincipalDep = Annotated[CurrentUser, Depends(_principal)]


@router.get("/summary", summary="Dashboard 核心 KPI（角色感知）")
def summary(
    db: DbDep,
    user: PrincipalDep,
    _guard: None = Depends(require_perm("dashboard:view")),
) -> ApiResponse[DashboardSummary]:
    return ApiResponse.ok(dashboard_service.dashboard_summary(db, user))


@router.get("/pr-trend", summary="采购申请趋势（apply_date，排除 CANCELLED）")
def pr_trend(
    db: DbDep,
    user: PrincipalDep,
    _guard: None = Depends(require_perm("dashboard:view")),
    days: int = Query(30, ge=1, le=365, description="最近天数：7 / 30 / 90，默认 30"),
) -> ApiResponse[list[DashboardTrendPoint]]:
    return ApiResponse.ok(dashboard_service.pr_trend(db, user, days=days))


@router.get("/po-status-distribution", summary="采购订单状态分布（全状态含 0）")
def po_status_distribution(
    db: DbDep,
    user: PrincipalDep,
    _guard: None = Depends(require_perm("dashboard:view")),
) -> ApiResponse[list[DashboardStatusCount]]:
    return ApiResponse.ok(dashboard_service.po_status_distribution(db, user))


@router.get("/low-stock", summary="低库存预警 Top N（缺口倒序）")
def low_stock(
    db: DbDep,
    user: PrincipalDep,
    _guard: None = Depends(require_perm("dashboard:view")),
    limit: int = Query(5, ge=1, le=50, description="返回条数，默认 5"),
) -> ApiResponse[list[LowStockRow]]:
    return ApiResponse.ok(dashboard_service.low_stock_list(db, user, limit=limit))


@router.get("/todos", summary="待办事项（后端只给 type+count）")
def todos(
    db: DbDep,
    user: PrincipalDep,
    _guard: None = Depends(require_perm("dashboard:view")),
) -> ApiResponse[list[TodoItem]]:
    return ApiResponse.ok(dashboard_service.dashboard_todos(db, user))


@router.get("/recent-activities", summary="最近采购动态（关键业务事件）")
def recent_activities(
    db: DbDep,
    user: PrincipalDep,
    _guard: None = Depends(require_perm("dashboard:view")),
    limit: int = Query(10, ge=1, le=50, description="返回条数，默认 10"),
) -> ApiResponse[list[ActivityItem]]:
    return ApiResponse.ok(
        dashboard_service.recent_activities(db, user, limit=limit)
    )


@router.get("/inventory-activities", summary="最近库存动态（带符号流水）")
def inventory_activities(
    db: DbDep,
    user: PrincipalDep,
    _guard: None = Depends(require_perm("dashboard:view")),
    limit: int = Query(5, ge=1, le=50, description="返回条数，默认 5"),
) -> ApiResponse[list[InventoryActivityItem]]:
    return ApiResponse.ok(
        dashboard_service.inventory_activities(db, user, limit=limit)
    )
