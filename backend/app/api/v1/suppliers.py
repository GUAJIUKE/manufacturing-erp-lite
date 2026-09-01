"""Supplier master-data endpoints (require supplier:* permissions)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.api.v1.deps import CurrentUserDep, DbDep, require_perm
from app.core.response import ApiResponse, PageResult
from app.schemas.supplier import SupplierCreate, SupplierOut, SupplierUpdate
from app.services import supplier_service
from app.utils.enums import ActiveStatus

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


def _to_out(s) -> SupplierOut:
    return SupplierOut(
        id=s.id,
        supplier_code=s.supplier_code,
        supplier_name=s.supplier_name,
        contact_person=s.contact_person,
        phone=s.phone,
        email=s.email,
        address=s.address,
        status=s.status,
        remark=s.remark,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


def _audit_ctx(request: Request, user: CurrentUserDep) -> dict:
    return {
        "username": user.username,
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
        "request_id": request.headers.get("x-request-id"),
    }


@router.get("", summary="供应商列表（分页/编码/名称/状态）")
def list_suppliers(
    db: DbDep,
    _guard: None = Depends(require_perm("supplier:view")),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    code: str | None = Query(None, description="supplier_code 搜索"),
    name: str | None = Query(None, description="supplier_name 模糊搜索"),
    status: ActiveStatus | None = None,
) -> ApiResponse[PageResult[SupplierOut]]:
    rows, total = supplier_service.list_suppliers(
        db, page=page, page_size=page_size, code=code, name=name, status=status
    )
    return ApiResponse.ok(
        PageResult(items=[_to_out(s) for s in rows], total=total, page=page, page_size=page_size)
    )


@router.post("", summary="创建供应商（自动生成 SUP 编码）")
def create_supplier(
    payload: SupplierCreate,
    request: Request,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("supplier:create")),
) -> ApiResponse[SupplierOut]:
    supplier = supplier_service.create_supplier(db, payload, **_audit_ctx(request, user))
    db.commit()
    return ApiResponse.ok(_to_out(supplier), message="创建成功")


@router.get("/{supplier_id}", summary="供应商详情")
def get_supplier(
    supplier_id: int,
    db: DbDep,
    _guard: None = Depends(require_perm("supplier:view")),
) -> ApiResponse[SupplierOut]:
    supplier = supplier_service.get_supplier(db, supplier_id)
    return ApiResponse.ok(_to_out(supplier))


@router.put("/{supplier_id}", summary="更新供应商（supplier_code 不可修改）")
def update_supplier(
    supplier_id: int,
    payload: SupplierUpdate,
    request: Request,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("supplier:update")),
) -> ApiResponse[SupplierOut]:
    supplier = supplier_service.update_supplier(db, supplier_id, payload, **_audit_ctx(request, user))
    db.commit()
    return ApiResponse.ok(_to_out(supplier), message="更新成功")


@router.post("/{supplier_id}/disable", summary="停用供应商")
def disable_supplier(
    supplier_id: int,
    request: Request,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("supplier:delete")),
) -> ApiResponse[SupplierOut]:
    supplier = supplier_service.disable_supplier(db, supplier_id, **_audit_ctx(request, user))
    db.commit()
    return ApiResponse.ok(_to_out(supplier), message="已停用")


@router.post("/{supplier_id}/enable", summary="启用供应商")
def enable_supplier(
    supplier_id: int,
    request: Request,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("supplier:update")),
) -> ApiResponse[SupplierOut]:
    supplier = supplier_service.enable_supplier(db, supplier_id, **_audit_ctx(request, user))
    db.commit()
    return ApiResponse.ok(_to_out(supplier), message="已启用")
