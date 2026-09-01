"""Warehouse master-data endpoints (require warehouse:* permissions)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.api.v1.deps import CurrentUserDep, DbDep, require_perm
from app.core.response import ApiResponse, PageResult
from app.schemas.warehouse import WarehouseCreate, WarehouseOut, WarehouseUpdate
from app.services import warehouse_service
from app.utils.enums import ActiveStatus

router = APIRouter(prefix="/warehouses", tags=["warehouses"])


def _to_out(w) -> WarehouseOut:
    return WarehouseOut(
        id=w.id,
        warehouse_code=w.warehouse_code,
        warehouse_name=w.warehouse_name,
        status=w.status,
        remark=w.remark,
        created_at=w.created_at,
        updated_at=w.updated_at,
    )


def _audit_ctx(request: Request, user: CurrentUserDep) -> dict:
    return {
        "username": user.username,
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
        "request_id": request.headers.get("x-request-id"),
    }


@router.get("", summary="仓库列表（分页/编码/名称/状态）")
def list_warehouses(
    db: DbDep,
    _guard: None = Depends(require_perm("warehouse:view")),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    code: str | None = Query(None, description="warehouse_code 搜索"),
    name: str | None = Query(None, description="warehouse_name 模糊搜索"),
    status: ActiveStatus | None = None,
) -> ApiResponse[PageResult[WarehouseOut]]:
    rows, total = warehouse_service.list_warehouses(
        db, page=page, page_size=page_size, code=code, name=name, status=status
    )
    return ApiResponse.ok(
        PageResult(items=[_to_out(w) for w in rows], total=total, page=page, page_size=page_size)
    )


@router.post("", summary="创建仓库（自动生成 WH 编码）")
def create_warehouse(
    payload: WarehouseCreate,
    request: Request,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("warehouse:create")),
) -> ApiResponse[WarehouseOut]:
    warehouse = warehouse_service.create_warehouse(db, payload, **_audit_ctx(request, user))
    db.commit()
    return ApiResponse.ok(_to_out(warehouse), message="创建成功")


@router.get("/{warehouse_id}", summary="仓库详情")
def get_warehouse(
    warehouse_id: int,
    db: DbDep,
    _guard: None = Depends(require_perm("warehouse:view")),
) -> ApiResponse[WarehouseOut]:
    warehouse = warehouse_service.get_warehouse(db, warehouse_id)
    return ApiResponse.ok(_to_out(warehouse))


@router.put("/{warehouse_id}", summary="更新仓库（warehouse_code 不可修改）")
def update_warehouse(
    warehouse_id: int,
    payload: WarehouseUpdate,
    request: Request,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("warehouse:update")),
) -> ApiResponse[WarehouseOut]:
    warehouse = warehouse_service.update_warehouse(db, warehouse_id, payload, **_audit_ctx(request, user))
    db.commit()
    return ApiResponse.ok(_to_out(warehouse), message="更新成功")


@router.post("/{warehouse_id}/disable", summary="停用仓库（存在非零库存时禁止）")
def disable_warehouse(
    warehouse_id: int,
    request: Request,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("warehouse:delete")),
) -> ApiResponse[WarehouseOut]:
    warehouse = warehouse_service.disable_warehouse(db, warehouse_id, **_audit_ctx(request, user))
    db.commit()
    return ApiResponse.ok(_to_out(warehouse), message="已停用")


@router.post("/{warehouse_id}/enable", summary="启用仓库")
def enable_warehouse(
    warehouse_id: int,
    request: Request,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("warehouse:update")),
) -> ApiResponse[WarehouseOut]:
    warehouse = warehouse_service.enable_warehouse(db, warehouse_id, **_audit_ctx(request, user))
    db.commit()
    return ApiResponse.ok(_to_out(warehouse), message="已启用")
