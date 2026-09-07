"""Unified exception hierarchy and business error codes.

Design rules
------------
* Every expected failure is raised as an :class:`AppException` subclass.
* HTTP status carries the *semantic* category (401/403/404/409/422),
  while ``code`` carries the precise business reason for the frontend.
* Services raise these exceptions; the global handlers in
  :mod:`app.core.exception_handlers` translate them into
  :class:`app.core.response.ApiResponse`.

Error code ranges
-----------------
===== =========================================
1xxx  generic / validation
2xxx  authentication & authorization
3xxx  master data
4xxx  purchase requisition
5xxx  purchase order
6xxx  receiving & inventory
7xxx  stock reconciliation (Sprint 1 / Impl. A)
===== =========================================
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any

from fastapi import status


class ErrorCode(IntEnum):
    OK = 0

    # 1xxx generic
    INTERNAL_ERROR = 1000
    VALIDATION_ERROR = 1001
    NOT_FOUND = 1002
    CONFLICT = 1003
    DUPLICATE_KEY = 1004

    # 2xxx auth
    UNAUTHORIZED = 2001
    FORBIDDEN = 2002
    INVALID_CREDENTIALS = 2003
    USER_DISABLED = 2004
    PERMISSION_DENIED = 2005

    # 3xxx master data
    MATERIAL_CODE_EXISTS = 3001
    MATERIAL_IN_USE = 3002
    SUPPLIER_CODE_EXISTS = 3003
    SUPPLIER_IN_USE = 3004
    WAREHOUSE_CODE_EXISTS = 3005
    USERNAME_EXISTS = 3006
    DEPARTMENT_CODE_EXISTS = 3007
    ROLE_CODE_EXISTS = 3008
    MASTER_DATA_DISABLED = 3009
    WAREHOUSE_HAS_STOCK = 3010
    INVENTORY_POLICY_DUPLICATE = 3011

    # 4xxx purchase requisition
    PR_NOT_FOUND = 4001
    PR_INVALID_STATUS_TRANSITION = 4002
    PR_NOT_EDITABLE = 4003
    PR_EMPTY_ITEMS = 4004
    PR_NOT_APPLICANT = 4005
    PR_REJECT_COMMENT_REQUIRED = 4006
    PR_NOT_APPROVER = 4007
    PR_CANCEL_HAS_ACTIVE_PO = 4008
    PR_ITEM_CONVERT_EXCEEDED = 4009
    PR_ITEM_NOT_FOUND = 4010
    # Phase 7: approval workflow
    PR_VERSION_CONFLICT = 4011  # 乐观锁：客户端 version 已过期
    PR_ALREADY_PROCESSED = 4012  # 单据已被其他审批动作处理（并发/重复审批）

    # 5xxx purchase order
    PO_NOT_FOUND = 5001
    PO_INVALID_STATUS_TRANSITION = 5002
    PO_NOT_EDITABLE = 5003
    PO_EMPTY_ITEMS = 5004
    PO_SUPPLIER_REQUIRED = 5005
    PO_SUPPLIER_DISABLED = 5006
    PO_UNIT_PRICE_REQUIRED = 5007
    PO_CANCEL_HAS_RECEIPT = 5008
    PO_NOT_RECEIVABLE = 5009
    PO_SOURCE_QUANTITY_MISMATCH = 5010  # 来源数量合计必须严格等于订购数量（Review fix）
    PO_ITEM_NOT_FOUND = 5011
    # Phase 8: PO optimistic lock / concurrent processing (mirrors PR 4011/4012)
    PO_VERSION_CONFLICT = 5012  # 乐观锁：客户端 version 已过期
    PO_ALREADY_PROCESSED = 5013  # 单据已被其他动作处理（并发/重复确认、取消）

    # 6xxx receiving & inventory
    RECEIPT_NOT_FOUND = 6001
    RECEIPT_EXCEEDS_REMAINING = 6002
    RECEIPT_EMPTY_ITEMS = 6003
    RECEIPT_DUPLICATE_ITEM = 6004
    RECEIPT_ALREADY_REVERSED = 6005
    RECEIPT_NOT_POSTED = 6006
    REVERSE_REASON_REQUIRED = 6007
    RECEIPT_QUANTITY_POSITIVE = 6008
    INVENTORY_NEGATIVE = 6009
    INVENTORY_BALANCE_MISMATCH = 6010
    INVENTORY_TXN_APPEND_ONLY = 6011
    # Phase 9: 入库明细归属校验
    RECEIPT_ITEM_NOT_IN_PO = 6012  # po_item 不属于指定 PO（§五.10）

    # 7xxx stock reconciliation (Reality Hardening Sprint 1 / Implementation A)
    # 仅实现 A 实际用到的错误码；Freeze / True Backdate / Diagnostic 相关码不建。
    RECONCILIATION_NOT_FOUND = 7001
    RECONCILIATION_INVALID_STATUS = 7002
    RECONCILIATION_VERSION_CONFLICT = 7003
    RECONCILIATION_BALANCE_CHANGED = 7005  # Snapshot Guard：item stale（DA-001 / OQ-12）
    RECONCILIATION_ALREADY_PROCESSED = 7006  # CAS 认领失败（并发重复审批）
    RECONCILIATION_SELF_APPROVAL = 7007  # SoD：审批人 == 盘点人（未 override）
    RECONCILIATION_OVERRIDE_REASON_REQUIRED = 7008
    RECONCILIATION_EMPTY_ITEMS = 7009
    RECONCILIATION_PHYSICAL_NEGATIVE = 7011
    RECONCILIATION_ITEM_NOT_FOUND = 7014
    RECONCILIATION_VALUATION_RATE_REQUIRED = 7017  # 盘盈行缺失/≤0 valuation_rate（DA-002）


class AppException(Exception):
    """Base class for all expected application errors."""

    code: ErrorCode = ErrorCode.INTERNAL_ERROR
    http_status: int = status.HTTP_409_CONFLICT
    default_message: str = "请求处理失败"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: ErrorCode | None = None,
        http_status: int | None = None,
        detail: Any = None,
    ) -> None:
        self.message = message or self.default_message
        if code is not None:
            self.code = code
        if http_status is not None:
            self.http_status = http_status
        self.detail = detail
        super().__init__(self.message)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<{type(self).__name__} code={int(self.code)} "
            f"http={self.http_status} message={self.message!r}>"
        )


# ----------------------------------------------------------------------
# Generic
# ----------------------------------------------------------------------
class ValidationException(AppException):
    code = ErrorCode.VALIDATION_ERROR
    http_status = status.HTTP_422_UNPROCESSABLE_CONTENT
    default_message = "参数校验失败"


class NotFoundException(AppException):
    code = ErrorCode.NOT_FOUND
    http_status = status.HTTP_404_NOT_FOUND
    default_message = "记录不存在"


class ConflictException(AppException):
    code = ErrorCode.CONFLICT
    http_status = status.HTTP_409_CONFLICT
    default_message = "数据冲突"


# ----------------------------------------------------------------------
# Authentication & authorization
# ----------------------------------------------------------------------
class UnauthorizedException(AppException):
    code = ErrorCode.UNAUTHORIZED
    http_status = status.HTTP_401_UNAUTHORIZED
    default_message = "未认证或登录已过期"


class InvalidCredentialsException(AppException):
    code = ErrorCode.INVALID_CREDENTIALS
    http_status = status.HTTP_401_UNAUTHORIZED
    default_message = "用户名或密码错误"


class UserDisabledException(AppException):
    code = ErrorCode.USER_DISABLED
    http_status = status.HTTP_403_FORBIDDEN
    default_message = "账号已被禁用"


class ForbiddenException(AppException):
    code = ErrorCode.FORBIDDEN
    http_status = status.HTTP_403_FORBIDDEN
    default_message = "无权访问该资源"


class PermissionDeniedException(AppException):
    code = ErrorCode.PERMISSION_DENIED
    http_status = status.HTTP_403_FORBIDDEN
    default_message = "权限不足，无法执行该操作"


# ----------------------------------------------------------------------
# Business: purchase requisition
# ----------------------------------------------------------------------
class InvalidStatusTransitionException(AppException):
    code = ErrorCode.PR_INVALID_STATUS_TRANSITION
    http_status = status.HTTP_409_CONFLICT
    default_message = "当前单据状态不允许执行该操作"


class ReceiptExceedsRemainingException(AppException):
    code = ErrorCode.RECEIPT_EXCEEDS_REMAINING
    http_status = status.HTTP_409_CONFLICT
    default_message = "入库数量超过采购订单剩余未到货数量"


class InventoryNegativeException(AppException):
    code = ErrorCode.INVENTORY_NEGATIVE
    http_status = status.HTTP_409_CONFLICT
    default_message = "库存不足，操作将导致负库存"


class InventoryTxnAppendOnlyException(AppException):
    code = ErrorCode.INVENTORY_TXN_APPEND_ONLY
    http_status = status.HTTP_409_CONFLICT
    default_message = "库存流水为只追加账本，禁止修改或删除，请通过反向流水冲销"


# ----------------------------------------------------------------------
# Business: stock reconciliation (Reality Hardening Sprint 1)
# ----------------------------------------------------------------------
class ReconciliationNotFoundException(AppException):
    code = ErrorCode.RECONCILIATION_NOT_FOUND
    http_status = status.HTTP_404_NOT_FOUND
    default_message = "库存盘点单不存在"


class ReconciliationInvalidStatusException(AppException):
    code = ErrorCode.RECONCILIATION_INVALID_STATUS
    http_status = status.HTTP_409_CONFLICT
    default_message = "当前盘点单状态不允许执行该操作"


class ReconciliationVersionConflictException(AppException):
    code = ErrorCode.RECONCILIATION_VERSION_CONFLICT
    http_status = status.HTTP_409_CONFLICT
    default_message = "盘点单已被他人修改，请刷新后重试（版本冲突）"


class ReconciliationBalanceChangedException(AppException):
    code = ErrorCode.RECONCILIATION_BALANCE_CHANGED
    http_status = status.HTTP_409_CONFLICT
    default_message = (
        "盘点后该仓该料又发生业务，盘点基准已漂移（stale）；"
        "请刷新库存、确认实物后新建盘点单"
    )


class ReconciliationAlreadyProcessedException(AppException):
    code = ErrorCode.RECONCILIATION_ALREADY_PROCESSED
    http_status = status.HTTP_409_CONFLICT
    default_message = "盘点单已被其他审批动作处理，请刷新后重试"


class ReconciliationSelfApprovalException(AppException):
    code = ErrorCode.RECONCILIATION_SELF_APPROVAL
    http_status = status.HTTP_403_FORBIDDEN
    default_message = "盘点人不能审批自己创建的盘点单（SoD）"


class ReconciliationOverrideReasonRequiredException(AppException):
    code = ErrorCode.RECONCILIATION_OVERRIDE_REASON_REQUIRED
    http_status = status.HTTP_422_UNPROCESSABLE_CONTENT
    default_message = "SoD override 必须提供理由（override_reason）"


class ReconciliationValuationRateRequiredException(AppException):
    code = ErrorCode.RECONCILIATION_VALUATION_RATE_REQUIRED
    http_status = status.HTTP_422_UNPROCESSABLE_CONTENT
    default_message = "盘盈（ADJUST_IN）行必须提供 valuation_rate 且大于 0（DA-002）"
