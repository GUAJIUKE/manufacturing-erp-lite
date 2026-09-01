"""Inventory policy endpoints (require inventory_policy:* permissions)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.api.v1.deps import CurrentUserDep, DbDep, require_perm
from app.core.response import ApiResponse, PageResult
from app.schemas.inventory_policy import (
    InventoryPolicyCreate,
    InventoryPolicyOut,
    InventoryPolicyUpdate,
)
from app.services import inventory_policy_service

router = APIRouter(prefix="/inventory-policies", tags=["inventory-policies"])


def _to_out(p) -> InventoryPolicyOut:
    return InventoryPolicyOut(
        id=p.id,
        warehouse_id=p.warehouse_id,
        material_id=p.material_id,
        safety_stock=p.safety_stock,
        min_stock=p.min_stock,
        reorder_point=p.reorder_point,
        max_stock=p.max_stock,
        remark=p.remark,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


def _audit_ctx(request: Request, user: CurrentUserDep) -> dict:
    return {
        "username": user.username,
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
        "request_id": request.headers.get("x-request-id"),
    }


@router.get("", summary="库存策略列表（可按 warehouse_id / material_id 筛选）")
def list_policies(
    db: DbDep,
    _guard: None = Depends(require_perm("inventory_policy:view")),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    warehouse_id: int | None = Query(None, gt=0),
    material_id: int | None = Query(None, gt=0),
) -> ApiResponse[PageResult[InventoryPolicyOut]]:
    rows, total = inventory_policy_service.list_policies(
        db,
        page=page,
        page_size=page_size,
        warehouse_id=warehouse_id,
        material_id=material_id,
    )
    return ApiResponse.ok(
        PageResult(items=[_to_out(p) for p in rows], total=total, page=page, page_size=page_size)
    )


@router.post("", summary="创建库存策略")
def create_policy(
    payload: InventoryPolicyCreate,
    request: Request,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("inventory_policy:create")),
) -> ApiResponse[InventoryPolicyOut]:
    policy = inventory_policy_service.create_policy(db, payload, **_audit_ctx(request, user))
    db.commit()
    return ApiResponse.ok(_to_out(policy), message="创建成功")


@router.get("/{policy_id}", summary="库存策略详情")
def get_policy(
    policy_id: int,
    db: DbDep,
    _guard: None = Depends(require_perm("inventory_policy:view")),
) -> ApiResponse[InventoryPolicyOut]:
    policy = inventory_policy_service.get_policy(db, policy_id)
    return ApiResponse.ok(_to_out(policy))


@router.put("/{policy_id}", summary="更新库存策略")
def update_policy(
    policy_id: int,
    payload: InventoryPolicyUpdate,
    request: Request,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("inventory_policy:update")),
) -> ApiResponse[InventoryPolicyOut]:
    policy = inventory_policy_service.update_policy(db, policy_id, payload, **_audit_ctx(request, user))
    db.commit()
    return ApiResponse.ok(_to_out(policy), message="更新成功")
