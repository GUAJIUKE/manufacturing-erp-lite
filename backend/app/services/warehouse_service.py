"""Warehouse master-data service (Phase 5 §三).

Disable rules:
- a warehouse with non-zero stock (inventory_balances.quantity != 0) can NOT
  be disabled (Phase 5 §三.5) — avoids "stock exists but warehouse unusable".
- history transactions / receipts stay queryable; no physical delete.
"""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictException, ErrorCode, NotFoundException
from app.models import InventoryBalance, Warehouse
from app.schemas.warehouse import WarehouseCreate, WarehouseUpdate
from app.services import audit_service, numbering_service
from app.utils.enums import ActiveStatus, AuditAction, SequenceKey

_MODULE = "warehouse"


def _load(db: Session, warehouse_id: int) -> Warehouse:
    warehouse = db.get(Warehouse, warehouse_id)
    if warehouse is None:
        raise NotFoundException("仓库不存在", code=ErrorCode.NOT_FOUND)
    return warehouse


def get_warehouse(db: Session, warehouse_id: int) -> Warehouse:
    return _load(db, warehouse_id)


def _assert_no_stock(db: Session, warehouse_id: int) -> None:
    nonzero = db.execute(
        select(func.count())
        .select_from(InventoryBalance)
        .where(InventoryBalance.warehouse_id == warehouse_id, InventoryBalance.quantity != 0)
    ).scalar_one()
    if nonzero > 0:
        raise ConflictException(
            "仓库仍存在非零库存，禁止停用（请先清空或转移库存）",
            code=ErrorCode.WAREHOUSE_HAS_STOCK,
        )


def create_warehouse(
    db: Session,
    data: WarehouseCreate,
    *,
    username: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> Warehouse:
    code = numbering_service.next_code(db, SequenceKey.WAREHOUSE, "WH")
    warehouse = Warehouse(
        warehouse_code=code,
        warehouse_name=data.warehouse_name,
        remark=data.remark,
        status=ActiveStatus.ACTIVE,
    )
    db.add(warehouse)
    db.flush()
    audit_service.write_audit(
        db,
        action=AuditAction.WAREHOUSE_CREATE,
        module=_MODULE,
        username_snapshot=username,
        document_type="warehouse",
        document_id=warehouse.id,
        description=f"创建仓库 {code} {data.warehouse_name}",
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    return warehouse


def update_warehouse(
    db: Session,
    warehouse_id: int,
    data: WarehouseUpdate,
    *,
    username: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> Warehouse:
    warehouse = _load(db, warehouse_id)
    if data.warehouse_name is not None:
        warehouse.warehouse_name = data.warehouse_name
    if data.remark is not None:
        warehouse.remark = data.remark
    db.flush()
    audit_service.write_audit(
        db,
        action=AuditAction.WAREHOUSE_UPDATE,
        module=_MODULE,
        username_snapshot=username,
        document_type="warehouse",
        document_id=warehouse.id,
        description=f"更新仓库 {warehouse.warehouse_code}",
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    return warehouse


def disable_warehouse(
    db: Session,
    warehouse_id: int,
    *,
    username: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> Warehouse:
    warehouse = _load(db, warehouse_id)
    _assert_no_stock(db, warehouse_id)
    warehouse.status = ActiveStatus.DISABLED
    db.flush()
    audit_service.write_audit(
        db,
        action=AuditAction.WAREHOUSE_DISABLE,
        module=_MODULE,
        username_snapshot=username,
        document_type="warehouse",
        document_id=warehouse.id,
        description=f"停用仓库 {warehouse.warehouse_code}",
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    return warehouse


def enable_warehouse(
    db: Session,
    warehouse_id: int,
    *,
    username: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> Warehouse:
    warehouse = _load(db, warehouse_id)
    warehouse.status = ActiveStatus.ACTIVE
    db.flush()
    audit_service.write_audit(
        db,
        action=AuditAction.WAREHOUSE_ENABLE,
        module=_MODULE,
        username_snapshot=username,
        document_type="warehouse",
        document_id=warehouse.id,
        description=f"启用仓库 {warehouse.warehouse_code}",
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    return warehouse


def list_warehouses(
    db: Session,
    *,
    page: int,
    page_size: int,
    code: str | None = None,
    name: str | None = None,
    status: ActiveStatus | None = None,
) -> tuple[list[Warehouse], int]:
    stmt = select(Warehouse)
    count_stmt = select(func.count()).select_from(Warehouse)

    if code:
        like = f"%{code}%"
        cond = Warehouse.warehouse_code.like(like)
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    if name:
        like = f"%{name}%"
        cond = Warehouse.warehouse_name.like(like)
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    if status is not None:
        cond = Warehouse.status == status
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    total = db.execute(count_stmt).scalar_one()
    rows = db.execute(
        stmt.order_by(Warehouse.id).offset((page - 1) * page_size).limit(page_size)
    ).scalars().all()
    return list(rows), total
