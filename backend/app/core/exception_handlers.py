"""Global exception handlers.

Translates :class:`AppException` subclasses and framework-level errors
(validation, integrity, HTTP) into the unified :class:`ApiResponse` envelope.
Registered in ``app.main``.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import AppException, ErrorCode
from app.core.response import ApiResponse

logger = logging.getLogger(__name__)


def _request_id(request: Request) -> str | None:
    return request.headers.get("X-Request-ID")


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppException)
    async def _app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        body = ApiResponse.error(
            int(exc.code),
            exc.message,
            request_id=_request_id(request),
            detail=exc.detail,
        )
        return JSONResponse(status_code=exc.http_status, content=body.model_dump())

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        # 只保留最关键的校验错误信息，避免把整个 schema 泄漏给前端
        errors = []
        for err in exc.errors()[:5]:
            loc = ".".join(str(p) for p in err.get("loc", []) if p != "body")
            errors.append({"field": loc, "message": err.get("msg", "")})
        body = ApiResponse.error(
            ErrorCode.VALIDATION_ERROR,
            "参数校验失败",
            request_id=_request_id(request),
            detail=errors,
        )
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=body.model_dump())

    @app.exception_handler(StarletteHTTPException)
    async def _http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        body = ApiResponse.error(
            ErrorCode.NOT_FOUND if exc.status_code == 404 else ErrorCode.INTERNAL_ERROR,
            str(exc.detail),
            request_id=_request_id(request),
        )
        return JSONResponse(status_code=exc.status_code, content=body.model_dump())

    @app.exception_handler(IntegrityError)
    async def _integrity_handler(request: Request, exc: IntegrityError) -> JSONResponse:
        # 唯一约束冲突等数据库层错误 → 通用冲突码
        logger.warning("IntegrityError: %s", exc.orig)
        body = ApiResponse.error(
            ErrorCode.DUPLICATE_KEY,
            "数据冲突：记录已存在或违反唯一约束",
            request_id=_request_id(request),
        )
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=body.model_dump())

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        body = ApiResponse.error(
            ErrorCode.INTERNAL_ERROR,
            "服务器内部错误",
            request_id=_request_id(request),
        )
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=body.model_dump())
