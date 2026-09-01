"""User management schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.utils.enums import UserStatus


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$", description="登录账号")
    password: str = Field(min_length=6, max_length=128, description="初始密码，至少 6 位")
    real_name: str = Field(min_length=1, max_length=64)
    email: str | None = Field(default=None, max_length=128)
    phone: str | None = Field(default=None, max_length=32)
    department_id: int | None = None
    role_id: int = Field(gt=0)


class UserUpdate(BaseModel):
    """All fields optional; password=None keeps the current hash."""

    real_name: str | None = Field(default=None, min_length=1, max_length=64)
    email: str | None = Field(default=None, max_length=128)
    phone: str | None = Field(default=None, max_length=32)
    department_id: int | None = None
    role_id: int | None = Field(default=None, gt=0)
    status: UserStatus | None = None
    password: str | None = Field(default=None, min_length=6, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    real_name: str
    email: str | None = None
    phone: str | None = None
    department_id: int | None = None
    department_name: str | None = None
    role_id: int
    role_code: str | None = None
    role_name: str | None = None
    status: UserStatus
    last_login_at: datetime | None = None
    created_at: datetime
