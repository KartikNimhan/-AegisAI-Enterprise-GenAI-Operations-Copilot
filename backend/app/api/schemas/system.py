"""Response schema for the system status endpoint (Milestone 9).

Distinguishes two genuinely different kinds of signal, labeled
differently so the UI never presents one as the other:
- a **live connectivity check** (`database`/`redis`, reusing the exact
  same checks `/health/ready` already performs — never a second,
  divergent implementation of "is Postgres reachable");
- a **configuration fact** (`llm_configured`, `trusted_a2a_agents`,
  `mcp_server`) — true/present regardless of whether the provider/agent
  actually responds right now. Milestone 9's brief is explicit: "do not
  claim healthy merely because the frontend loaded," and a live Groq/MCP/
  A2A probe on every status check would mean an API call (cost, latency)
  just to render a status page — out of proportion for this milestone.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class SystemStatusResponse(BaseModel):
    database: Literal["ok", "unavailable"]
    redis: Literal["ok", "unavailable"]
    llm_configured: bool
    trusted_a2a_agents: list[str]
    mcp_server: str
