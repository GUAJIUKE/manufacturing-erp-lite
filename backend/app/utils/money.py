"""Centralized money / quantity arithmetic (Phase 6 §八).

All business amount calculations MUST go through these helpers so the
rounding policy lives in exactly one place instead of being scattered
across services. Python ``Decimal`` only — float is banned for business
money/quantity math.

Rounding policy (finance convention): ``ROUND_HALF_UP``.

* ``line_amount(qty, price)``  → ROUND_HALF_UP(qty × price, 2)  金额
* ``unit_cost(value)``         → ROUND_HALF_UP(value, 4)        单价/平均成本
* ``sum_amounts(iterable)``    → ROUND_HALF_UP(sum, 2)          单据合计

Phase 9 addition: inventory moving-average cost is a *unit price*, not a
money amount, so it needs its own 4-decimal helper instead of ``money()``.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

#: Money precision: 2 decimal places.
_MONEY_QUANT = Decimal("0.01")

#: Unit-cost / quantity precision: 4 decimal places.
_COST_QUANT = Decimal("0.0001")

#: Quantity / unit-price scale accepted by the API layer (4 decimals).
QUANTITY_QUANT = Decimal("0.0001")


def money(value: Decimal) -> Decimal:
    """Round a Decimal to 2 places using ROUND_HALF_UP."""
    return value.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)


def unit_cost(value: Decimal) -> Decimal:
    """Round a unit cost / average cost to 4 places using ROUND_HALF_UP.

    Used by the moving-average inventory costing (Phase 9 §十二): the
    balance's ``total_amount`` stays authoritative at 2 decimals, while
    ``average_unit_cost`` is a derived display / issue-price value.
    """
    return value.quantize(_COST_QUANT, rounding=ROUND_HALF_UP)


def line_amount(requested_quantity: Decimal, estimated_unit_price: Decimal) -> Decimal:
    """Per-line estimated amount: ROUND_HALF_UP(qty × price, 2)."""
    return money(requested_quantity * estimated_unit_price)


def sum_amounts(amounts: Iterable[Decimal]) -> Decimal:
    """Header total: ROUND_HALF_UP(sum of per-line amounts, 2)."""
    return money(sum(amounts, Decimal("0")))
