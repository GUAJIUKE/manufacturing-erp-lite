"""Material master-data endpoints (require material:* permissions).

No DELETE endpoint: master data is disabled, never physically deleted
(Phase 5 §六 — business documents must remain queryable).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.api.v1.deps import CurrentUserDep, DbDep, require_perm
from app.core.response import ApiResponse, PageResult
from app.schemas.material import MaterialCreate, MaterialOut, MaterialUpdate
from app.services import material_service
from app.utils.enums import ActiveStatus

router = APIRouter(prefix="/materials", tags=["materials"])


def _to_out(m) -> MaterialOut:
    return MaterialOut(
        id=m.id,
        material_code=m.material_code,
        material_name=m.material_name,
        category=m.category,
        specification=m.specification,
        unit=m.unit,
        status=m.status,
        remark=m.remark,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def _audit_ctx(request: Request, user: CurrentUserDep) -> dict:
    return {
        "username": user.username,
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
        "request_id": request.headers.get("x-request-id"),
    }


@router.get("", summary="物料列表（分页/编码/名称/分类/状态）")
def list_materials(
    db: DbDep,
    _guard: None = Depends(require_perm("material:view")),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    code: str | None = Query(None, description="material_code 搜索"),
    name: str | None = Query(None, description="material_name 模糊搜索"),
    category: str | None = Query(None, description="分类精确筛选"),
    status: ActiveStatus | None = None,
) -> ApiResponse[PageResult[MaterialOut]]:
    rows, total = material_service.list_materials(
        db,
        page=page,
        page_size=page_size,
        code=code,
        name=name,
        category=category,
        status=status,
    )
    return ApiResponse.ok(
        PageResult(items=[_to_out(m) for m in rows], total=total, page=page, page_size=page_size)
    )


@router.post("", summary="创建物料（自动生成 MAT 编码）")
def create_material(
    payload: MaterialCreate,
    request: Request,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("material:create")),
) -> ApiResponse[MaterialOut]:
    material = material_service.create_material(db, payload, **_audit_ctx(request, user))
    db.commit()
    return ApiResponse.ok(_to_out(material), message="创建成功")


@router.get("/{material_id}", summary="物料详情")
def get_material(
    material_id: int,
    db: DbDep,
    _guard: None = Depends(require_perm("material:view")),
) -> ApiResponse[MaterialOut]:
    material = material_service.get_material(db, material_id)
    return ApiResponse.ok(_to_out(material))


@router.put("/{material_id}", summary="更新物料（material_code 不可修改）")
def update_material(
    material_id: int,
    payload: MaterialUpdate,
    request: Request,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("material:update")),
) -> ApiResponse[MaterialOut]:
    material = material_service.update_material(db, material_id, payload, **_audit_ctx(request, user))
    db.commit()
    return ApiResponse.ok(_to_out(material), message="更新成功")


@router.post("/{material_id}/disable", summary="停用物料")
def disable_material(
    material_id: int,
    request: Request,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("material:delete")),
) -> ApiResponse[MaterialOut]:
    material = material_service.disable_material(db, material_id, **_audit_ctx(request, user))
    db.commit()
    return ApiResponse.ok(_to_out(material), message="已停用")


@router.post("/{material_id}/enable", summary="启用物料")
def enable_material(
    material_id: int,
    request: Request,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("material:update")),
) -> ApiResponse[MaterialOut]:
    material = material_service.enable_material(db, material_id, **_audit_ctx(request, user))
    db.commit()
    return ApiResponse.ok(_to_out(material), message="已启用")
