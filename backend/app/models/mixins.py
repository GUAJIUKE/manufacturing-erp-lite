"""Shared column mixins.

Keeps the four "audit" columns (id / created_at / updated_at) declared once
instead of repeated on every model. Mirrors the common columns defined in
``docs/database-design.md`` §1.1.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import  DateTime, func
from sqlalchemy.dialects.mysql import BIGINT as BigInteger, DATETIME

from sqlalchemy.orm import Mapped, mapped_column


class PKMixin:
    """BIGINT UNSIGNED auto-increment primary key."""

    id: Mapped[int] = mapped_column(
        BigInteger(unsigned=True),
        primary_key=True,
        autoincrement=True,
        comment="Primary key",
    )


class TimestampMixin:
    """created_at / updated_at with DB-side defaults (DATETIME(3) to match
    every table in docs/database-design.md)."""

    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        nullable=False,
        server_default=func.current_timestamp(3),
        comment="Created at (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        nullable=False,
        server_default=func.current_timestamp(3),
        onupdate=func.current_timestamp(3),
        comment="Last updated at (UTC)",
    )
