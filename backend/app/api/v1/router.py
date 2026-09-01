"""API v1 router aggregation.

Phase 3 (scaffold): health check only. Business routers are mounted here as
they are implemented (Phase 4: auth, Phase 5: master data, ...).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.v1 import (
    auth,
    departments,
    inventory_policies,
    materials,
    purchase_requisitions,
    roles,
    suppliers,
    users,
    warehouses,
)
from app.core.response import ApiResponse
from app.db.session import get_db

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(roles.router)
api_router.include_router(roles.permission_router)
api_router.include_router(departments.router)
api_router.include_router(materials.router)
api_router.include_router(suppliers.router)
api_router.include_router(warehouses.router)
api_router.include_router(inventory_policies.router)
api_router.include_router(purchase_requisitions.router)


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
