"""Purchase requisition service (Phase 6).

Business-document rules, NOT plain CRUD:

* ``pr_no`` is server-generated per day (PR-YYYYMMDD-0001, Phase 6 §三).
* ``applicant_id`` / ``department_id`` are snapshots from the creating user's
  current department — never derived from the user's current department
  afterwards (Phase 6 §二).
* Status changes only via the central transition map below; the API layer
  never writes ``status`` directly (Phase 6 §十二).
* Money is always recomputed server-side through ``app.utils.money``
  (ROUND_HALF_UP, 2 decimals); client-sent amounts are ignored (Phase 6 §八).
* Updates / submit / cancel use atomic conditional UPDATEs so concurrent
  editors cannot overwrite each other (optimistic lock, Phase 6 §十一).
* Object-level rule: a plain applicant only touches their own PRs; ADMIN
  keeps management capability (Phase 6 §六 / §十四).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.exceptions import (
    ConflictException,
    ErrorCode,
    InvalidStatusTransitionException,
    NotFoundException,
    PermissionDeniedException,
    ValidationException,
)
from app.models import Department, Material, PurchaseRequisition, PurchaseRequisitionItem, User
from app.schemas.auth import CurrentUser
from app.schemas.purchase_requisition import (
    PurchaseRequisitionCreate,
    PurchaseRequisitionUpdate,
)
from app.services import audit_service, numbering_service
from app.utils import money
from app.utils.enums import (
    ActiveStatus,
    AuditAction,
    DeptStatus,
    PrStatus,
    RoleCode,
    SequenceKey,
)

_MODULE = "pr"
_DOCUMENT_TYPE = "PURCHASE_REQUISITION"

# ----------------------------------------------------------------------
# Status machine (Phase 6 §十二): the single source of truth.
# Phase 6 only implements DRAFT -> PENDING (submit) and DRAFT -> CANCELLED
# (cancel). APPROVED / REJECTED transitions arrive with Phase 7.
# ----------------------------------------------------------------------
_TRANSITIONS: dict[PrStatus, frozenset[PrStatus]] = {
    PrStatus.DRAFT: frozenset({PrStatus.PENDING, PrStatus.CANCELLED}),
}


def _assert_transition(pr: PurchaseRequisition, target: PrStatus) -> None:
    allowed = _TRANSITIONS.get(pr.status, frozenset())
    if target not in allowed:
        raise InvalidStatusTransitionException(
            f"采购申请状态不允许从 {pr.status.value} 变更为 {target.value}",
            code=ErrorCode.PR_INVALID_STATUS_TRANSITION,
        )


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _load(db: Session, pr_id: int) -> PurchaseRequisition:
    pr = db.get(PurchaseRequisition, pr_id)
    if pr is None:
        raise NotFoundException("采购申请不存在", code=ErrorCode.PR_NOT_FOUND)
    return pr


def _assert_material_active(db: Session, material_id: int) -> Material:
    material = db.get(Material, material_id)
    if material is None:
        raise NotFoundException("物料不存在", code=ErrorCode.PR_ITEM_NOT_FOUND)
    if material.status != ActiveStatus.ACTIVE:
        raise ConflictException(
            f"物料 {material.material_code} 已停用，不能用于采购申请",
            code=ErrorCode.MASTER_DATA_DISABLED,
        )
    return material


def _can_manage(pr: PurchaseRequisition, user: CurrentUser) -> bool:
    """Object-level rule: owner, or ADMIN with management capability."""
    return pr.applicant_id == user.id or user.role_code == RoleCode.ADMIN.value


def _assert_self_or_admin(pr: PurchaseRequisition, user: CurrentUser) -> None:
    if not _can_manage(pr, user):
        raise PermissionDeniedException(
            "只能操作自己创建的采购申请",
            code=ErrorCode.PR_NOT_APPLICANT,
        )


def _assert_user_department_active(db: Session, user: CurrentUser) -> Department:
    """创建时：当前用户必须属于有效部门（Phase 6 §五.2）。"""
    dept = db.get(Department, user.department_id) if user.department_id else None
    if dept is None or dept.status != DeptStatus.ACTIVE:
        raise ValidationException("当前用户未归属有效部门，无法创建采购申请")
    return dept


def _recompute(pr: PurchaseRequisition) -> Decimal:
    """Recompute every line amount + header total (Phase 6 §八).

    Called by create / update / submit so amounts are always authoritative
    and client-provided amounts are never trusted.
    """
    total = Decimal("0")
    for item in pr.items:
        if item.requested_quantity <= 0:
            raise ValidationException(f"明细 {item.line_no} 申请数量必须大于 0")
        if item.estimated_unit_price < 0:
            raise ValidationException(f"明细 {item.line_no} 预估单价不能为负数")
        item.estimated_amount = money.line_amount(
            item.requested_quantity, item.estimated_unit_price
        )
        total += item.estimated_amount
    pr.total_estimated_amount = money.sum_amounts([total])
    return pr.total_estimated_amount


def _sync_items(pr: PurchaseRequisition, data: PurchaseRequisitionUpdate, db: Session) -> None:
    """Replace items per payload: stable-id updates, appends, deletions.

    ``line_no`` is re-assigned by payload order (display order only,
    Phase 6 §七). Line identity is the stable item ``id``.
    """
    existing = {it.id: it for it in pr.items}
    seen: set[int] = set()
    for line_no, req in enumerate(data.items, start=1):
        if req.id is not None:
            if req.id not in existing:
                raise ConflictException(
                    f"明细 {req.id} 不属于当前采购申请",
                    code=ErrorCode.PR_ITEM_NOT_FOUND,
                )
            item = existing[req.id]
            seen.add(req.id)
        else:
            # 必须 append 到 pr.items 集合：db.add() 只进 session，不会进已加载的
            # relationship 集合，_recompute 遍历 pr.items 时会漏掉新增行。
            item = PurchaseRequisitionItem(converted_quantity=Decimal("0"))
            pr.items.append(item)
            item.pr_id = pr.id
        _assert_material_active(db, req.material_id)
        item.line_no = line_no
        item.material_id = req.material_id
        item.requested_quantity = req.requested_quantity
        item.estimated_unit_price = req.estimated_unit_price
        item.required_date = req.required_date
        item.remark = req.remark
    for item_id, item in existing.items():
        if item_id not in seen:
            # remove 而非 db.delete：集合同步（响应遍历 pr.items 不再含被删行），
            # delete-orphan cascade 会在 flush 时发出 DELETE。
            pr.items.remove(item)


# ----------------------------------------------------------------------
# Create
# ----------------------------------------------------------------------
def create_pr(
    db: Session,
    data: PurchaseRequisitionCreate,
    *,
    user: CurrentUser,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> PurchaseRequisition:
    """创建 PR：Header + Items + 审计同一事务（Phase 6 §五.10）。

    全部服务端决定：pr_no / applicant_id / department_id / status /
    converted_quantity / estimated_amount / total_estimated_amount。
    """
    dept = _assert_user_department_active(db, user)
    apply_date = data.apply_date or date.today()
    pr_no = numbering_service.next_daily_code(
        db, SequenceKey.PURCHASE_REQUISITION, "PR", apply_date
    )
    pr = PurchaseRequisition(
        pr_no=pr_no,
        applicant_id=user.id,
        department_id=dept.id,  # 历史快照：不随调岗漂移
        apply_date=apply_date,
        reason=data.reason,
        status=PrStatus.DRAFT,
        total_estimated_amount=Decimal("0"),
        version=1,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(pr)
    db.flush()  # 需要 pr.id

    for line_no, req in enumerate(data.items, start=1):
        _assert_material_active(db, req.material_id)
        db.add(
            PurchaseRequisitionItem(
                pr_id=pr.id,
                line_no=line_no,
                material_id=req.material_id,
                requested_quantity=req.requested_quantity,
                converted_quantity=Decimal("0"),  # 创建时恒为 0（Phase 6 §五.7）
                estimated_unit_price=req.estimated_unit_price,
                estimated_amount=Decimal("0"),
                required_date=req.required_date,
                remark=req.remark,
            )
        )
    db.flush()
    _recompute(pr)
    db.flush()

    audit_service.write_audit(
        db,
        action=AuditAction.PR_CREATE,
        module=_MODULE,
        username_snapshot=user.username,
        document_type=_DOCUMENT_TYPE,
        document_id=pr.id,
        document_no=pr.pr_no,
        description=f"创建采购申请 {pr.pr_no}",
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    return pr


# ----------------------------------------------------------------------
# Read
# ----------------------------------------------------------------------
def get_pr(db: Session, pr_id: int, *, user: CurrentUser) -> PurchaseRequisition:
    pr = _load(db, pr_id)
    if user.role_code == RoleCode.APPLICANT.value and pr.applicant_id != user.id:
        raise PermissionDeniedException(
            "只能查看自己创建的采购申请",
            code=ErrorCode.PR_NOT_APPLICANT,
        )
    return pr


def list_prs(
    db: Session,
    *,
    user: CurrentUser,
    page: int,
    page_size: int,
    pr_no: str | None = None,
    applicant: str | None = None,
    department_id: int | None = None,
    status: PrStatus | None = None,
    apply_date_from: date | None = None,
    apply_date_to: date | None = None,
) -> tuple[list[PurchaseRequisition], int]:
    """分页列表：申请人默认只看自己的；有 pr:view 的其他角色看全部
    （部门主管的部门范围规则留给 Phase 7 审批阶段完善）。"""
    stmt = select(PurchaseRequisition)
    count_stmt = select(func.count()).select_from(PurchaseRequisition)

    if user.role_code == RoleCode.APPLICANT.value:
        cond = PurchaseRequisition.applicant_id == user.id
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    if pr_no:
        cond = PurchaseRequisition.pr_no.like(f"%{pr_no}%")
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    if applicant:
        join_cond = PurchaseRequisition.applicant_id == User.id
        stmt = stmt.join(User, join_cond)
        count_stmt = count_stmt.join(User, join_cond)
        like = f"%{applicant}%"
        cond = (User.username.like(like)) | (User.real_name.like(like))
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    if department_id is not None:
        cond = PurchaseRequisition.department_id == department_id
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    if status is not None:
        cond = PurchaseRequisition.status == status
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    if apply_date_from is not None:
        cond = PurchaseRequisition.apply_date >= apply_date_from
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    if apply_date_to is not None:
        cond = PurchaseRequisition.apply_date <= apply_date_to
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    total = db.execute(count_stmt).scalar_one()
    rows = db.execute(
        stmt.order_by(PurchaseRequisition.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).scalars().all()
    return list(rows), total


# ----------------------------------------------------------------------
# Update (optimistic lock, Phase 6 §六 / §十一)
# ----------------------------------------------------------------------
def update_pr(
    db: Session,
    pr_id: int,
    data: PurchaseRequisitionUpdate,
    *,
    user: CurrentUser,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> PurchaseRequisition:
    pr = _load(db, pr_id)
    _assert_self_or_admin(pr, user)
    if pr.status != PrStatus.DRAFT:
        raise ConflictException(
            "只有草稿状态的采购申请可以编辑",
            code=ErrorCode.PR_NOT_EDITABLE,
        )
    if pr.version != data.version:
        raise ConflictException(
            "单据已被其他操作修改，请刷新后重试",
            code=ErrorCode.CONFLICT,
        )

    _sync_items(pr, data, db)
    if data.apply_date is not None:
        pr.apply_date = data.apply_date
    if data.reason is not None:
        pr.reason = data.reason
    _recompute(pr)
    db.flush()

    # 原子乐观锁判定：version 不匹配或状态已被并发变更 → rowcount==0。
    # synchronize_session=False：ORM-enabled UPDATE 默认 'auto' 会用
    # RETURNING（MySQL 8.0.19+）把 DB 新值同步回 identity map，导致
    # 下方 pr.version 赋值基于已递增的值再 +1（version 双加）。这里关闭
    # 会话同步，手动按旧值赋值。
    result = db.execute(
        update(PurchaseRequisition)
        .where(
            PurchaseRequisition.id == pr_id,
            PurchaseRequisition.version == data.version,
            PurchaseRequisition.status == PrStatus.DRAFT,
        )
        .values(
            apply_date=pr.apply_date,
            reason=pr.reason,
            total_estimated_amount=pr.total_estimated_amount,
            updated_by=user.id,
            version=PurchaseRequisition.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        raise ConflictException(
            "单据已被其他操作修改，请刷新后重试",
            code=ErrorCode.CONFLICT,
        )
    pr.version = data.version + 1
    db.flush()

    audit_service.write_audit(
        db,
        action=AuditAction.PR_UPDATE,
        module=_MODULE,
        username_snapshot=user.username,
        document_type=_DOCUMENT_TYPE,
        document_id=pr.id,
        document_no=pr.pr_no,
        description=f"编辑采购申请 {pr.pr_no}（version {data.version} → {pr.version}）",
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    return pr


# ----------------------------------------------------------------------
# Submit (DRAFT -> PENDING, Phase 6 §九)
# ----------------------------------------------------------------------
def submit_pr(
    db: Session,
    pr_id: int,
    *,
    user: CurrentUser,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> PurchaseRequisition:
    pr = _load(db, pr_id)
    _assert_self_or_admin(pr, user)
    _assert_transition(pr, PrStatus.PENDING)

    if not pr.items:
        raise ConflictException(
            "采购申请至少需要一条明细才能提交",
            code=ErrorCode.PR_EMPTY_ITEMS,
        )
    for item in pr.items:
        _assert_material_active(db, item.material_id)
    _recompute(pr)  # 提交前重算所有金额（幂等，金额始终服务端权威）
    db.flush()

    now = datetime.now(timezone.utc)
    old_version = pr.version
    result = db.execute(
        update(PurchaseRequisition)
        .where(
            PurchaseRequisition.id == pr_id,
            PurchaseRequisition.status == PrStatus.DRAFT,
        )
        .values(
            status=PrStatus.PENDING,
            submitted_at=now,
            total_estimated_amount=pr.total_estimated_amount,
            updated_by=user.id,
            version=PurchaseRequisition.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        # 并发提交：另一个请求已把状态改走（或已被取消）
        raise ConflictException(
            "采购申请已被其他操作提交或修改，请刷新后重试",
            code=ErrorCode.PR_INVALID_STATUS_TRANSITION,
        )
    pr.status = PrStatus.PENDING
    pr.submitted_at = now
    pr.version = old_version + 1
    db.flush()

    audit_service.write_audit(
        db,
        action=AuditAction.PR_SUBMIT,
        module=_MODULE,
        username_snapshot=user.username,
        document_type=_DOCUMENT_TYPE,
        document_id=pr.id,
        document_no=pr.pr_no,
        description=f"提交采购申请 {pr.pr_no} 审批",
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    return pr


# ----------------------------------------------------------------------
# Cancel (DRAFT -> CANCELLED, Phase 6 §十)
# ----------------------------------------------------------------------
def cancel_pr(
    db: Session,
    pr_id: int,
    *,
    user: CurrentUser,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> PurchaseRequisition:
    pr = _load(db, pr_id)
    _assert_self_or_admin(pr, user)
    _assert_transition(pr, PrStatus.CANCELLED)

    old_version = pr.version
    result = db.execute(
        update(PurchaseRequisition)
        .where(
            PurchaseRequisition.id == pr_id,
            PurchaseRequisition.status == PrStatus.DRAFT,
        )
        .values(
            status=PrStatus.CANCELLED,
            updated_by=user.id,
            version=PurchaseRequisition.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        raise ConflictException(
            "采购申请已被其他操作修改，无法取消",
            code=ErrorCode.PR_INVALID_STATUS_TRANSITION,
        )
    old_status = pr.status
    pr.status = PrStatus.CANCELLED
    pr.version = old_version + 1
    db.flush()

    audit_service.write_audit(
        db,
        action=AuditAction.PR_CANCEL,
        module=_MODULE,
        username_snapshot=user.username,
        document_type=_DOCUMENT_TYPE,
        document_id=pr.id,
        document_no=pr.pr_no,
        description=f"取消采购申请 {pr.pr_no}",
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    return pr
