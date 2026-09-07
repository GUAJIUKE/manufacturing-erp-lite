"""Numbering service regression tests (CR-A-008).

Implementation A modified the *shared* numbering behaviour
(``numbering_service.next_sequence_value`` now writes then re-reads the row
value instead of trusting ``LAST_INSERT_ID()``, because a real INSERT overwrites
``LAST_INSERT_ID()`` with the table's auto-increment PK). These tests pin the
contract on the shared table while never disturbing real document flows:

* daily keys are allocated on synthetic far-future dates;
* the global keys (MAT/SUP/WH) share the fixed 1970-01-01 row with every
  material / supplier / warehouse created anywhere in the suite, so they are
  only exercised for increment/uniqueness — never "first == 1";
* every row created here is deleted at the end of its test (nothing has an FK
  to ``number_sequences``).

Alembic migrations are NOT touched — this is pure behavioural regression on the
already-approved architecture (unique ``uk_seq`` row lock + monotonic counters,
gaps allowed, duplicates forbidden).
"""

from __future__ import annotations

import threading
from datetime import date

import pytest
from sqlalchemy import select, text

from app.db.session import SessionLocal
from app.models import NumberSequence
from app.services import numbering_service
from app.utils.enums import SequenceKey

#: Daily-reset keys exercised with synthetic dates (never colliding with real
#: document counters for today's date).
_DAILY_KEYS = [
    SequenceKey.PURCHASE_REQUISITION,
    SequenceKey.PURCHASE_ORDER,
    SequenceKey.PURCHASE_RECEIPT,
    SequenceKey.INVENTORY_TRANSACTION,
    SequenceKey.STOCK_RECONCILIATION,
]


def _clean(key: SequenceKey, d: date) -> None:
    """Delete rows this test created (safe: no FK references number_sequences)."""
    with SessionLocal() as s:
        s.execute(
            text("DELETE FROM number_sequences WHERE sequence_key = :k AND sequence_date = :d"),
            {"k": key.value, "d": d},
        )
        s.commit()


def _stored(key: SequenceKey, d: date) -> int:
    with SessionLocal() as s:
        s.rollback()
        return s.execute(
            select(NumberSequence.current_value).where(
                NumberSequence.sequence_key == key.value,
                NumberSequence.sequence_date == d,
            )
        ).scalar_one()


@pytest.mark.parametrize("key", _DAILY_KEYS)
def test_daily_first_and_second_allocation(key: SequenceKey) -> None:
    """新序列首号 = 1，次号 = 2（写后回读修复的直接回归）。"""
    d = date(2031, 1, 1)
    _clean(key, d)
    try:
        with SessionLocal() as s:
            first = numbering_service.next_sequence_value(s, key, d)
            second = numbering_service.next_sequence_value(s, key, d)
            s.commit()
        assert first == 1, f"{key}: first={first}"
        assert second == 2, f"{key}: second={second}"
        assert _stored(key, d) == 2
    finally:
        _clean(key, d)


def test_global_key_increments_monotonically() -> None:
    """全局序列（固定 1970-01-01）：连续两次取号严格 +1 且唯一。"""
    with SessionLocal() as s:
        first = numbering_service.next_sequence_value(s, SequenceKey.MATERIAL)
        second = numbering_service.next_sequence_value(s, SequenceKey.MATERIAL)
        s.commit()
    assert second == first + 1
    assert second != first


def test_new_sequence_unaffected_by_previous_auto_increment_pks() -> None:
    """存量行的自增主键推到高位后，新 (key,date) 首号仍必须是 1（修复的根因）。"""
    key = SequenceKey.PURCHASE_ORDER
    d = date(2033, 5, 17)
    _clean(key, d)
    try:
        # 造 60 个其它 (key,date) 行，把 number_sequences 的表级 AUTO_INCREMENT 推高
        with SessionLocal() as s:
            for i in range(60):
                s.execute(
                    text("INSERT INTO number_sequences (sequence_key, sequence_date, current_value) "
                         "VALUES (:k, :d, :v)"),
                    {"k": f"TMP{i:02d}", "d": date(2033, 5, 1), "v": 1},
                )
            s.commit()
        with SessionLocal() as s:
            first = numbering_service.next_sequence_value(s, key, d)
            second = numbering_service.next_sequence_value(s, key, d)
            s.commit()
        assert first == 1 and second == 2
        assert _stored(key, d) == 2
    finally:
        _clean(key, d)
        with SessionLocal() as s:
            s.execute(text("DELETE FROM number_sequences WHERE sequence_key LIKE 'TMP%'"))
            s.commit()


def test_concurrent_first_use_does_not_duplicate() -> None:
    """4 线程同时首次取同一 (key,date)：恰好拿到 1..4，无重复（uk_seq 行锁串行）。"""
    key = SequenceKey.STOCK_RECONCILIATION
    d = date(2034, 3, 9)
    _clean(key, d)
    n = 4
    barrier = threading.Barrier(n)
    results: list[int] = []
    guard = threading.Lock()

    def worker() -> None:
        barrier.wait()
        with SessionLocal() as s:
            v = numbering_service.next_sequence_value(s, key, d)
            s.commit()
        with guard:
            results.append(v)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sorted(results) == list(range(1, n + 1)), results
        assert len(set(results)) == n  # 无重复
        assert _stored(key, d) == n
    finally:
        _clean(key, d)
