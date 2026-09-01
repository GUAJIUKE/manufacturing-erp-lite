"""Business document numbering service (architecture rule 1).

Concurrency-safe sequence generation shared by MAT / SUP / WH (and later
PR / PO / REC / TXN) using a single-statement upsert:

    INSERT INTO number_sequences(sequence_key, sequence_date, current_value)
    VALUES (:key, :date, 1)
    ON DUPLICATE KEY UPDATE current_value = LAST_INSERT_ID(current_value + 1)

* The unique index ``uk_seq(sequence_key, sequence_date)`` turns the upsert
  into an X-lock on that one row. Two concurrent callers for the same key are
  serialized at the DB level, so values never repeat.
* ``LAST_INSERT_ID(expr)`` both assigns and returns the new value in one
  statement — no SELECT-after-UPDATE race window.
* Gaps are allowed (architecture rule 1: no strict continuity, no number
  recycling). The ``uk_seq`` unique index is the final backstop against
  duplicates; ``material_code / supplier_code / warehouse_code`` also carry
  their own UNIQUE constraints.

Lock lifetime note: ``next_sequence_value`` is meant to run *inside* the
caller's business transaction. The row lock is then held until that
transaction commits — concurrent creations of the same entity type serialize,
which is exactly what guarantees unique codes. Because the lock is a single
index-row X lock (not a table lock) and entity creation is a short
transaction, contention is negligible for this project's scale.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.orm import Session

from app.models import NumberSequence
from app.utils.enums import GLOBAL_SEQUENCE_KEYS, SequenceKey

#: Fixed business date for never-resetting (global) sequences.
_GLOBAL_DATE = date(1970, 1, 1)


def next_sequence_value(db: Session, key: SequenceKey, sequence_date: date | None = None) -> int:
    """Allocate the next sequence value for ``key`` (global or per-day).

    ``sequence_date`` is only meaningful for daily-reset keys (PR/PO/REC/TXN);
    global keys (MAT/SUP/WH) always use 1970-01-01 regardless.
    """
    if sequence_date is None:
        sequence_date = _GLOBAL_DATE if key in GLOBAL_SEQUENCE_KEYS else date.today()

    stmt = insert(NumberSequence).values(
        sequence_key=key.value,
        sequence_date=sequence_date,
        # 关键：VALUES 分支必须显式 LAST_INSERT_ID(1)。
        # 否则 INSERT 分支下 LAST_INSERT_ID() 返回的是 number_sequences 的
        # AUTO_INCREMENT 主键（如 5/7），而非期望的 1 —— 首次取号会得到错误
        # 大号（SUP-000005 / WH-000007），后续递增回来后撞唯一键。
        current_value=func.last_insert_id(1),
    )
    stmt = stmt.on_duplicate_key_update(
        current_value=func.last_insert_id(NumberSequence.current_value + 1)
    )
    db.execute(stmt)
    value = db.execute(select(func.last_insert_id())).scalar_one()
    return int(value)


def format_code(prefix: str, seq: int) -> str:
    """Render a sequence value as a business code, e.g. MAT-000001."""
    return f"{prefix}-{seq:06d}"


def next_code(db: Session, key: SequenceKey, prefix: str) -> str:
    """Convenience: allocate and format in one call (MAT/SUP/WH)."""
    return format_code(prefix, next_sequence_value(db, key))
