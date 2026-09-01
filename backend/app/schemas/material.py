"""Material master-data schemas.

``material_code`` is system-generated (MAT-000001) and immutable: it never
appears in create/update payloads.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.utils.enums import ActiveStatus

UNIT_EXAMPLES = "pcs / set / kg / m / box（第一阶段字符串即可，不建 UOM 换算）"


class MaterialCreate(BaseModel):
    material_name: str = Field(min_length=1, max_length=128, description="物料名称（不要求全局唯一）")
    category: str | None = Field(default=None, max_length=64, description="分类（电子件/结构件/紧固件）")
    specification: str | None = Field(default=None, max_length=128, description="规格型号（可空）")
    unit: str = Field(min_length=1, max_length=16, description=f"计量单位，如 {UNIT_EXAMPLES}")
    remark: str | None = Field(default=None, max_length=255)


class MaterialUpdate(BaseModel):
    """All fields optional; ``material_code`` is never updatable."""

    material_name: str | None = Field(default=None, min_length=1, max_length=128)
    category: str | None = Field(default=None, max_length=64)
    specification: str | None = Field(default=None, max_length=128)
    unit: str | None = Field(default=None, min_length=1, max_length=16)
    remark: str | None = Field(default=None, max_length=255)


class MaterialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    material_code: str
    material_name: str
    category: str | None = None
    specification: str | None = None
    unit: str
    status: ActiveStatus
    remark: str | None = None
    created_at: datetime
    updated_at: datetime
