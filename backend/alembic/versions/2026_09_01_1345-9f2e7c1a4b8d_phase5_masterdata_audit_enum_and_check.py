"""Phase 5: extend audit action ENUM + tighten inventory_policies.max_stock CHECK.

Two schema changes needed by the master-data module (Phase 5):

1. ``operation_logs.action`` is a MySQL ENUM column; Phase 5 introduces
   master-data audit actions (MATERIAL_*/SUPPLIER_*/WAREHOUSE_*,
   INVENTORY_POLICY_CHANGE). The column must be redefined with the full
   value list.

2. ``inventory_policies.max_stock`` CHECK was ``>= 0``; the business rule
   (Phase 5 §四.4) requires ``> 0`` when present. MySQL has no ALTER CHECK,
   so the constraint is dropped and re-added.

Revision ID: 9f2e7c1a4b8d (Phase 5, master data)
"""

from __future__ import annotations

from alembic import op

#: Alembic revision identifiers.
revision = "9f2e7c1a4b8d"
down_revision = "0d8e51ed6370"
branch_labels = None
depends_on = None

#: Full action value set (11 original + 13 Phase-5 values).
_AUDIT_ACTIONS = (
    "LOGIN",
    "LOGIN_FAILED",
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

#: Original value set (Phase 3).
_ORIGINAL_ACTIONS = (
    "LOGIN",
    "LOGIN_FAILED",
    "PR_SUBMIT",
    "PR_APPROVE",
    "PR_REJECT",
    "PR_CANCEL",
    "PO_CREATE",
    "PO_CONFIRM",
    "RECEIPT_POST",
    "RECEIPT_REVERSE",
    "PERMISSION_CHANGE",
)

_MAX_STOCK_CHECK = "ck_inventory_policies_max_stock_nonneg"


def _enum_ddl(values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"ENUM({quoted})"


def upgrade() -> None:
    op.execute(
        f"ALTER TABLE operation_logs "
        f"MODIFY COLUMN action {_enum_ddl(_AUDIT_ACTIONS)} NOT NULL"
    )
    op.execute(f"ALTER TABLE inventory_policies DROP CHECK {_MAX_STOCK_CHECK}")
    op.execute(
        f"ALTER TABLE inventory_policies "
        f"ADD CONSTRAINT {_MAX_STOCK_CHECK} CHECK (max_stock IS NULL OR max_stock > 0)"
    )


def downgrade() -> None:
    op.execute(
        f"ALTER TABLE inventory_policies DROP CHECK {_MAX_STOCK_CHECK}"
    )
    op.execute(
        f"ALTER TABLE inventory_policies "
        f"ADD CONSTRAINT {_MAX_STOCK_CHECK} CHECK (max_stock IS NULL OR max_stock >= 0)"
    )
    op.execute(
        f"ALTER TABLE operation_logs "
        f"MODIFY COLUMN action {_enum_ddl(_ORIGINAL_ACTIONS)} NOT NULL"
    )
