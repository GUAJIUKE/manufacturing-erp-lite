"""Purchase order service (Phase 8: PR -> PO conversion + confirm/cancel).

Business-document rules, NOT plain CRUD:

* ``po_no`` is server-generated per day (PO-YYYYMMDD-0001, Phase 6 §三 policy).
* ``buyer_id`` is the creating buyer; ``status`` changes only via the central
  transition map below — the API layer never writes ``status`` directly
  (Phase 6 §十二 policy, inherited).
* Money is always recomputed server-side through ``app.utils.money``
  (ROUND_HALF_UP, 2 decimals); client-sent amounts are ignored (Phase 6 §八).
* PR -> PO conversion enforces quantity consistency (§9.2): every source row
  CAS-updates ``purchase_requisition_items.converted_quantity`` inside the
  PO transaction, so two concurrent POs can never over-convert one PR item
  (``PR_ITEM_CONVERT_EXCEEDED``, 4009). A PR header flips to CONVERTED only
  when ALL its items are fully converted — decided atomically inside the same
  transaction (NOT EXISTS sub-query), immune to REPEATABLE READ snapshots.
* PO cancel (R14 + §9.2 回退): only when no receiving happened; sources roll
  ``converted_quantity`` back and the PR header flips back to APPROVED when
  it is no longer fully converted.
* Confirm requires every line ``unit_price > 0`` (Q9 → ``PO_UNIT_PRICE_REQUIRED``).
* Object-level rules: BUYER/ADMIN/WAREHOUSE see all POs (receiving needs the
  full list); APPLICANT sees POs converted from their own PRs; DEPT_MANAGER
  sees POs converted from PRs of departments they manage. BUYER may only
  confirm/cancel POs they created (ADMIN overrides).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import exists, func, select, update
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
    DepartmentManager,
    Material,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderItemSource,
    PurchaseRequisition,
    PurchaseRequisitionItem,
    Supplier,
)
from app.schemas.auth import CurrentUser
from app.schemas.purchase_order import PurchaseOrderCreate
from app.services import audit_service, numbering_service
from app.utils import money
from app.utils.enums import (
    ActiveStatus,
    AuditAction,
    PoStatus,
    PrStatus,
    RoleCode,
    SequenceKey,
)

_MODULE = "po"
_DOCUMENT_TYPE = "PURCHASE_ORDER"

#: Roles that see the whole PO book (buying owns it, warehouse needs it for
#: receiving, admin manages everything).
_FULL_SCOPE_ROLES = frozenset({RoleCode.ADMIN.value, RoleCode.BUYER.value, RoleCode.WAREHOUSE.value})

# ----------------------------------------------------------------------
# Status machine (Phase 8 §二): the single source of truth.
# DRAFT -> CONFIRMED (confirm); DRAFT/CONFIRMED -> CANCELLED (cancel).
# PARTIALLY_RECEIVED / RECEIVED are driven by the receiving flow (Phase 9)
# and are deliberately NOT reachable from here; CANCELLED is terminal.
# Forbidden transitions stay out of the map: CONFIRMED -> DRAFT,
# CANCELLED -> anything, received states -> anything (R14).
# ----------------------------------------------------------------------
_TRANSITIONS: dict[PoStatus, frozenset[PoStatus]] = {
    PoStatus.DRAFT: frozenset({PoStatus.CONFIRMED, PoStatus.CANCELLED}),
    PoStatus.CONFIRMED: frozenset({PoStatus.CANCELLED}),
}


def _assert_transition(po: PurchaseOrder, target: PoStatus) -> None:
    allowed = _TRANSITIONS.get(po.status, frozenset())
    if target not in allowed:
        raise InvalidStatusTransitionException(
            f"采购订单状态不允许从 {po.status.value} 变更为 {target.value}",
            code=ErrorCode.PO_INVALID_STATUS_TRANSITION,
        )


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _load(db: Session, po_id: int) -> PurchaseOrder:
    po = db.get(PurchaseOrder, po_id)
    if po is None:
        raise NotFoundException("采购订单不存在", code=ErrorCode.PO_NOT_FOUND)
    return po


def _assert_version(po: PurchaseOrder, version: int) -> None:
    """乐观锁：客户端 version 必须等于当前 version（Phase 8 §六）。"""
    if po.version != version:
        raise ConflictException(
            "单据已被其他操作修改，请刷新后重试",
            code=ErrorCode.PO_VERSION_CONFLICT,
        )


def _raise_if_concurrent_change(db: Session, po: PurchaseOrder, expected: PoStatus) -> None:
    """条件 UPDATE rowcount==0 后：用锁定读穿透 REPEATABLE READ 快照，
    区分「状态已被并发动作改走」与「version 已过期」（Phase 7 同款技巧）。"""
    db.refresh(po, with_for_update=True)  # 当前读，看到最新已提交数据
    if po.status != expected:
        raise ConflictException(
            "单据已被其他操作处理，请刷新后重试",
            code=ErrorCode.PO_ALREADY_PROCESSED,
        )
    raise ConflictException(
        "单据已被其他操作修改，请刷新后重试",
        code=ErrorCode.PO_VERSION_CONFLICT,
    )


def _assert_buyer_or_admin(po: PurchaseOrder, user: CurrentUser) -> None:
    """对象级：BUYER 只能操作自己创建的 PO；ADMIN 全量（Phase 8 §四）。"""
    if user.role_code == RoleCode.ADMIN.value:
        return
    if po.buyer_id != user.id:
        raise PermissionDeniedException(
            "只能操作自己创建的采购订单",
            code=ErrorCode.PERMISSION_DENIED,
        )


def _assert_supplier_active(db: Session, supplier_id: int) -> Supplier:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise NotFoundException("供应商不存在", code=ErrorCode.NOT_FOUND)
    if supplier.status != ActiveStatus.ACTIVE:
        raise ConflictException(
            f"供应商 {supplier.supplier_name} 已停用，不能创建采购订单",
            code=ErrorCode.PO_SUPPLIER_DISABLED,
        )
    return supplier


def _assert_material_active(db: Session, material_id: int) -> Material:
    material = db.get(Material, material_id)
    if material is None:
        raise NotFoundException("物料不存在", code=ErrorCode.PO_ITEM_NOT_FOUND)
    if material.status != ActiveStatus.ACTIVE:
        raise ConflictException(
            f"物料 {material.material_code} 已停用，不能用于采购订单",
            code=ErrorCode.MASTER_DATA_DISABLED,
        )
    return material


def _source_visibility_cond(user: CurrentUser, managed_dept_ids: list[int]):
    """申请人看「自己 PR 转出的 PO」；主管看「本部门 PR 转出的 PO」。
    通过 sources → pr_item → PR 关联（§4.5 全链路可追溯，Q4/Q9 需求 9）。"""
    if user.role_code == RoleCode.APPLICANT.value:
        return PurchaseRequisition.applicant_id == user.id
    # DEPT_MANAGER（其余角色已由 _FULL_SCOPE_ROLES 放行）
    return PurchaseRequisition.department_id.in_(managed_dept_ids)


def _visible_source_stmt(cond) -> select:
    """EXISTS 风格子查询：PO 存在至少一条来源明细，其所属 PR 满足 cond。

    注意：不能带 LIMIT —— MySQL 不允许 ``IN (SELECT ... LIMIT 1)``；
    单个读取场景（get_po）由调用方自行追加 ``.limit(1)``。
    """
    return (
        select(PurchaseOrder.id)
        .join(PurchaseOrderItem, PurchaseOrderItem.po_id == PurchaseOrder.id)
        .join(PurchaseOrderItemSource, PurchaseOrderItemSource.po_item_id == PurchaseOrderItem.id)
        .join(PurchaseRequisitionItem, PurchaseRequisitionItem.id == PurchaseOrderItemSource.pr_item_id)
        .join(PurchaseRequisition, PurchaseRequisition.id == PurchaseRequisitionItem.pr_id)
        .where(cond)
    )


def _assert_visible(db: Session, po: PurchaseOrder, user: CurrentUser) -> None:
    """对象级读取门（Phase 8 §四）：APPLICANT/DEPT_MANAGER 仅可见自己链路
    的 PO；其余角色全量。不可见一律 403（不泄漏存在性）。"""
    if user.role_code in _FULL_SCOPE_ROLES:
        return
    if user.role_code == RoleCode.APPLICANT.value:
        cond = PurchaseRequisition.applicant_id == user.id
    elif user.role_code == RoleCode.DEPT_MANAGER.value:
        managed = db.execute(
            select(DepartmentManager.dept_id).where(DepartmentManager.user_id == user.id)
        ).scalars().all()
        cond = PurchaseRequisition.department_id.in_(managed)
    else:
        cond = None  # 未知角色：默认不可见
    if cond is None:
        raise PermissionDeniedException("无权查看该采购订单", code=ErrorCode.PERMISSION_DENIED)
    row = db.execute(
        _visible_source_stmt(cond).where(PurchaseOrder.id == po.id).limit(1)
    ).scalar_one_or_none()
    if row is None:
        raise PermissionDeniedException("无权查看该采购订单", code=ErrorCode.PERMISSION_DENIED)


def _flip_pr_to_converted(db: Session, pr_id: int) -> None:
    """PR 全部明细转完 → 头置 CONVERTED（§9.2 步骤 6）。

    用单条原子 UPDATE（NOT EXISTS 子查询）判定，避免 REPEATABLE READ 快照：
    并发转单时各事务读到的是自己的快照，逐行判断会漏置状态。
    rowcount 不强制——未全转完时条件不满足，UPDATE 自然 0 行。
    """
    db.execute(
        update(PurchaseRequisition)
        .where(
            PurchaseRequisition.id == pr_id,
            PurchaseRequisition.status == PrStatus.APPROVED,
        )
        .where(
            ~exists(
                select(PurchaseRequisitionItem.id).where(
                    PurchaseRequisitionItem.pr_id == pr_id,
                    PurchaseRequisitionItem.converted_quantity
                    < PurchaseRequisitionItem.requested_quantity,
                )
            )
        )
        .values(status=PrStatus.CONVERTED)
        .execution_options(synchronize_session=False)
    )


def _flip_pr_back_to_approved(db: Session, pr_id: int) -> None:
    """PO 取消后，PR 不再全部转完 → 回退 APPROVED（§9.2 回退）。

    同样原子判定：仅当存在未转完明细时才回退，已转完的不动。
    """
    db.execute(
        update(PurchaseRequisition)
        .where(
            PurchaseRequisition.id == pr_id,
            PurchaseRequisition.status == PrStatus.CONVERTED,
        )
        .where(
            exists(
                select(PurchaseRequisitionItem.id).where(
                    PurchaseRequisitionItem.pr_id == pr_id,
                    PurchaseRequisitionItem.converted_quantity
                    < PurchaseRequisitionItem.requested_quantity,
                )
            )
        )
        .values(status=PrStatus.APPROVED)
        .execution_options(synchronize_session=False)
    )


# ----------------------------------------------------------------------
# Create (PR -> PO conversion, §9.2; R4/R5/R12; Q3 拆单 / Q4 合单)
# ----------------------------------------------------------------------
def create_po(
    db: Session,
    data: PurchaseOrderCreate,
    *,
    user: CurrentUser,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> PurchaseOrder:
    """PR -> PO 转换：Header + Items + Sources + 审计同一事务（§9.2）。

    全部服务端决定：po_no / buyer_id / status / received_quantity / amount /
    total_amount / version / converted_quantity。
    """
    if not data.items:
        raise ConflictException("采购订单至少需要一条明细", code=ErrorCode.PO_EMPTY_ITEMS)
    supplier = _assert_supplier_active(db, data.supplier_id)  # R5

    # --- 预校验 1：所有来源明细存在，且所属 PR 均 APPROVED（R4 / §9.2 2.a） ---
    pr_items: dict[int, PurchaseRequisitionItem] = {}
    for item in data.items:
        for src in item.sources:
            pri = db.get(PurchaseRequisitionItem, src.pr_item_id)
            if pri is None:
                raise NotFoundException(
                    "采购申请明细不存在", code=ErrorCode.PR_ITEM_NOT_FOUND
                )
            pr_items[pri.id] = pri
    pr_ids = {pri.pr_id for pri in pr_items.values()}
    for pid in pr_ids:
        pr = db.get(PurchaseRequisition, pid)
        if pr is None:
            raise NotFoundException("采购申请不存在", code=ErrorCode.PR_NOT_FOUND)
        if pr.status != PrStatus.APPROVED:
            raise InvalidStatusTransitionException(
                f"采购申请 {pr.pr_no} 状态为 {pr.status.value}，只有 APPROVED 才能转采购订单",
                code=ErrorCode.PR_INVALID_STATUS_TRANSITION,
            )

    # --- 预校验 2：物料 ACTIVE；数量/单价合法；来源合计 ≤ 采购数量（§4.5 约束 2） ---
    for item in data.items:
        _assert_material_active(db, item.material_id)
        if item.ordered_quantity <= 0:
            raise ValidationException("明细采购数量必须大于 0")
        if item.unit_price < 0:
            raise ValidationException("明细采购单价不能为负数")
        total_src = sum((s.quantity for s in item.sources), Decimal("0"))
        if total_src > item.ordered_quantity:
            raise ConflictException(
                f"明细来源数量合计 {total_src} 超过采购数量 {item.ordered_quantity}",
                code=ErrorCode.PO_SOURCE_EXCEEDS_ORDERED,
            )

    order_date = data.order_date or date.today()
    po_no = numbering_service.next_daily_code(
        db, SequenceKey.PURCHASE_ORDER, "PO", order_date
    )
    po = PurchaseOrder(
        po_no=po_no,
        supplier_id=supplier.id,
        buyer_id=user.id,
        order_date=order_date,
        expected_date=data.expected_date,
        status=PoStatus.DRAFT,
        total_amount=Decimal("0"),
        version=1,
        remark=data.remark,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(po)
    db.flush()  # 需要 po.id

    total = Decimal("0")
    for line_no, item in enumerate(data.items, start=1):
        poi = PurchaseOrderItem(
            po_id=po.id,
            line_no=line_no,
            material_id=item.material_id,
            ordered_quantity=item.ordered_quantity,
            received_quantity=Decimal("0"),  # 创建时恒为 0（Q5）
            unit_price=item.unit_price,
            amount=money.line_amount(item.ordered_quantity, item.unit_price),
            remark=item.remark,
        )
        db.add(poi)
        db.flush()  # 需要 poi.id
        total += poi.amount
        for src in item.sources:
            # §9.2 2.b：CAS 更新已转数量，防并发超转（Q3 拆单核心）
            result = db.execute(
                update(PurchaseRequisitionItem)
                .where(
                    PurchaseRequisitionItem.id == src.pr_item_id,
                    PurchaseRequisitionItem.converted_quantity + src.quantity
                    <= PurchaseRequisitionItem.requested_quantity,
                )
                .values(
                    converted_quantity=PurchaseRequisitionItem.converted_quantity + src.quantity
                )
                .execution_options(synchronize_session=False)
            )
            if result.rowcount == 0:
                raise ConflictException(
                    "采购申请明细可转数量不足（可能已被其他采购订单占用）",
                    code=ErrorCode.PR_ITEM_CONVERT_EXCEEDED,
                )
            db.add(
                PurchaseOrderItemSource(
                    po_item_id=poi.id,
                    pr_item_id=src.pr_item_id,
                    quantity=src.quantity,
                )
            )
    po.total_amount = money.sum_amounts([total])
    db.flush()

    # §9.2 步骤 6：被引用 PR 全部明细转完 → CONVERTED（原子判定，见函数注释）
    for pid in pr_ids:
        _flip_pr_to_converted(db, pid)

    audit_service.write_audit(
        db,
        action=AuditAction.PO_CREATE,
        module=_MODULE,
        username_snapshot=user.username,
        document_type=_DOCUMENT_TYPE,
        document_id=po.id,
        document_no=po.po_no,
        description=f"创建采购订单 {po.po_no}（供应商 {supplier.supplier_name}）",
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    return po


# ----------------------------------------------------------------------
# Read
# ----------------------------------------------------------------------
def get_po(db: Session, po_id: int, *, user: CurrentUser) -> PurchaseOrder:
    po = _load(db, po_id)
    _assert_visible(db, po, user)
    return po


def list_pos(
    db: Session,
    *,
    user: CurrentUser,
    page: int,
    page_size: int,
    po_no: str | None = None,
    supplier_id: int | None = None,
    status: PoStatus | None = None,
    order_date_from: date | None = None,
    order_date_to: date | None = None,
) -> tuple[list[PurchaseOrder], int]:
    """分页列表（Phase 8 §四 查询范围）：
    BUYER/ADMIN/WAREHOUSE 全量；APPLICANT 仅自己 PR 转出的 PO；
    DEPT_MANAGER 仅本部门 PR 转出的 PO。
    """
    stmt = select(PurchaseOrder)
    count_stmt = select(func.count()).select_from(PurchaseOrder)

    if user.role_code not in _FULL_SCOPE_ROLES:
        if user.role_code == RoleCode.APPLICANT.value:
            cond = _source_visibility_cond(user, [])
            sub = _visible_source_stmt(cond)
            stmt = stmt.where(PurchaseOrder.id.in_(sub))
            count_stmt = count_stmt.where(PurchaseOrder.id.in_(sub))
        elif user.role_code == RoleCode.DEPT_MANAGER.value:
            managed = db.execute(
                select(DepartmentManager.dept_id).where(DepartmentManager.user_id == user.id)
            ).scalars().all()
            cond = _source_visibility_cond(user, list(managed))
            sub = _visible_source_stmt(cond)
            stmt = stmt.where(PurchaseOrder.id.in_(sub))
            count_stmt = count_stmt.where(PurchaseOrder.id.in_(sub))
        else:
            # 未知角色：只查无结果
            stmt = stmt.where(False)
            count_stmt = count_stmt.where(False)
    if po_no:
        cond = PurchaseOrder.po_no.like(f"%{po_no}%")
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    if supplier_id is not None:
        cond = PurchaseOrder.supplier_id == supplier_id
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    if status is not None:
        cond = PurchaseOrder.status == status
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    if order_date_from is not None:
        cond = PurchaseOrder.order_date >= order_date_from
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    if order_date_to is not None:
        cond = PurchaseOrder.order_date <= order_date_to
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    total = db.execute(count_stmt).scalar_one()
    rows = db.execute(
        stmt.order_by(PurchaseOrder.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).scalars().all()
    return list(rows), total


# ----------------------------------------------------------------------
# Confirm (DRAFT -> CONFIRMED, Q9)
# ----------------------------------------------------------------------
def confirm_po(
    db: Session,
    po_id: int,
    *,
    version: int,
    comment: str | None,
    user: CurrentUser,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> PurchaseOrder:
    """确认订单（Phase 8 §七）。

    DRAFT 阶段允许单价为 0 暂存（Q9）；确认（已向供应商下单）时逐行强制
    unit_price > 0。全部校验通过后：原子条件更新 + 审计，单事务。
    """
    po = _load(db, po_id)
    _assert_transition(po, PoStatus.CONFIRMED)  # 非 DRAFT -> 5002
    _assert_version(po, version)  # 乐观锁 -> 5012
    _assert_buyer_or_admin(po, user)  # 对象级 -> 403

    if not po.items:
        raise ConflictException("采购订单至少需要一条明细", code=ErrorCode.PO_EMPTY_ITEMS)
    for item in po.items:
        if item.unit_price <= 0:
            raise ConflictException(
                f"明细 {item.line_no} 采购单价必须大于 0 才能确认订单（价格未谈妥请先编辑）",
                code=ErrorCode.PO_UNIT_PRICE_REQUIRED,
            )

    old_version = po.version
    result = db.execute(
        update(PurchaseOrder)
        .where(
            PurchaseOrder.id == po_id,
            PurchaseOrder.version == version,
            PurchaseOrder.status == PoStatus.DRAFT,
        )
        .values(
            status=PoStatus.CONFIRMED,
            updated_by=user.id,
            version=PurchaseOrder.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        _raise_if_concurrent_change(db, po, PoStatus.DRAFT)
    po.status = PoStatus.CONFIRMED
    po.version = old_version + 1
    db.flush()

    audit_service.write_audit(
        db,
        action=AuditAction.PO_CONFIRM,
        module=_MODULE,
        username_snapshot=user.username,
        document_type=_DOCUMENT_TYPE,
        document_id=po.id,
        document_no=po.po_no,
        description=f"确认采购订单 {po.po_no}（version {old_version} → {po.version}）"
        + (f"，备注：{comment}" if comment else ""),
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    return po


# ----------------------------------------------------------------------
# Cancel (DRAFT/CONFIRMED -> CANCELLED; R14 + §9.2 回退)
# ----------------------------------------------------------------------
def cancel_po(
    db: Session,
    po_id: int,
    *,
    version: int,
    reason: str | None,
    user: CurrentUser,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> PurchaseOrder:
    """取消订单（Phase 8 §八）。

    仅当整单未发生收货（SUM(received_quantity) == 0，R14 → 5008）时允许。
    取消后逐条 source 回退 PR 明细 converted_quantity（CAS），并在 PR 不再
    全部转完时把 PR 头回退 APPROVED（§9.2 回退）。全部同一事务。
    """
    po = _load(db, po_id)
    _assert_transition(po, PoStatus.CANCELLED)  # DRAFT/CONFIRMED -> CANCELLED
    _assert_version(po, version)  # 乐观锁 -> 5012
    _assert_buyer_or_admin(po, user)  # 对象级 -> 403

    for item in po.items:
        if item.received_quantity > 0:
            raise ConflictException(
                "已产生收货的采购订单不能取消",
                code=ErrorCode.PO_CANCEL_HAS_RECEIPT,
            )

    old_version = po.version
    result = db.execute(
        update(PurchaseOrder)
        .where(
            PurchaseOrder.id == po_id,
            PurchaseOrder.version == version,
            PurchaseOrder.status.in_([PoStatus.DRAFT, PoStatus.CONFIRMED]),
        )
        .values(
            status=PoStatus.CANCELLED,
            updated_by=user.id,
            version=PurchaseOrder.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        _raise_if_concurrent_change(db, po, po.status)
    po.status = PoStatus.CANCELLED
    po.version = old_version + 1
    db.flush()

    # --- 回退 sources（§9.2 回退） ---
    po_item_ids = [it.id for it in po.items]
    pr_ids: set[int] = set()
    if po_item_ids:
        source_rows = db.execute(
            select(PurchaseOrderItemSource).where(
                PurchaseOrderItemSource.po_item_id.in_(po_item_ids)
            )
        ).scalars().all()
        for s in source_rows:
            result = db.execute(
                update(PurchaseRequisitionItem)
                .where(
                    PurchaseRequisitionItem.id == s.pr_item_id,
                    PurchaseRequisitionItem.converted_quantity >= s.quantity,
                )
                .values(
                    converted_quantity=PurchaseRequisitionItem.converted_quantity - s.quantity
                )
                .execution_options(synchronize_session=False)
            )
            if result.rowcount == 0:
                raise ConflictException(
                    "回退采购申请明细数量失败（数据异常，请人工核查）",
                    code=ErrorCode.CONFLICT,
                )
        if source_rows:
            pri_ids = [s.pr_item_id for s in source_rows]
            pr_ids = set(
                db.execute(
                    select(PurchaseRequisitionItem.pr_id).where(
                        PurchaseRequisitionItem.id.in_(pri_ids)
                    )
                ).scalars().all()
            )
    for pid in pr_ids:
        _flip_pr_back_to_approved(db, pid)

    audit_service.write_audit(
        db,
        action=AuditAction.PO_CANCEL,
        module=_MODULE,
        username_snapshot=user.username,
        document_type=_DOCUMENT_TYPE,
        document_id=po.id,
        document_no=po.po_no,
        description=f"取消采购订单 {po.po_no}（version {old_version} → {po.version}）"
        + (f"，原因：{reason}" if reason else ""),
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    return po
