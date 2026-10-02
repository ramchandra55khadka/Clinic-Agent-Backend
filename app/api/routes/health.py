"""Liveness and readiness probes.

`/health` and `/health/live` never touch the database (a liveness probe must not
fail because of a dependency); `/health/ready` verifies the database so a load
balancer stops routing to an instance that cannot serve traffic.
"""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def health():
    return {"status": "healthy"}


@router.get("/live")
def liveness():
    return {"status": "alive"}


@router.get("/ready")
def readiness():
    database = "ok"
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - exercised by infrastructure
        database = f"unavailable: {type(exc).__name__}"
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unavailable", "database": database, "environment": settings.environment},
        )

    return {
        "status": "ready",
        "database": database,
        "environment": settings.environment,
        "docs_enabled": settings.enable_docs,
    }
