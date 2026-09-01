"""Inventory policy (safety stock) service — the core of Phase 5 §四.

Business rules:
- UNIQUE(warehouse_id, material_id): one policy per material per warehouse.
- safety_stock >= 0, reorder_point >= 0, max_stock > 0.
- When all three are configured: safety_stock <= reorder_point <= max_stock.
- A disabled material or disabled warehouse can neither create nor update a
  policy (Phase 5 §四.6).
- Dashboard's "materials below safety stock" will join
  inventory_policies × inventory_balances later; safety_stock is NOT copied
  into inventory_balances.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import (
    ConflictException,
    ErrorCode,
    NotFoundException,
    ValidationException,
)
from app.models import InventoryPolicy, Material, Warehouse
from app.schemas.inventory_policy import InventoryPolicyCreate, InventoryPolicyUpdate
from app.services import audit_service
from app.utils.enums import ActiveStatus, AuditAction

_MODULE = "inventory_policy"


def _load(db: Session, policy_id: int) -> InventoryPolicy:
    policy = db.get(InventoryPolicy, policy_id)
    if policy is None:
        raise NotFoundException("库存策略不存在", code=ErrorCode.NOT_FOUND)
    return policy


def _validate_ranges(
    safety_stock: Decimal | None,
    reorder_point: Decimal | None,
    max_stock: Decimal | None,
) -> None:
    """Phase 5 §四.5: when configured together, safety <= reorder <= max."""
    if (
        safety_stock is not None
        and reorder_point is not None
        and safety_stock > reorder_point
    ):
        raise ValidationException("safety_stock 必须小于等于 reorder_point")
    if (
        reorder_point is not None
        and max_stock is not None
        and reorder_point > max_stock
    ):
        raise ValidationException("reorder_point 必须小于等于 max_stock")
    if (
        safety_stock is not None
        and max_stock is not None
        and safety_stock > max_stock
    ):
        raise ValidationException("safety_stock 必须小于等于 max_stock")


def _validate_refs(db: Session, warehouse_id: int, material_id: int) -> None:
    """Material & warehouse must exist and be ACTIVE (§四.6)."""
    material = db.get(Material, material_id)
    if material is None:
        raise NotFoundException("物料不存在", code=ErrorCode.NOT_FOUND)
    if material.status != ActiveStatus.ACTIVE:
        raise ConflictException(
            "物料已停用，禁止创建/修改库存策略",
            code=ErrorCode.MASTER_DATA_DISABLED,
        )
    warehouse = db.get(Warehouse, warehouse_id)
    if warehouse is None:
        raise NotFoundException("仓库不存在", code=ErrorCode.NOT_FOUND)
    if warehouse.status != ActiveStatus.ACTIVE:
        raise ConflictException(
            "仓库已停用，禁止创建/修改库存策略",
            code=ErrorCode.MASTER_DATA_DISABLED,
        )


def _check_duplicate(db: Session, warehouse_id: int, material_id: int, exclude_id: int | None = None) -> None:
    stmt = select(InventoryPolicy.id).where(
        InventoryPolicy.warehouse_id == warehouse_id,
        InventoryPolicy.material_id == material_id,
    )
    if exclude_id is not None:
        stmt = stmt.where(InventoryPolicy.id != exclude_id)
    if db.execute(stmt).scalar_one_or_none() is not None:
        raise ConflictException(
            "该物料在该仓库已存在库存策略（一个物料一个仓库只能有一条策略）",
            code=ErrorCode.INVENTORY_POLICY_DUPLICATE,
        )


def get_policy(db: Session, policy_id: int) -> InventoryPolicy:
    return _load(db, policy_id)


def create_policy(
    db: Session,
    data: InventoryPolicyCreate,
    *,
    username: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> InventoryPolicy:
    # 校验顺序：引用（3009）-> 数值范围（422）-> 重复（3011）。
    # 参数错误应先于资源冲突返回，给前端更明确的修复指引。
    _validate_refs(db, data.warehouse_id, data.material_id)
    _validate_ranges(data.safety_stock, data.reorder_point, data.max_stock)
    _check_duplicate(db, data.warehouse_id, data.material_id)

    policy = InventoryPolicy(
        warehouse_id=data.warehouse_id,
        material_id=data.material_id,
        safety_stock=data.safety_stock,
        reorder_point=data.reorder_point,
        max_stock=data.max_stock,
        remark=data.remark,
    )
    db.add(policy)
    db.flush()
    audit_service.write_audit(
        db,
        action=AuditAction.INVENTORY_POLICY_CHANGE,
        module=_MODULE,
        username_snapshot=username,
        document_type="inventory_policy",
        document_id=policy.id,
        description=(
            f"创建库存策略 wh={policy.warehouse_id} mat={policy.material_id} "
            f"safety={policy.safety_stock}"
        ),
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    return policy


def update_policy(
    db: Session,
    policy_id: int,
    data: InventoryPolicyUpdate,
    *,
    username: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> InventoryPolicy:
    policy = _load(db, policy_id)
    # warehouse/material pair is immutable; refs must stay ACTIVE (§四.6).
    _validate_refs(db, policy.warehouse_id, policy.material_id)

    new_safety = data.safety_stock if data.safety_stock is not None else policy.safety_stock
    new_reorder = data.reorder_point if data.reorder_point is not None else policy.reorder_point
    new_max = data.max_stock if data.max_stock is not None else policy.max_stock
    _validate_ranges(new_safety, new_reorder, new_max)

    if data.safety_stock is not None:
        policy.safety_stock = data.safety_stock
    if data.reorder_point is not None:
        policy.reorder_point = data.reorder_point
    if data.max_stock is not None:
        policy.max_stock = data.max_stock
    if data.remark is not None:
        policy.remark = data.remark
    db.flush()
    audit_service.write_audit(
        db,
        action=AuditAction.INVENTORY_POLICY_CHANGE,
        module=_MODULE,
        username_snapshot=username,
        document_type="inventory_policy",
        document_id=policy.id,
        description=f"更新库存策略 wh={policy.warehouse_id} mat={policy.material_id}",
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    return policy


def list_policies(
    db: Session,
    *,
    page: int,
    page_size: int,
    warehouse_id: int | None = None,
    material_id: int | None = None,
) -> tuple[list[InventoryPolicy], int]:
    stmt = select(InventoryPolicy)
    count_stmt = select(func.count()).select_from(InventoryPolicy)
    if warehouse_id is not None:
        stmt = stmt.where(InventoryPolicy.warehouse_id == warehouse_id)
        count_stmt = count_stmt.where(InventoryPolicy.warehouse_id == warehouse_id)
    if material_id is not None:
        stmt = stmt.where(InventoryPolicy.material_id == material_id)
        count_stmt = count_stmt.where(InventoryPolicy.material_id == material_id)

    total = db.execute(count_stmt).scalar_one()
    rows = db.execute(
        stmt.order_by(InventoryPolicy.id).offset((page - 1) * page_size).limit(page_size)
    ).scalars().all()
    return list(rows), total
