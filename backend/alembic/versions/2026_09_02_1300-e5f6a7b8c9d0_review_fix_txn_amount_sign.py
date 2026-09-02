"""Review Fix §1: constrain inventory_transactions.amount sign.

Phase 9 review asked for the ledger amount to be signed exactly like the
quantity, so that

    SUM(quantity)  (per warehouse + material) == balance.quantity
    SUM(amount)    (per warehouse + material) == balance.total_amount

The old ``ck_inventory_transactions_it_sign`` CHECK only constrained the
*quantity* sign against the transaction type; the *amount* column was free,
so a PURCHASE_IN_REVERSAL row could in theory carry a positive amount and
silently break the SUM(amount) reconciliation.

This migration replaces that CHECK with one that also forces ``amount`` to
share the sign of ``quantity`` (inbound > 0 / reversal & outbound < 0,
zero allowed only for the sub-cent rounding edge, see model comment).

No historical migration is touched. Only the CHECK is re-created.

Revision ID: e5f6a7b8c9d0
Revises:     c3f8a1d2b7e9 (Phase 9)
"""

from alembic import op

#: Alembic revision identifiers.
revision = "e5f6a7b8c9d0"
down_revision = "c3f8a1d2b7e9"

#: MySQL stores the constraint under the naming-convention-expanded name.
_IT_SIGN_CHECK = "ck_inventory_transactions_it_sign"

_NEW_CHECK = (
    "(transaction_type IN ('PURCHASE_IN','ADJUST_IN','PRODUCTION_IN')"
    " AND quantity > 0 AND amount >= 0)"
    " OR (transaction_type IN ('PURCHASE_IN_REVERSAL','ADJUST_OUT','PRODUCTION_OUT')"
    " AND quantity < 0 AND amount <= 0)"
)

#: The original constraint from the Phase 2 base migration (quantity only).
_OLD_CHECK = (
    "(transaction_type IN ('PURCHASE_IN','ADJUST_IN','PRODUCTION_IN') AND quantity > 0)"
    " OR (transaction_type IN ('PURCHASE_IN_REVERSAL','ADJUST_OUT','PRODUCTION_OUT') AND quantity < 0)"
)


def upgrade() -> None:
    op.execute(f"ALTER TABLE inventory_transactions DROP CHECK {_IT_SIGN_CHECK}")
    op.execute(
        f"ALTER TABLE inventory_transactions "
        f"ADD CONSTRAINT {_IT_SIGN_CHECK} CHECK ({_NEW_CHECK})"
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE inventory_transactions DROP CHECK {_IT_SIGN_CHECK}")
    op.execute(
        f"ALTER TABLE inventory_transactions "
        f"ADD CONSTRAINT {_IT_SIGN_CHECK} CHECK ({_OLD_CHECK})"
    )
