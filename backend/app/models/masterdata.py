"""Master data models: materials, suppliers, warehouses, inventory policies.

Maps 1:1 to docs/database-design.md §3.7 - §3.10.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mysql import BIGINT as BigInteger

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import PKMixin, TimestampMixin
from app.utils.enums import ActiveStatus


class Material(PKMixin, TimestampMixin, Base):
    """物料主数据（§3.7）"""

    __tablename__ = "materials"
    __table_args__ = (
        UniqueConstraint("material_code", name="uk_mat_code"),
        Index("ix_mat_name", "material_name"),
        Index("ix_mat_status", "status"),
    )

    material_code: Mapped[str] = mapped_column(String(32), nullable=False, comment="MAT-000001")
    material_name: Mapped[str] = mapped_column(String(128), nullable=False, comment="物料名称")
    category: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="分类（电子件/结构件/紧固件）")
    specification: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="规格型号")
    unit: Mapped[str] = mapped_column(String(16), nullable=False, comment="计量单位（个/kg/m/套）")
    status: Mapped[ActiveStatus] = mapped_column(
        SAEnum(ActiveStatus, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        server_default=ActiveStatus.ACTIVE.value,
    )
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("users.id", name="fk_materials_created_by_users"),
        nullable=True,
    )
    updated_by: Mapped[int | None] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("users.id", name="fk_materials_updated_by_users"),
        nullable=True,
    )


class Supplier(PKMixin, TimestampMixin, Base):
    """供应商（§3.8）"""

    __tablename__ = "suppliers"
    __table_args__ = (
        UniqueConstraint("supplier_code", name="uk_sup_code"),
        Index("ix_sup_name", "supplier_name"),
        Index("ix_sup_status", "status"),
    )

    supplier_code: Mapped[str] = mapped_column(String(32), nullable=False, comment="SUP-000001")
    supplier_name: Mapped[str] = mapped_column(String(128), nullable=False)
    contact_person: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="联系人")
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(128), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[ActiveStatus] = mapped_column(
        SAEnum(ActiveStatus, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        server_default=ActiveStatus.ACTIVE.value,
    )
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("users.id", name="fk_suppliers_created_by_users"),
        nullable=True,
    )
    updated_by: Mapped[int | None] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("users.id", name="fk_suppliers_updated_by_users"),
        nullable=True,
    )


class Warehouse(PKMixin, TimestampMixin, Base):
    """仓库（§3.9）"""

    __tablename__ = "warehouses"
    __table_args__ = (
        UniqueConstraint("warehouse_code", name="uk_wh_code"),
        Index("ix_wh_status", "status"),
    )

    warehouse_code: Mapped[str] = mapped_column(String(32), nullable=False, comment="WH-000001")
    warehouse_name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[ActiveStatus] = mapped_column(
        SAEnum(ActiveStatus, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        server_default=ActiveStatus.ACTIVE.value,
    )
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("users.id", name="fk_warehouses_created_by_users"),
        nullable=True,
    )
    updated_by: Mapped[int | None] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("users.id", name="fk_warehouses_updated_by_users"),
        nullable=True,
    )


class InventoryPolicy(PKMixin, TimestampMixin, Base):
    """库存策略 / 安全库存（§3.10，Q10）

    安全库存是「仓库 + 物料」维度，故独立成表而非放在 materials。
    UNIQUE(warehouse_id, material_id) 保证一个仓库一个物料只有一条策略。
    """

    __tablename__ = "inventory_policies"
    __table_args__ = (
        UniqueConstraint("warehouse_id", "material_id", name="uk_invpol"),
        Index("ix_invpol_mat", "material_id"),
        CheckConstraint("safety_stock >= 0", name="safety_stock_nonneg"),
        CheckConstraint("min_stock IS NULL OR min_stock >= 0", name="min_stock_nonneg"),
        CheckConstraint("max_stock IS NULL OR max_stock > 0", name="max_stock_nonneg"),
        CheckConstraint("reorder_point IS NULL OR reorder_point >= 0", name="reorder_point_nonneg"),
    )

    warehouse_id: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("warehouses.id", name="fk_invpol_wh", ondelete="CASCADE"),
        nullable=False,
    )
    material_id: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("materials.id", name="fk_invpol_mat", ondelete="CASCADE"),
        nullable=False,
    )
    safety_stock: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default="0", comment="安全库存"
    )
    min_stock: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True, comment="最低库存")
    max_stock: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True, comment="最高库存")
    reorder_point: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True, comment="补货点")
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)

    warehouse: Mapped["Warehouse"] = relationship()
    material: Mapped["Material"] = relationship()
