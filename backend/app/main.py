"""FastAPI application entrypoint.

Layered architecture: ``api -> services -> repositories -> models``.
The API layer never mutates ``status`` fields directly; all business
operations go through the service layer (business rules §10).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exception_handlers import register_exception_handlers


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description=(
            "制造企业采购库存协同系统（Manufacturing ERP Lite）\n\n"
            "第一阶段：采购 + 仓储完整业务闭环。\n\n"
            "统一响应格式：`{code, message, data, request_id}`，业务错误通过 `code` 区分。"
        ),
        docs_url=settings.DOCS_URL,
        openapi_url=settings.OPENAPI_URL,
    )

    # CORS — 开发阶段放开，生产环境由部署层收紧
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    return app


app = create_app()
