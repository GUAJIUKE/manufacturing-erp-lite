"""Purchase requisition service (Phase 6 + Phase 7 approval workflow).

Business-document rules, NOT plain CRUD:

* ``pr_no`` is server-generated per day (PR-YYYYMMDD-0001, Phase 6 §三).
* ``applicant_id`` / ``department_id`` are snapshots from the creating user's
  current department — never derived from the user's current department
  afterwards (Phase 6 §二).
* Status changes only via the central transition map below; the API layer
  never writes ``status`` directly (Phase 6 §十二 / Phase 7 §一).
* Money is always recomputed server-side through ``app.utils.money``
  (ROUND_HALF_UP, 2 decimals); client-sent amounts are ignored (Phase 6 §八).
* Updates / submit / cancel / approve / reject / revise use atomic
  conditional UPDATEs so concurrent editors cannot overwrite each other
  (optimistic lock, Phase 6 §十一 / Phase 7 §十四).
* Object-level rules (Phase 6 §六 / §十四, Phase 7 §四):
  - a plain applicant only touches their own PRs;
  - a department manager may approve/reject PRs of departments they manage
    (current ``department_managers`` relation, never hard-coded);
  - ADMIN keeps management capability and may override as approver
    (``is_admin_override`` — recorded in step_name + audit description).
* Approval actions write an append-only ``approval_records`` row PLUS a
  system ``operation_logs`` row in the SAME transaction (Phase 7 §三 / §十五).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.core.exceptions import (
    ConflictException,
    ErrorCode,
    InvalidStatusTransitionException,
    NotFoundException,
    PermissionDeniedException,
    ValidationException,
)
from app.models import (
    ApprovalRecord,
    Department,
    DepartmentManager,
    Material,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderItemSource,
    PurchaseRequisition,
    PurchaseRequisitionItem,
    User,
)
from app.schemas.auth import CurrentUser
from app.schemas.purchase_requisition import (
    PurchaseRequisitionCreate,
    PurchaseRequisitionUpdate,
)
from app.services import audit_service, numbering_service
from app.utils import money
from app.utils.enums import (
    ActiveStatus,
    ApprovalAction,
    AuditAction,
    DeptStatus,
    DocumentType,
    PoStatus,
    PrStatus,
    RoleCode,
    SequenceKey,
    UserStatus,
)

_MODULE = "pr"
_DOCUMENT_TYPE = "PURCHASE_REQUISITION"

# ----------------------------------------------------------------------
# Status machine (Phase 6 §十二 / Phase 7 §二): the single source of truth.
# Phase 7 adds: PENDING -> APPROVED / REJECTED (approve/reject),
# REJECTED -> DRAFT (revise, then edit + resubmit DRAFT -> PENDING).
# Phase 8 adds (Q2): APPROVED -> CANCELLED — allowed only when the PR has no
# active (non-cancelled) PO, checked in cancel_pr (4008).
# Forbidden transitions stay out of the map: DRAFT -> APPROVED/REJECTED,
# PENDING -> DRAFT, APPROVED -> PENDING/CONVERTED (handled by PO service),
# CANCELLED -> anything, REJECTED -> PENDING (must go through DRAFT first).
# ----------------------------------------------------------------------
_TRANSITIONS: dict[PrStatus, frozenset[PrStatus]] = {
    PrStatus.DRAFT: frozenset({PrStatus.PENDING, PrStatus.CANCELLED}),
    PrStatus.PENDING: frozenset({PrStatus.APPROVED, PrStatus.REJECTED}),
    PrStatus.REJECTED: frozenset({PrStatus.DRAFT}),
    PrStatus.APPROVED: frozenset({PrStatus.CANCELLED}),  # Phase 8 Q2
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


def _assert_approver(db: Session, pr: PurchaseRequisition, user: CurrentUser) -> bool:
    """Phase 7 §四 / §五: 审批人对象级校验。

    通过返回 ``is_admin_override``（True 表示 ADMIN 越权兜底，须在
    approval_record.step_name 与 operation_logs.description 中体现）。

    校验顺序：用户 ACTIVE → 申请部门 ACTIVE → ADMIN override →
    当前部门主管关系（department_managers，可查询、不写死 user_id）。
    """
    db_user = db.get(User, user.id)
    if db_user is None or db_user.status != UserStatus.ACTIVE:
        raise PermissionDeniedException("账号已被禁用，无法审批", code=ErrorCode.USER_DISABLED)
    dept = db.get(Department, pr.department_id)
    if dept is None or dept.status != DeptStatus.ACTIVE:
        raise ConflictException(
            f"申请部门 {dept.dept_name if dept else ''} 已停用，无法审批",
            code=ErrorCode.MASTER_DATA_DISABLED,
        )
    if user.role_code == RoleCode.ADMIN.value:
        return True  # ADMIN override（审计中显式记录）
    is_manager = db.execute(
        select(DepartmentManager.id).where(
            DepartmentManager.dept_id == pr.department_id,
            DepartmentManager.user_id == user.id,
        )
    ).scalar_one_or_none()
    if is_manager is None:
        raise PermissionDeniedException(
            "只有申请部门的主管才能审批该采购申请",
            code=ErrorCode.PR_NOT_APPROVER,
        )
    return False


def _assert_version(pr: PurchaseRequisition, version: int) -> None:
    """乐观锁：客户端 version 必须等于当前 version（Phase 7 §十四）。"""
    if pr.version != version:
        raise ConflictException(
            "单据已被其他操作修改，请刷新后重试",
            code=ErrorCode.PR_VERSION_CONFLICT,
        )


def _raise_if_concurrent_change(db: Session, pr: PurchaseRequisition, expected: PrStatus) -> None:
    """条件 UPDATE rowcount==0 后：用锁定读穿透 REPEATABLE READ 快照，
    区分「状态已被并发动作改走」与「version 已过期」。"""
    db.refresh(pr, with_for_update=True)  # 当前读，看到最新已提交数据
    if pr.status != expected:
        raise ConflictException(
            "单据已被其他操作处理，请刷新后重试",
            code=ErrorCode.PR_ALREADY_PROCESSED,
        )
    raise ConflictException(
        "单据已被其他操作修改，请刷新后重试",
        code=ErrorCode.PR_VERSION_CONFLICT,
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


def visible_pr_condition(db: Session, user: CurrentUser):
    """当前用户可见 PR 的 WHERE 条件；``None`` 表示全量可见。

    口径与 :func:`list_prs` 完全一致（Phase 7 §六 查询范围）——Phase 11
    Dashboard 直接复用本函数做 SQL 聚合，避免另起一套范围规则造成漂移：

    - APPLICANT：只看自己创建的 PR
    - DEPT_MANAGER：自己创建的 + 自己负责部门（当前有效主管关系）的 PR
    - ADMIN / BUYER / WAREHOUSE：全量（采购执行 / 仓储角色跨部门）
    """
    if user.role_code == RoleCode.APPLICANT.value:
        return PurchaseRequisition.applicant_id == user.id
    if user.role_code == RoleCode.DEPT_MANAGER.value:
        managed_dept_ids = db.execute(
            select(DepartmentManager.dept_id).where(DepartmentManager.user_id == user.id)
        ).scalars().all()
        return or_(
            PurchaseRequisition.applicant_id == user.id,
            PurchaseRequisition.department_id.in_(managed_dept_ids),
        )
    return None


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
    """分页列表（Phase 7 §六 查询范围，不因拥有 pr:view 就全量放行）：

    - APPLICANT：只看自己的 PR
    - DEPT_MANAGER：自己创建的 PR + 自己负责部门（当前有效主管关系）的 PR
    - ADMIN / BUYER：全部（采购执行角色跨部门，Phase 8 转 PO 需要）
    """
    stmt = select(PurchaseRequisition)
    count_stmt = select(func.count()).select_from(PurchaseRequisition)

    scope_cond = visible_pr_condition(db, user)
    if scope_cond is not None:
        stmt = stmt.where(scope_cond)
        count_stmt = count_stmt.where(scope_cond)
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
    _assert_transition(pr, PrStatus.CANCELLED)  # DRAFT / APPROVED -> CANCELLED（Phase 8 Q2）

    if pr.status == PrStatus.APPROVED:
        # Q2 限制：已转 PO（存在非 CANCELLED 的关联订单）的 PR 禁止取消，
        # 避免 PR 已取消但 PO 仍活跃的数据不一致（4008）。
        has_active_po = db.execute(
            select(PurchaseOrder.id)
            .join(PurchaseOrderItem, PurchaseOrderItem.po_id == PurchaseOrder.id)
            .join(
                PurchaseOrderItemSource,
                PurchaseOrderItemSource.po_item_id == PurchaseOrderItem.id,
            )
            .join(
                PurchaseRequisitionItem,
                PurchaseRequisitionItem.id == PurchaseOrderItemSource.pr_item_id,
            )
            .where(
                PurchaseRequisitionItem.pr_id == pr.id,
                PurchaseOrder.status != PoStatus.CANCELLED,
            )
            .limit(1)
        ).scalar_one_or_none()
        if has_active_po is not None:
            raise ConflictException(
                "该采购申请已转采购订单，不能取消",
                code=ErrorCode.PR_CANCEL_HAS_ACTIVE_PO,
            )

    old_version = pr.version
    result = db.execute(
        update(PurchaseRequisition)
        .where(
            PurchaseRequisition.id == pr_id,
            PurchaseRequisition.status.in_([PrStatus.DRAFT, PrStatus.APPROVED]),
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


# ----------------------------------------------------------------------
# Approval workflow (Phase 7)
# ----------------------------------------------------------------------
def _approval_record(
    db: Session,
    *,
    pr: PurchaseRequisition,
    action: ApprovalAction,
    from_status: PrStatus,
    to_status: PrStatus,
    approver_id: int,
    is_admin_override: bool,
    comment: str | None,
) -> ApprovalRecord:
    """写一条 append-only 审批记录（Phase 7 §三）。

    ``step_name`` 区分「部门主管审批 / 管理员越权审批」，让 ADMIN_OVERRIDE
    在审批历史中可追溯；``result_status`` 与 ``to_status`` 同步保持向后兼容。
    """
    record = ApprovalRecord(
        document_type=DocumentType.PURCHASE_REQUISITION,
        document_id=pr.id,
        document_no=pr.pr_no,
        step_no=1,
        step_name="管理员越权审批" if is_admin_override else "部门主管审批",
        approver_id=approver_id,
        action=action,
        from_status=from_status.value,
        to_status=to_status.value,
        result_status=to_status.value,
        comment=comment,
    )
    db.add(record)
    return record


def approve_pr(
    db: Session,
    pr_id: int,
    *,
    version: int,
    comment: str | None,
    user: CurrentUser,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> PurchaseRequisition:
    """审批通过 PENDING -> APPROVED（Phase 7 §七 / §八）。

    Approve 必须重新校验业务数据：提交与审批之间物料可能已被停用，此时
    不应批准一张后续无法转 PO 的 PR。全部校验通过后：原子条件更新 status/
    version + 写 approval_record + 写 operation_log，单事务（Phase 7 §十五）。
    """
    pr = _load(db, pr_id)
    _assert_transition(pr, PrStatus.APPROVED)  # 非 PENDING -> 4002
    _assert_version(pr, version)  # 乐观锁 -> 4011
    is_admin_override = _assert_approver(db, pr, user)  # 对象级 -> 403/4007

    # 重新校验业务数据（不依赖 submit 时的历史校验，Phase 7 §八）
    if not pr.items:
        raise ConflictException(
            "采购申请至少需要一条明细才能审批",
            code=ErrorCode.PR_EMPTY_ITEMS,
        )
    for item in pr.items:
        _assert_material_active(db, item.material_id)  # 物料存在且 ACTIVE -> 3009
        if item.requested_quantity <= 0:
            raise ValidationException(f"明细 {item.line_no} 申请数量必须大于 0")
        if item.estimated_unit_price < 0:
            raise ValidationException(f"明细 {item.line_no} 预估单价不能为负数")
    _recompute(pr)  # 服务端重算金额（幂等，审批时再次确认一致）
    db.flush()

    old_version = pr.version
    result = db.execute(
        update(PurchaseRequisition)
        .where(
            PurchaseRequisition.id == pr_id,
            PurchaseRequisition.version == version,
            PurchaseRequisition.status == PrStatus.PENDING,
        )
        .values(
            status=PrStatus.APPROVED,
            total_estimated_amount=pr.total_estimated_amount,
            updated_by=user.id,
            version=PurchaseRequisition.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        _raise_if_concurrent_change(db, pr, PrStatus.PENDING)
    pr.status = PrStatus.APPROVED
    pr.version = old_version + 1
    db.flush()

    _approval_record(
        db,
        pr=pr,
        action=ApprovalAction.APPROVE,
        from_status=PrStatus.PENDING,
        to_status=PrStatus.APPROVED,
        approver_id=user.id,
        is_admin_override=is_admin_override,
        comment=comment,
    )
    override_note = "（ADMIN 越权审批）" if is_admin_override else ""
    audit_service.write_audit(
        db,
        action=AuditAction.PR_APPROVE,
        module=_MODULE,
        username_snapshot=user.username,
        document_type=_DOCUMENT_TYPE,
        document_id=pr.id,
        document_no=pr.pr_no,
        description=f"审批通过采购申请 {pr.pr_no}{override_note}（version {old_version} → {pr.version}）",
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    return pr


def reject_pr(
    db: Session,
    pr_id: int,
    *,
    version: int,
    comment: str,
    user: CurrentUser,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> PurchaseRequisition:
    """驳回 PENDING -> REJECTED（Phase 7 §九）。

    与 approve 不同：不强制校验 material ACTIVE / 金额有效性 —— 即使业务
    数据有问题也应允许主管驳回。comment 必填（schema 层 trim 校验兜底）。
    """
    pr = _load(db, pr_id)
    _assert_transition(pr, PrStatus.REJECTED)  # 非 PENDING -> 4002
    _assert_version(pr, version)  # 乐观锁 -> 4011
    is_admin_override = _assert_approver(db, pr, user)  # 对象级 -> 403/4007

    old_version = pr.version
    result = db.execute(
        update(PurchaseRequisition)
        .where(
            PurchaseRequisition.id == pr_id,
            PurchaseRequisition.version == version,
            PurchaseRequisition.status == PrStatus.PENDING,
        )
        .values(
            status=PrStatus.REJECTED,
            updated_by=user.id,
            version=PurchaseRequisition.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        _raise_if_concurrent_change(db, pr, PrStatus.PENDING)
    pr.status = PrStatus.REJECTED
    pr.version = old_version + 1
    db.flush()

    _approval_record(
        db,
        pr=pr,
        action=ApprovalAction.REJECT,
        from_status=PrStatus.PENDING,
        to_status=PrStatus.REJECTED,
        approver_id=user.id,
        is_admin_override=is_admin_override,
        comment=comment,
    )
    override_note = "（ADMIN 越权审批）" if is_admin_override else ""
    audit_service.write_audit(
        db,
        action=AuditAction.PR_REJECT,
        module=_MODULE,
        username_snapshot=user.username,
        document_type=_DOCUMENT_TYPE,
        document_id=pr.id,
        document_no=pr.pr_no,
        description=f"驳回采购申请 {pr.pr_no}{override_note}（version {old_version} → {pr.version}）",
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    return pr


def revise_pr(
    db: Session,
    pr_id: int,
    *,
    version: int,
    user: CurrentUser,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> PurchaseRequisition:
    """重新编辑 REJECTED -> DRAFT（Phase 7 §十）。

    仅原申请人（或 ADMIN，沿用现有对象权限策略）。不修改业务内容，
    清空 submitted_at（旧提交时间可从审计/审批历史追溯）。不写
    approval_record —— revise 不是审批动作，只写 PR_REVISE 审计。
    """
    pr = _load(db, pr_id)
    _assert_transition(pr, PrStatus.DRAFT)  # 非 REJECTED -> 4002
    _assert_self_or_admin(pr, user)  # 仅 applicant（或 ADMIN）-> 403/4005
    _assert_version(pr, version)  # 乐观锁 -> 4011

    old_version = pr.version
    result = db.execute(
        update(PurchaseRequisition)
        .where(
            PurchaseRequisition.id == pr_id,
            PurchaseRequisition.version == version,
            PurchaseRequisition.status == PrStatus.REJECTED,
        )
        .values(
            status=PrStatus.DRAFT,
            submitted_at=None,  # 新编辑轮次，旧提交时间不再代表当前（Phase 7 §十.5）
            updated_by=user.id,
            version=PurchaseRequisition.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        _raise_if_concurrent_change(db, pr, PrStatus.REJECTED)
    pr.status = PrStatus.DRAFT
    pr.submitted_at = None
    pr.version = old_version + 1
    db.flush()

    audit_service.write_audit(
        db,
        action=AuditAction.PR_REVISE,
        module=_MODULE,
        username_snapshot=user.username,
        document_type=_DOCUMENT_TYPE,
        document_id=pr.id,
        document_no=pr.pr_no,
        description=f"重新编辑被驳回的采购申请 {pr.pr_no}（version {old_version} → {pr.version}）",
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    return pr


def list_approvals(db: Session, pr_id: int, *, user: CurrentUser) -> list[ApprovalRecord]:
    """审批历史（Phase 7 §十二）：仅「能查看该 PR 的用户」可看，
    复用 get_pr 的对象级规则，防止审批历史侧漏业务数据。"""
    get_pr(db, pr_id, user=user)  # 权限门：无权查看 PR 则 403/404
    stmt = (
        select(ApprovalRecord)
        .where(
            ApprovalRecord.document_type == DocumentType.PURCHASE_REQUISITION,
            ApprovalRecord.document_id == pr_id,
        )
        .order_by(ApprovalRecord.created_at.asc(), ApprovalRecord.id.asc())
    )
    return list(db.execute(stmt).scalars().all())
