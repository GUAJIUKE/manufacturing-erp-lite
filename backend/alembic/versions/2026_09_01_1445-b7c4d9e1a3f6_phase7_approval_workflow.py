"""Phase 7: purchase requisition approval workflow.

Changes needed by the approval workflow (Phase 7):

1. ``approval_records`` gains the audit-friendly columns required by
   Phase 7 §三: ``document_no`` (PR number redundancy for queries),
   ``from_status`` / ``to_status`` (pre/post action state). The existing
   ``result_status`` (post-action snapshot) is kept and kept in sync with
   ``to_status`` — backward compatible with the Phase 2 schema.

2. ``purchase_requisitions`` gains a composite index
   ``ix_pr_dept_status (department_id, status)`` for the approval-centre
   query pattern (department + PENDING, Phase 7 §二十二). Existing single
   column indexes are kept: ``status`` alone serves "my pending PRs"
   (applicant-scoped), ``department_id`` alone serves plain dept filters,
   and the composite left-prefix cannot replace either standalone query.

3. ``operation_logs.action`` ENUM is extended with PR_REVISE
   (REJECTED -> DRAFT, Phase 7 §十七). Value order matches the Python
   ``AuditAction`` enum exactly.

Revision ID: b7c4d9e1a3f6 (Phase 7, approval workflow)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

#: Alembic revision identifiers.
revision = "b7c4d9e1a3f6"
down_revision = "f2a7d3b5c9e1"
branch_labels = None
depends_on = None

#: Full action value set (26 from Phase 6 + PR_REVISE).
_AUDIT_ACTIONS = (
    "LOGIN",
    "LOGIN_FAILED",
    "PR_CREATE",
    "PR_UPDATE",
    "PR_SUBMIT",
    "PR_APPROVE",
    "PR_REJECT",
    "PR_REVISE",
    "PR_CANCEL",
    "PO_CREATE",
    "PO_CONFIRM",
    "RECEIPT_POST",
    "RECEIPT_REVERSE",
    "PERMISSION_CHANGE",
    "MATERIAL_CREATE",
    "MATERIAL_UPDATE",
    "MATERIAL_DISABLE",
    "MATERIAL_ENABLE",
    "SUPPLIER_CREATE",
    "SUPPLIER_UPDATE",
    "SUPPLIER_DISABLE",
    "SUPPLIER_ENABLE",
    "WAREHOUSE_CREATE",
    "WAREHOUSE_UPDATE",
    "WAREHOUSE_DISABLE",
    "WAREHOUSE_ENABLE",
    "INVENTORY_POLICY_CHANGE",
)

#: Value set before this migration (Phase 6).
_PREVIOUS_ACTIONS = (
    "LOGIN",
    "LOGIN_FAILED",
    "PR_CREATE",
    "PR_UPDATE",
    "PR_SUBMIT",
    "PR_APPROVE",
    "PR_REJECT",
    "PR_CANCEL",
    "PO_CREATE",
    "PO_CONFIRM",
    "RECEIPT_POST",
    "RECEIPT_REVERSE",
    "PERMISSION_CHANGE",
    "MATERIAL_CREATE",
    "MATERIAL_UPDATE",
    "MATERIAL_DISABLE",
    "MATERIAL_ENABLE",
    "SUPPLIER_CREATE",
    "SUPPLIER_UPDATE",
    "SUPPLIER_DISABLE",
    "SUPPLIER_ENABLE",
    "WAREHOUSE_CREATE",
    "WAREHOUSE_UPDATE",
    "WAREHOUSE_DISABLE",
    "WAREHOUSE_ENABLE",
    "INVENTORY_POLICY_CHANGE",
)


def _enum_ddl(values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"ENUM({quoted})"


def upgrade() -> None:
    # 1. approval_records: audit-friendly columns (Phase 7 §三)
    op.add_column(
        "approval_records",
        sa.Column(
            "document_no",
            sa.String(32),
            nullable=True,
            comment="单据编号冗余（如 PR-20260901-0001），便于审计查询（Phase 7 §三）",
        ),
    )
    op.add_column(
        "approval_records",
        sa.Column(
            "from_status",
            sa.String(32),
            nullable=True,
            comment="审批动作前状态（Phase 7 §三）",
        ),
    )
    op.add_column(
        "approval_records",
        sa.Column(
            "to_status",
            sa.String(32),
            nullable=True,
            comment="审批动作后状态（Phase 7 §三）",
        ),
    )
    op.alter_column(
        "approval_records",
        "result_status",
        existing_type=sa.String(32),
        existing_nullable=False,
        comment="动作执行后单据状态快照（与 to_status 同步）",
    )

    # 2. PR: composite index for the approval-centre query (Phase 7 §二十二)
    op.create_index("ix_pr_dept_status", "purchase_requisitions", ["department_id", "status"])

    # 3. audit: PR_REVISE action
    op.execute(
        f"ALTER TABLE operation_logs "
        f"MODIFY COLUMN action {_enum_ddl(_AUDIT_ACTIONS)} NOT NULL"
    )


def downgrade() -> None:
    op.execute(
        f"ALTER TABLE operation_logs "
        f"MODIFY COLUMN action {_enum_ddl(_PREVIOUS_ACTIONS)} NOT NULL"
    )
    op.drop_index("ix_pr_dept_status", table_name="purchase_requisitions")
    op.alter_column(
        "approval_records",
        "result_status",
        existing_type=sa.String(32),
        existing_nullable=False,
        comment="动作执行后单据状态快照",
    )
    op.drop_column("approval_records", "to_status")
    op.drop_column("approval_records", "from_status")
    op.drop_column("approval_records", "document_no")
