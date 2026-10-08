"""The System Status API module — wraps Milestone 9's
`/api/v1/system/status`. `database`/`redis` are live connectivity
checks; `llm_configured`/`trusted_a2a_agents`/`mcp_server` are
configuration facts, not live probes — see `app.api.schemas.system`'s
own docstring for why, and render them distinctly in the UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .client import request_json


@dataclass(frozen=True)
class SystemStatus:
    database: str
    redis: str
    llm_configured: bool
    trusted_a2a_agents: list[str] = field(default_factory=list)
    mcp_server: str = ""


def get_system_status() -> SystemStatus:
    payload = request_json("GET", "/api/v1/system/status")
    return SystemStatus(
        database=payload["database"],
        redis=payload["redis"],
        llm_configured=payload["llm_configured"],
        trusted_a2a_agents=payload.get("trusted_a2a_agents", []),
        mcp_server=payload.get("mcp_server", ""),
    )
