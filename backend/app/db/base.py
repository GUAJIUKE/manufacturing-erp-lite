"""SQLAlchemy declarative base.

All ORM models inherit from ``Base``. The ``__init__.py`` of the models
package imports every model so that ``Base.metadata`` is fully populated
before Alembic / create_all runs.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Naming convention: every constraint/index gets a deterministic name.
# Alembic autogenerate depends on this to diff cleanly.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        cols = ", ".join(
            f"{c.name}={getattr(self, c.name)!r}"
            for c in self.__table__.columns
            if c.name in {"id", "no", "username", "status"}
        )
        return f"<{self.__class__.__name__}({cols})>"
