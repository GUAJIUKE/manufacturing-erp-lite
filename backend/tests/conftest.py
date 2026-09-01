"""Pytest fixtures.

Q14: tests MUST use a dedicated test database (erp_lite_test). The ENV
variable is set BEFORE any app import so that ``app.core.config.settings``
resolves to the test database (settings.database_name appends _test when
ENV=test). Tables are created by the Alembic migration (``-x db=test``).
"""

from __future__ import annotations

import os

# 必须在任何 app 导入之前设置 —— settings 是 lru_cache 单例
os.environ["ENV"] = "test"
os.environ["DB_NAME"] = "erp_lite"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="function")
def db():
    """Fresh session per test; rolled back so tests never leak data."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
