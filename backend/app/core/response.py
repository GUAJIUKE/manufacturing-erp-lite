"""Unified API response envelope.

Every endpoint returns::

    {"code": 0, "message": "success", "data": ..., "request_id": "..."}

``code != 0`` marks a business error; HTTP status still carries the
semantic category. Paginated results use :class:`PageResult`.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, model_validator

from app.core.exceptions import ErrorCode

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int = ErrorCode.OK
    message: str = "success"
    data: T | None = None
    request_id: str | None = None

    @classmethod
    def ok(cls, data: T | None = None, *, message: str = "success") -> "ApiResponse[T]":
        return cls(code=ErrorCode.OK, message=message, data=data)

    @classmethod
    def error(
        cls,
        code: int,
        message: str,
        *,
        request_id: str | None = None,
        detail: Any = None,
    ) -> "ApiResponse[Any]":
        return cls(code=code, message=message, data=detail, request_id=request_id)


class PageResult(BaseModel, Generic[T]):
    """Standard pagination envelope::

        {"items": [...], "total": 42, "page": 1, "page_size": 20, "total_pages": 3}
    """

    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int = 0

    @model_validator(mode="after")
    def _compute_total_pages(self) -> "PageResult[T]":
        if self.page_size > 0:
            self.total_pages = (self.total + self.page_size - 1) // self.page_size
        return self
