"""Inventory policy (safety stock) schemas.

Dimension: warehouse + material (Q10). UNIQUE(warehouse_id, material_id)
is enforced at the DB level; the service also pre-checks and returns a
friendly error. Phase 5 §四: safety >= 0, reorder >= 0, max > 0, and when
all three are set: safety <= reorder <= max.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class InventoryPolicyCreate(BaseModel):
    warehouse_id: int = Field(gt=0)
    material_id: int = Field(gt=0)
    safety_stock: Decimal = Field(default=Decimal("0"), ge=0, description="安全库存，>= 0")
    reorder_point: Decimal | None = Field(default=None, ge=0, description="补货点，>= 0")
    max_stock: Decimal | None = Field(default=None, gt=0, description="最高库存，> 0")
    remark: str | None = Field(default=None, max_length=255)


class InventoryPolicyUpdate(BaseModel):
    """All fields optional; warehouse/material pair is immutable once created."""

    safety_stock: Decimal | None = Field(default=None, ge=0)
    reorder_point: Decimal | None = Field(default=None, ge=0)
    max_stock: Decimal | None = Field(default=None, gt=0)
    remark: str | None = Field(default=None, max_length=255)


class InventoryPolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    warehouse_id: int
    material_id: int
    safety_stock: Decimal
    min_stock: Decimal | None = None
    reorder_point: Decimal | None = None
    max_stock: Decimal | None = None
    remark: str | None = None
    created_at: datetime
    updated_at: datetime
