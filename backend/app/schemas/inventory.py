"""Inventory query schemas (Phase 9).

Read-only by design: the balance is a derived snapshot and the ledger is
append-only, so there is no create/update/delete schema for either.
``inventory_transactions`` has no write endpoint at all (architecture
rule 3) — corrections are reversal rows written by the receipt service.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.utils.enums import TxnSourceType, TxnType


class BalanceRow(BaseModel):
    """当前库存余额 + 安全库存联查结果（§二十四）。"""

    model_config = ConfigDict(from_attributes=True)

    warehouse_id: int
    warehouse_code: str
    warehouse_name: str
    material_id: int
    material_code: str
    material_name: str
    unit: str
    quantity: Decimal
    average_unit_cost: Decimal
    total_amount: Decimal
    #: 无库存策略时为 None（不告警）
    safety_stock: Decimal | None = None
    #: 无策略时恒为 False；有策略时为 quantity < safety_stock
    is_below_safety_stock: bool = False
    last_transaction_at: datetime | None = None


class TransactionOut(BaseModel):
    """库存流水（append-only ledger，§十 / §二十三）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    txn_no: str
    transaction_type: TxnType
    warehouse_id: int
    warehouse_code: str | None = None
    warehouse_name: str | None = None
    material_id: int
    material_code: str | None = None
    material_name: str | None = None
    unit: str | None = None
    #: 带符号：入库正、冲销负；SUM(quantity) 即库存净变化
    quantity: Decimal
    unit_cost: Decimal
    amount: Decimal
    balance_after: Decimal
    source_type: TxnSourceType | None = None
    source_id: int | None = None
    source_item_id: int | None = None
    #: 来源单据编号（PURCHASE_RECEIPT → receipt_no），便于全链路追溯
    reference_no: str | None = None
    #: 冲销流水指向被冲销的原始流水（§二十三）
    reversed_transaction_id: int | None = None
    operator_id: int | None = None
    operator_name: str | None = None
    transaction_at: datetime
    remark: str | None = None
    created_at: datetime
