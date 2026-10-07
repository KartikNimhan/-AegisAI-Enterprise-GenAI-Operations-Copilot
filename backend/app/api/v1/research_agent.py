"""Research Agent A2A endpoints.

Kept thin: `ResearchAgentService` (reusing `RetrievalService`/`LLMGateway`)
does the actual work; this module only builds the Agent Card and the Task
response around its result. Two routers are exported: `well_known_router`
(unversioned — `/.well-known/agent-card.json` is a fixed A2A convention,
not an AegisAI API path, the same reasoning `/health` is unversioned) and
`router` (versioned, under `/api/v1/agents/research`).

This endpoint is intentionally synchronous: it runs the research task to
completion and returns the final `Task` (status `completed` or `failed`)
in one response — no task store, no polling, no background queue. See
docs/architecture/decisions/009-mcp-a2a-architecture.md, "Why M7's A2A
task handling is synchronous".
"""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.a2a.agent_card import agent_card_to_json_dict, build_research_agent_card
from app.a2a.research_agent import ResearchAgentService
from app.a2a.schemas import ResearchResult
from app.a2a.tasks import build_task, task_to_dict
from app.config import get_settings
from app.dependencies import SettingsDep
from app.llm.exceptions import LLMError
from app.llm.gateway import LLMGateway, get_llm_gateway
from app.rag.context.assembler import ContextAssembler
from app.rag.retrieval.service import RetrievalService, get_retrieval_service

logger = structlog.get_logger(__name__)

well_known_router = APIRouter(tags=["a2a"])
router = APIRouter(prefix="/agents/research", tags=["a2a"])


class ResearchTaskRequest(BaseModel):
    question: str = Field(min_length=1, description="The research question.")


def get_research_agent_service(
    settings: SettingsDep,
    gateway: Annotated[LLMGateway, Depends(get_llm_gateway)],
    retrieval: Annotated[RetrievalService, Depends(get_retrieval_service)],
) -> ResearchAgentService:
    return ResearchAgentService(
        retrieval=retrieval,
        context_assembler=ContextAssembler(max_context_chars=settings.rag_max_context_chars),
        gateway=gateway,
    )


ResearchAgentServiceDep = Annotated[ResearchAgentService, Depends(get_research_agent_service)]


@well_known_router.get("/.well-known/agent-card.json")
async def get_well_known_agent_card(request: Request) -> JSONResponse:
    settings = get_settings()
    card = build_research_agent_card(settings, base_url=str(request.base_url).rstrip("/"))
    return JSONResponse(content=agent_card_to_json_dict(card))


@router.get("/card")
async def get_research_agent_card(request: Request) -> JSONResponse:
    """A convenience alias for the well-known path, at a path under this
    project's own versioned API prefix."""
    settings = get_settings()
    card = build_research_agent_card(settings, base_url=str(request.base_url).rstrip("/"))
    return JSONResponse(content=agent_card_to_json_dict(card))


@router.post("/tasks")
async def submit_research_task(
    request: ResearchTaskRequest, agent_service: ResearchAgentServiceDep
) -> JSONResponse:
    logger.info("a2a.task_started", question_length=len(request.question))
    try:
        result = await agent_service.research(question=request.question)
    except LLMError as exc:
        logger.warning("a2a.task_failed", error_type=type(exc).__name__)
        result = ResearchResult(
            status="failed", answer="", error="The research agent's language model is unavailable"
        )
    except Exception:
        logger.exception("a2a.task_failed", error_type="internal")
        result = ResearchResult(
            status="failed", answer="", error="The research agent failed to complete the task"
        )
    else:
        logger.info("a2a.task_completed", status=result.status)

    task = build_task(question=request.question, result=result)
    return JSONResponse(content=task_to_dict(task))
