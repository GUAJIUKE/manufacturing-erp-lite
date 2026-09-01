"""Audit log writer (Q15).

- Business-operation logs (PR_* / PO_* / RECEIPT_*) are written inside the
  business transaction: if the business rolls back, the log rolls back too.
- Login logs (LOGIN / LOGIN_FAILED) use an independent transaction.
- PERMISSION_CHANGE shares the transaction with the grant operation.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import OperationLog, User
from app.utils.enums import AuditAction


def write_audit(
    db: Session,
    *,
    action: AuditAction,
    module: str,
    operator: User | None = None,
    username_snapshot: str | None = None,
    document_type: str | None = None,
    document_id: int | None = None,
    description: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> OperationLog:
    """Write one audit row on the given session.

    The caller decides the transaction boundary: pass the business session to
    share the transaction, or a fresh session for independent commits.
    """
    log = OperationLog(
        operator_id=operator.id if operator else None,
        username_snapshot=username_snapshot or (operator.username if operator else None),
        action=action,
        module=module,
        document_type=document_type,
        document_id=document_id,
        description=description,
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    db.add(log)
    return log
