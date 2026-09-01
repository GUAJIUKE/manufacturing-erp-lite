"""Supplier master-data schemas.

``supplier_code`` is system-generated (SUP-000001) and immutable.
``supplier_name`` is NOT unique (historical renames / branch companies are
legal, Phase 5 §二.2).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.utils.enums import ActiveStatus


class SupplierCreate(BaseModel):
    supplier_name: str = Field(min_length=1, max_length=128)
    contact_person: str | None = Field(default=None, max_length=64)
    phone: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=128)
    address: str | None = Field(default=None, max_length=255)
    remark: str | None = Field(default=None, max_length=255)


class SupplierUpdate(BaseModel):
    """All fields optional; ``supplier_code`` is never updatable."""

    supplier_name: str | None = Field(default=None, min_length=1, max_length=128)
    contact_person: str | None = Field(default=None, max_length=64)
    phone: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=128)
    address: str | None = Field(default=None, max_length=255)
    remark: str | None = Field(default=None, max_length=255)


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    supplier_code: str
    supplier_name: str
    contact_person: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    status: ActiveStatus
    remark: str | None = None
    created_at: datetime
    updated_at: datetime
