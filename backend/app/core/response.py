"""Unified API response envelope.

Every endpoint returns::

    {"code": 0, "message": "success", "data": ..., "request_id": "..."}

``code != 0`` marks a business error; HTTP status still carries the
semantic category. Paginated results use :class:`PageResult`.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel

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

        {"items": [...], "total": 42, "page": 1, "page_size": 20}
    """

    items: list[T]
    total: int
    page: int
    page_size: int

    @property
    def total_pages(self) -> int:
        if self.page_size <= 0:
            return 0
        return (self.total + self.page_size - 1) // self.page_size
