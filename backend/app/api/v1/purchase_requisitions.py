"""Purchase requisition endpoints (Phase 6).

Business-document surface: create / list / detail / update / submit / cancel.

* No DELETE: a PR is cancelled (DRAFT -> CANCELLED), never deleted
  (Phase 6 §十).
* No status writes in the API layer — every status change goes through the
  service's transition map (Phase 6 §十二).
* Object-level checks (owner-only / admin capability) live in the service,
  RBAC guards below are only the first layer (Phase 6 §十四).
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.v1.deps import CurrentUserDep, DbDep, require_perm
from app.core.response import ApiResponse, PageResult
from app.models import Department, PurchaseRequisition, User
from app.schemas.purchase_requisition import (
    PurchaseRequisitionCreate,
    PurchaseRequisitionItemOut,
    PurchaseRequisitionOut,
    PurchaseRequisitionUpdate,
)
from app.services import purchase_requisition_service as pr_service
from app.utils.enums import PrStatus

router = APIRouter(prefix="/purchase-requisitions", tags=["purchase-requisitions"])


def _audit_ctx(request: Request, user: CurrentUserDep) -> dict:
    return {
        "user": user,
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
        "request_id": request.headers.get("x-request-id"),
    }


def _to_out(db: Session, pr: PurchaseRequisition, *, with_items: bool = True) -> PurchaseRequisitionOut:
    applicant = db.get(User, pr.applicant_id)
    dept = db.get(Department, pr.department_id)
    items = []
    if with_items:
        for it in pr.items:
            mat = it.material
            items.append(
                PurchaseRequisitionItemOut(
                    id=it.id,
                    line_no=it.line_no,
                    material_id=it.material_id,
                    material_code=mat.material_code if mat else None,
                    material_name=mat.material_name if mat else None,
                    requested_quantity=it.requested_quantity,
                    converted_quantity=it.converted_quantity,
                    estimated_unit_price=it.estimated_unit_price,
                    estimated_amount=it.estimated_amount,
                    required_date=it.required_date,
                    remark=it.remark,
                )
            )
    return PurchaseRequisitionOut(
        id=pr.id,
        pr_no=pr.pr_no,
        applicant_id=pr.applicant_id,
        applicant_name=(applicant.real_name or applicant.username) if applicant else None,
        department_id=pr.department_id,
        department_name=dept.dept_name if dept else None,
        apply_date=pr.apply_date,
        reason=pr.reason,
        status=pr.status,
        total_estimated_amount=pr.total_estimated_amount,
        submitted_at=pr.submitted_at,
        version=pr.version,
        remark=pr.remark,
        created_at=pr.created_at,
        updated_at=pr.updated_at,
        items=items,
    )


@router.get("", summary="采购申请列表（分页/筛选）")
def list_prs(
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("pr:view")),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    pr_no: str | None = Query(None, description="PR 编号模糊搜索"),
    applicant: str | None = Query(None, description="申请人用户名/姓名模糊搜索"),
    department_id: int | None = Query(None, description="申请部门精确筛选"),
    status: PrStatus | None = None,
    apply_date_from: date | None = Query(None, description="申请日期起（含）"),
    apply_date_to: date | None = Query(None, description="申请日期止（含）"),
) -> ApiResponse[PageResult[PurchaseRequisitionOut]]:
    rows, total = pr_service.list_prs(
        db,
        user=user,
        page=page,
        page_size=page_size,
        pr_no=pr_no,
        applicant=applicant,
        department_id=department_id,
        status=status,
        apply_date_from=apply_date_from,
        apply_date_to=apply_date_to,
    )
    return ApiResponse.ok(
        PageResult(
            items=[_to_out(db, pr, with_items=False) for pr in rows],
            total=total,
            page=page,
            page_size=page_size,
        )
    )


@router.post("", summary="创建采购申请（自动编号 PR-YYYYMMDD-0001）")
def create_pr(
    payload: PurchaseRequisitionCreate,
    request: Request,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("pr:create")),
) -> ApiResponse[PurchaseRequisitionOut]:
    pr = pr_service.create_pr(db, payload, **_audit_ctx(request, user))
    db.commit()
    return ApiResponse.ok(_to_out(db, pr), message="创建成功")


@router.get("/{pr_id}", summary="采购申请详情")
def get_pr(
    pr_id: int,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("pr:view")),
) -> ApiResponse[PurchaseRequisitionOut]:
    pr = pr_service.get_pr(db, pr_id, user=user)
    return ApiResponse.ok(_to_out(db, pr))


@router.put("/{pr_id}", summary="编辑采购申请（仅 DRAFT，乐观锁 version）")
def update_pr(
    pr_id: int,
    payload: PurchaseRequisitionUpdate,
    request: Request,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("pr:update")),
) -> ApiResponse[PurchaseRequisitionOut]:
    pr = pr_service.update_pr(db, pr_id, payload, **_audit_ctx(request, user))
    db.commit()
    return ApiResponse.ok(_to_out(db, pr), message="更新成功")


@router.post("/{pr_id}/submit", summary="提交采购申请（DRAFT → PENDING）")
def submit_pr(
    pr_id: int,
    request: Request,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("pr:submit")),
) -> ApiResponse[PurchaseRequisitionOut]:
    pr = pr_service.submit_pr(db, pr_id, **_audit_ctx(request, user))
    db.commit()
    return ApiResponse.ok(_to_out(db, pr), message="提交成功")


@router.post("/{pr_id}/cancel", summary="取消采购申请（DRAFT → CANCELLED）")
def cancel_pr(
    pr_id: int,
    request: Request,
    db: DbDep,
    user: CurrentUserDep,
    _guard: None = Depends(require_perm("pr:cancel")),
) -> ApiResponse[PurchaseRequisitionOut]:
    pr = pr_service.cancel_pr(db, pr_id, **_audit_ctx(request, user))
    db.commit()
    return ApiResponse.ok(_to_out(db, pr), message="已取消")
