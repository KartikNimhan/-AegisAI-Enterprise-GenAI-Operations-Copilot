"""Liveness and readiness endpoints.

Kept deliberately thin: all connectivity checks live in the db layer
(`app.db.session.check_database`, `app.db.redis.check_redis`).
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.schemas.common import HealthStatus
from app.db.redis import check_redis
from app.db.session import check_database

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthStatus)
async def health() -> HealthStatus:
    """Liveness probe: process is up and serving requests."""
    return HealthStatus(status="ok")


@router.get("/health/ready")
async def readiness() -> JSONResponse:
    """Readiness probe: process can reach its required dependencies."""
    database_ok = await check_database()
    redis_ok = await check_redis()
    ready = database_ok and redis_ok

    payload = {
        "status": "ready" if ready else "degraded",
        "database": "ok" if database_ok else "unavailable",
        "redis": "ok" if redis_ok else "unavailable",
    }
    return JSONResponse(status_code=200 if ready else 503, content=payload)
