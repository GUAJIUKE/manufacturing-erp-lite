"""Auth schemas: login request/response and the authenticated principal."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64, description="登录账号")
    password: str = Field(min_length=1, max_length=128, description="密码")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class CurrentUser(BaseModel):
    """Authenticated principal exposed via the get_current_user dependency."""

    id: int
    username: str
    real_name: str
    role_id: int
    role_code: str
    role_name: str
    department_id: int | None = None
    department_name: str | None = None
    permissions: list[str] = []


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=6, max_length=128, description="新密码，至少 6 位")
