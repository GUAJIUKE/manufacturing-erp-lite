"""Domain enumerations.

Every value here maps 1:1 to a MySQL ENUM column defined in
``docs/database-design.md``. Keep the two in sync: changing a value here
without a matching Alembic migration will break persistence.
"""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """Enum whose members are also plain strings (JSON / DB friendly)."""

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return str(self.value)


# ----------------------------------------------------------------------
# Common
# ----------------------------------------------------------------------
class ActiveStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class DeptStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


# ----------------------------------------------------------------------
# Purchase Requisition  (Q1: REJECTED -> DRAFT -> PENDING)
# ----------------------------------------------------------------------
class PrStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    CONVERTED = "CONVERTED"


# ----------------------------------------------------------------------
# Purchase Order
# ----------------------------------------------------------------------
class PoStatus(StrEnum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


# ----------------------------------------------------------------------
# Purchase Receipt  (Q6: REVERSED, no DRAFT in phase 1)
# ----------------------------------------------------------------------
class ReceiptStatus(StrEnum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


# ----------------------------------------------------------------------
# Inventory
# ----------------------------------------------------------------------
class TxnType(StrEnum):
    """Inventory transaction type.

    IMPORTANT: ``PURCHASE_IN_REVERSAL`` must never be replaced by
    ``ADJUST_OUT``. The dedicated type preserves business semantics and
    makes purchase reversals auditable and reportable.
    """

    PURCHASE_IN = "PURCHASE_IN"
    PURCHASE_IN_REVERSAL = "PURCHASE_IN_REVERSAL"
    ADJUST_IN = "ADJUST_IN"
    ADJUST_OUT = "ADJUST_OUT"
    PRODUCTION_OUT = "PRODUCTION_OUT"
    PRODUCTION_IN = "PRODUCTION_IN"


#: Transaction types that add stock (quantity is positive).
TXN_INBOUND_TYPES: frozenset[TxnType] = frozenset(
    {TxnType.PURCHASE_IN, TxnType.ADJUST_IN, TxnType.PRODUCTION_IN}
)

#: Transaction types that remove stock (quantity is negative).
TXN_OUTBOUND_TYPES: frozenset[TxnType] = frozenset(
    {TxnType.PURCHASE_IN_REVERSAL, TxnType.ADJUST_OUT, TxnType.PRODUCTION_OUT}
)


class TxnSourceType(StrEnum):
    """Polymorphic source document type (logical reference, not a FK)."""

    PURCHASE_RECEIPT = "PURCHASE_RECEIPT"
    PURCHASE_RECEIPT_REVERSAL = "PURCHASE_RECEIPT_REVERSAL"
    MANUAL_ADJUST = "MANUAL_ADJUST"
    PRODUCTION_ISSUE = "PRODUCTION_ISSUE"
    PRODUCTION_RECEIPT = "PRODUCTION_RECEIPT"


# ----------------------------------------------------------------------
# Approval  (Q11: single level now, step_no reserved for multi-level)
# ----------------------------------------------------------------------
class DocumentType(StrEnum):
    PURCHASE_REQUISITION = "PURCHASE_REQUISITION"
    PURCHASE_ORDER = "PURCHASE_ORDER"


class ApprovalAction(StrEnum):
    SUBMIT = "SUBMIT"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    CANCEL = "CANCEL"


# ----------------------------------------------------------------------
# RBAC
# ----------------------------------------------------------------------
class RoleCode(StrEnum):
    ADMIN = "ADMIN"
    APPLICANT = "APPLICANT"
    DEPT_MANAGER = "DEPT_MANAGER"
    BUYER = "BUYER"
    WAREHOUSE = "WAREHOUSE"


# ----------------------------------------------------------------------
# Audit  (Q15: key business operations only)
# ----------------------------------------------------------------------
class AuditAction(StrEnum):
    LOGIN = "LOGIN"
    LOGIN_FAILED = "LOGIN_FAILED"
    # Phase 6: purchase requisition
    PR_CREATE = "PR_CREATE"
    PR_UPDATE = "PR_UPDATE"
    PR_SUBMIT = "PR_SUBMIT"
    PR_APPROVE = "PR_APPROVE"
    PR_REJECT = "PR_REJECT"
    PR_REVISE = "PR_REVISE"  # Phase 7: REJECTED -> DRAFT 重新编辑
    PR_CANCEL = "PR_CANCEL"
    PO_CREATE = "PO_CREATE"
    PO_CONFIRM = "PO_CONFIRM"
    PO_CANCEL = "PO_CANCEL"  # Phase 8: 取消订单（DRAFT/CONFIRMED -> CANCELLED）
    RECEIPT_POST = "RECEIPT_POST"
    RECEIPT_REVERSE = "RECEIPT_REVERSE"
    PERMISSION_CHANGE = "PERMISSION_CHANGE"
    # Phase 5: master data
    MATERIAL_CREATE = "MATERIAL_CREATE"
    MATERIAL_UPDATE = "MATERIAL_UPDATE"
    MATERIAL_DISABLE = "MATERIAL_DISABLE"
    MATERIAL_ENABLE = "MATERIAL_ENABLE"
    SUPPLIER_CREATE = "SUPPLIER_CREATE"
    SUPPLIER_UPDATE = "SUPPLIER_UPDATE"
    SUPPLIER_DISABLE = "SUPPLIER_DISABLE"
    SUPPLIER_ENABLE = "SUPPLIER_ENABLE"
    WAREHOUSE_CREATE = "WAREHOUSE_CREATE"
    WAREHOUSE_UPDATE = "WAREHOUSE_UPDATE"
    WAREHOUSE_DISABLE = "WAREHOUSE_DISABLE"
    WAREHOUSE_ENABLE = "WAREHOUSE_ENABLE"
    INVENTORY_POLICY_CHANGE = "INVENTORY_POLICY_CHANGE"


# ----------------------------------------------------------------------
# Numbering
# ----------------------------------------------------------------------
class SequenceKey(StrEnum):
    MATERIAL = "MAT"
    SUPPLIER = "SUP"
    WAREHOUSE = "WH"
    PURCHASE_REQUISITION = "PR"
    PURCHASE_ORDER = "PO"
    PURCHASE_RECEIPT = "REC"
    INVENTORY_TRANSACTION = "TXN"


#: Keys whose sequence never resets (global counter instead of a daily one).
GLOBAL_SEQUENCE_KEYS: frozenset[SequenceKey] = frozenset(
    {SequenceKey.MATERIAL, SequenceKey.SUPPLIER, SequenceKey.WAREHOUSE}
)
