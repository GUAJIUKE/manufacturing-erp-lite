"""Authentication endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.v1.deps import CurrentUserDep, DbDep
from app.core.response import ApiResponse
from app.schemas.auth import CurrentUser, LoginRequest, TokenResponse
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", summary="登录获取 JWT")
def login(payload: LoginRequest, request: Request, db: DbDep) -> ApiResponse[TokenResponse]:
    token, expires_in = auth_service.login(
        db,
        username=payload.username,
        password=payload.password,
        request=request,
    )
    return ApiResponse.ok(
        TokenResponse(access_token=token, expires_in=expires_in),
        message="登录成功",
    )


@router.get("/me", summary="当前登录用户信息（含权限）")
def me(user: CurrentUserDep, db: DbDep) -> ApiResponse[CurrentUser]:
    from app.api.v1.deps import get_role_permissions

    perms = sorted(get_role_permissions(db, user.role_id))
    return ApiResponse.ok(user.model_copy(update={"permissions": perms}))
