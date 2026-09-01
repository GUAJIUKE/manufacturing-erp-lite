"""Centralized money / quantity arithmetic (Phase 6 §八).

All business amount calculations MUST go through these helpers so the
rounding policy lives in exactly one place instead of being scattered
across services. Python ``Decimal`` only — float is banned for business
money/quantity math.

Rounding policy (finance convention): ``ROUND_HALF_UP`` to 2 decimals.

* ``line_amount(qty, price)``  → ROUND_HALF_UP(qty × price, 2)
* ``sum_amounts(iterable)``    → ROUND_HALF_UP(sum, 2)
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

#: Money precision: 2 decimal places.
_MONEY_QUANT = Decimal("0.01")

#: Quantity / unit-price scale accepted by the API layer (4 decimals).
QUANTITY_QUANT = Decimal("0.0001")


def money(value: Decimal) -> Decimal:
    """Round a Decimal to 2 places using ROUND_HALF_UP."""
    return value.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)


def line_amount(requested_quantity: Decimal, estimated_unit_price: Decimal) -> Decimal:
    """Per-line estimated amount: ROUND_HALF_UP(qty × price, 2)."""
    return money(requested_quantity * estimated_unit_price)


def sum_amounts(amounts: Iterable[Decimal]) -> Decimal:
    """Header total: ROUND_HALF_UP(sum of per-line amounts, 2)."""
    return money(sum(amounts, Decimal("0")))
