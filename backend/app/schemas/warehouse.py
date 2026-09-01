"""Warehouse master-data schemas.

``warehouse_code`` is system-generated (WH-000001) and immutable.
``warehouse_name``: not globally unique (Phase 5 §三.2 — a business may well
have two branches sharing a name; code is the real identity).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.utils.enums import ActiveStatus


class WarehouseCreate(BaseModel):
    warehouse_name: str = Field(min_length=1, max_length=64)
    remark: str | None = Field(default=None, max_length=255)


class WarehouseUpdate(BaseModel):
    """All fields optional; ``warehouse_code`` is never updatable."""

    warehouse_name: str | None = Field(default=None, min_length=1, max_length=64)
    remark: str | None = Field(default=None, max_length=255)


class WarehouseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    warehouse_code: str
    warehouse_name: str
    status: ActiveStatus
    remark: str | None = None
    created_at: datetime
    updated_at: datetime
