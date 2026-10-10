"""System status endpoint (Milestone 9).

Reuses the exact same connectivity checks `/health/ready` already makes
(`app.db.session.check_database`/`app.db.redis.check_redis`) — not a
second implementation — plus configuration facts already in `Settings`.
Never performs a live Groq/MCP/A2A call just to render a status page (see
the schema's own docstring for why).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.schemas.system import SystemStatusResponse
from app.db.redis import check_redis
from app.db.session import check_database
from app.dependencies import SettingsDep
from app.mcp.server import MCP_SERVER_NAME

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/status", response_model=SystemStatusResponse)
async def get_system_status(settings: SettingsDep) -> SystemStatusResponse:
    database_ok = await check_database()
    redis_ok = await check_redis()
    return SystemStatusResponse(
        database="ok" if database_ok else "unavailable",
        redis="ok" if redis_ok else "unavailable",
        llm_configured=settings.has_groq_api_key,
        trusted_a2a_agents=settings.trusted_a2a_agents,
        mcp_server=MCP_SERVER_NAME,
    )
