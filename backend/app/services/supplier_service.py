"""Supplier master-data service (Phase 5 §二)."""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import ErrorCode, NotFoundException
from app.models import Supplier
from app.schemas.supplier import SupplierCreate, SupplierUpdate
from app.services import audit_service, numbering_service
from app.utils.enums import ActiveStatus, AuditAction, SequenceKey

_MODULE = "supplier"


def _load(db: Session, supplier_id: int) -> Supplier:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise NotFoundException("供应商不存在", code=ErrorCode.NOT_FOUND)
    return supplier


def get_supplier(db: Session, supplier_id: int) -> Supplier:
    return _load(db, supplier_id)


def create_supplier(
    db: Session,
    data: SupplierCreate,
    *,
    username: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> Supplier:
    code = numbering_service.next_code(db, SequenceKey.SUPPLIER, "SUP")
    supplier = Supplier(
        supplier_code=code,
        supplier_name=data.supplier_name,
        contact_person=data.contact_person,
        phone=data.phone,
        email=data.email,
        address=data.address,
        remark=data.remark,
        status=ActiveStatus.ACTIVE,
    )
    db.add(supplier)
    db.flush()
    audit_service.write_audit(
        db,
        action=AuditAction.SUPPLIER_CREATE,
        module=_MODULE,
        username_snapshot=username,
        document_type="supplier",
        document_id=supplier.id,
        description=f"创建供应商 {code} {data.supplier_name}",
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    return supplier


def update_supplier(
    db: Session,
    supplier_id: int,
    data: SupplierUpdate,
    *,
    username: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> Supplier:
    supplier = _load(db, supplier_id)
    if data.supplier_name is not None:
        supplier.supplier_name = data.supplier_name
    if data.contact_person is not None:
        supplier.contact_person = data.contact_person
    if data.phone is not None:
        supplier.phone = data.phone
    if data.email is not None:
        supplier.email = data.email
    if data.address is not None:
        supplier.address = data.address
    if data.remark is not None:
        supplier.remark = data.remark
    db.flush()
    audit_service.write_audit(
        db,
        action=AuditAction.SUPPLIER_UPDATE,
        module=_MODULE,
        username_snapshot=username,
        document_type="supplier",
        document_id=supplier.id,
        description=f"更新供应商 {supplier.supplier_code}",
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    return supplier


def disable_supplier(
    db: Session,
    supplier_id: int,
    *,
    username: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> Supplier:
    supplier = _load(db, supplier_id)
    supplier.status = ActiveStatus.DISABLED
    db.flush()
    audit_service.write_audit(
        db,
        action=AuditAction.SUPPLIER_DISABLE,
        module=_MODULE,
        username_snapshot=username,
        document_type="supplier",
        document_id=supplier.id,
        description=f"停用供应商 {supplier.supplier_code}",
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    return supplier


def enable_supplier(
    db: Session,
    supplier_id: int,
    *,
    username: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> Supplier:
    supplier = _load(db, supplier_id)
    supplier.status = ActiveStatus.ACTIVE
    db.flush()
    audit_service.write_audit(
        db,
        action=AuditAction.SUPPLIER_ENABLE,
        module=_MODULE,
        username_snapshot=username,
        document_type="supplier",
        document_id=supplier.id,
        description=f"启用供应商 {supplier.supplier_code}",
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    return supplier


def list_suppliers(
    db: Session,
    *,
    page: int,
    page_size: int,
    code: str | None = None,
    name: str | None = None,
    status: ActiveStatus | None = None,
) -> tuple[list[Supplier], int]:
    stmt = select(Supplier)
    count_stmt = select(func.count()).select_from(Supplier)

    if code:
        like = f"%{code}%"
        cond = Supplier.supplier_code.like(like)
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    if name:
        like = f"%{name}%"
        cond = Supplier.supplier_name.like(like)
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    if status is not None:
        cond = Supplier.status == status
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    total = db.execute(count_stmt).scalar_one()
    rows = db.execute(
        stmt.order_by(Supplier.id).offset((page - 1) * page_size).limit(page_size)
    ).scalars().all()
    return list(rows), total
