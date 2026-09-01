"""API v1 router aggregation.

Phase 3 (scaffold): health check only. Business routers are mounted here as
they are implemented (Phase 4: auth, Phase 5: master data, ...).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.response import ApiResponse
from app.db.session import get_db

api_router = APIRouter()


@api_router.get("/health", tags=["system"], summary="服务健康检查")
def health(db: Session = Depends(get_db)) -> ApiResponse[dict]:
    """Checks API liveness and database connectivity in one round trip."""
    db_status = "up"
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # pragma: no cover - defensive
        db_status = "down"
    return ApiResponse.ok(
        {
            "service": "manufacturing-erp-lite",
            "database": db_status,
            "time": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        }
    )
