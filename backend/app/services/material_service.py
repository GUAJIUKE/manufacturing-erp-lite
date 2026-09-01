"""Material master-data service.

Business rules (Phase 5 §一):
- code auto-generated (MAT-000001), unique, concurrency-safe, immutable
- name not unique (same name different spec is legal)
- no physical delete; only disable (materials referenced by PR/PO/inventory
  must stay queryable — we simply never expose a DELETE endpoint)
- a disabled material must not be referenced by NEW PR lines / PO lines /
  inventory policies (validated here for policies; PR/PO enforce in later
  phases on their own create paths)
"""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictException, ErrorCode, NotFoundException
from app.models import Material
from app.schemas.material import MaterialCreate, MaterialUpdate
from app.services import audit_service, numbering_service
from app.utils.enums import ActiveStatus, AuditAction, SequenceKey

_MODULE = "material"


def _load(db: Session, material_id: int) -> Material:
    material = db.get(Material, material_id)
    if material is None:
        raise NotFoundException("物料不存在", code=ErrorCode.NOT_FOUND)
    return material


def get_material(db: Session, material_id: int) -> Material:
    return _load(db, material_id)


def create_material(
    db: Session,
    data: MaterialCreate,
    *,
    username: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> Material:
    code = numbering_service.next_code(db, SequenceKey.MATERIAL, "MAT")
    material = Material(
        material_code=code,
        material_name=data.material_name,
        category=data.category,
        specification=data.specification,
        unit=data.unit,
        remark=data.remark,
        status=ActiveStatus.ACTIVE,
    )
    db.add(material)
    db.flush()
    audit_service.write_audit(
        db,
        action=AuditAction.MATERIAL_CREATE,
        module=_MODULE,
        username_snapshot=username,
        document_type="material",
        document_id=material.id,
        description=f"创建物料 {code} {data.material_name}",
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    return material


def update_material(
    db: Session,
    material_id: int,
    data: MaterialUpdate,
    *,
    username: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> Material:
    material = _load(db, material_id)
    # material_code intentionally never updated.
    if data.material_name is not None:
        material.material_name = data.material_name
    if data.category is not None:
        material.category = data.category
    if data.specification is not None:
        material.specification = data.specification
    if data.unit is not None:
        material.unit = data.unit
    if data.remark is not None:
        material.remark = data.remark
    db.flush()
    audit_service.write_audit(
        db,
        action=AuditAction.MATERIAL_UPDATE,
        module=_MODULE,
        username_snapshot=username,
        document_type="material",
        document_id=material.id,
        description=f"更新物料 {material.material_code}",
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    return material


def disable_material(
    db: Session,
    material_id: int,
    *,
    username: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> Material:
    """Stop a material. History documents stay queryable (no physical delete)."""
    material = _load(db, material_id)
    material.status = ActiveStatus.DISABLED
    db.flush()
    audit_service.write_audit(
        db,
        action=AuditAction.MATERIAL_DISABLE,
        module=_MODULE,
        username_snapshot=username,
        document_type="material",
        document_id=material.id,
        description=f"停用物料 {material.material_code}",
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    return material


def enable_material(
    db: Session,
    material_id: int,
    *,
    username: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> Material:
    material = _load(db, material_id)
    material.status = ActiveStatus.ACTIVE
    db.flush()
    audit_service.write_audit(
        db,
        action=AuditAction.MATERIAL_ENABLE,
        module=_MODULE,
        username_snapshot=username,
        document_type="material",
        document_id=material.id,
        description=f"启用物料 {material.material_code}",
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    return material


def list_materials(
    db: Session,
    *,
    page: int,
    page_size: int,
    code: str | None = None,
    name: str | None = None,
    category: str | None = None,
    status: ActiveStatus | None = None,
) -> tuple[list[Material], int]:
    stmt = select(Material)
    count_stmt = select(func.count()).select_from(Material)

    if code:
        like = f"%{code}%"
        cond = Material.material_code.like(like)
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    if name:
        like = f"%{name}%"
        cond = Material.material_name.like(like)
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    if category:
        cond = Material.category == category
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    if status is not None:
        cond = Material.status == status
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    total = db.execute(count_stmt).scalar_one()
    rows = db.execute(
        stmt.order_by(Material.id).offset((page - 1) * page_size).limit(page_size)
    ).scalars().all()
    return list(rows), total
