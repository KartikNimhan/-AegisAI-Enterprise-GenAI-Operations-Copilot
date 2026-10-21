"""Multi-agent orchestration endpoint.

Kept thin: all orchestration (routing, A2A delegation, aggregation) lives
in `app.multi_agent.orchestrator.MultiAgentOrchestrator`. This module must
never import `app.a2a.research_agent`/`document_agent`/`analyst_agent`
directly, and never build an `A2AClient` call itself.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.a2a.client import A2AClient
from app.api.schemas.multi_agent import MultiAgentRunRequest, MultiAgentRunResponse
from app.core.rate_limit import LLM_RATE_LIMIT
from app.core.security import BearerTokenDep
from app.dependencies import SettingsDep
from app.llm.gateway import LLMGateway, get_llm_gateway
from app.multi_agent.orchestrator import MultiAgentOrchestrator

router = APIRouter(prefix="/multi-agent", tags=["multi-agent"])


def get_multi_agent_orchestrator(
    settings: SettingsDep,
    gateway: Annotated[LLMGateway, Depends(get_llm_gateway)],
    bearer_token: BearerTokenDep,
) -> MultiAgentOrchestrator:
    # `settings` (resolved through FastAPI's own DI, not a direct
    # `get_settings()` call) is passed to `A2AClient` too — a direct call
    # here would silently bypass a test's `app.dependency_overrides
    # [get_settings]`, since that override only affects dependency
    # resolution, not a plain function call inside the route body.
    #
    # The caller's bearer token is handed to the client so the specialist
    # agents' (authenticated) task endpoints see the same user; the client only
    # sends it to a task URL it has validated against the trusted origin.
    return MultiAgentOrchestrator(
        settings=settings,
        gateway=gateway,
        a2a_client=A2AClient(settings=settings, auth_token=bearer_token),
    )


OrchestratorDep = Annotated[MultiAgentOrchestrator, Depends(get_multi_agent_orchestrator)]


@router.post("/run", response_model=MultiAgentRunResponse, dependencies=[LLM_RATE_LIMIT])
async def run_multi_agent_workflow(
    request: MultiAgentRunRequest, orchestrator: OrchestratorDep
) -> MultiAgentRunResponse:
    result = await orchestrator.run(question=request.message)
    return MultiAgentRunResponse.from_workflow_result(result)
