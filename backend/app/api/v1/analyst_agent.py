"""Analyst Agent A2A endpoints.

Mirrors `app.api.v1.research_agent`'s shape exactly: `AnalystAgentService`
(reusing `CALCULATOR_TOOL` and `LLMGateway`) does the actual work; this
module only builds the Agent Card and the Task response around its
result. Served only at this versioned path, not the well-known one (see
`app.api.v1.document_agent`'s module docstring for why).
"""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.a2a.agent_card import agent_card_to_json_dict, build_analyst_agent_card
from app.a2a.analyst_agent import AnalystAgentService
from app.a2a.schemas import AnalystAgentResult
from app.a2a.tasks import build_generic_task, task_to_dict
from app.config import get_settings
from app.llm.exceptions import LLMError
from app.llm.gateway import LLMGateway, get_llm_gateway

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/agents/analyst", tags=["a2a"])

ANALYST_RESULT_ARTIFACT_NAME = "analyst_result"


class AnalystTaskRequest(BaseModel):
    question: str = Field(default="", description="The question to analyze/synthesize.")
    expressions: list[str] = Field(
        default_factory=list, description="Arithmetic expressions to evaluate."
    )
    evidence: list[str] = Field(
        default_factory=list, description="Structured evidence supplied by other agents."
    )


def get_analyst_agent_service(
    gateway: Annotated[LLMGateway, Depends(get_llm_gateway)],
) -> AnalystAgentService:
    return AnalystAgentService(gateway=gateway)


AnalystAgentServiceDep = Annotated[AnalystAgentService, Depends(get_analyst_agent_service)]


@router.get("/card")
async def get_analyst_agent_card(request: Request) -> JSONResponse:
    settings = get_settings()
    card = build_analyst_agent_card(settings, base_url=str(request.base_url).rstrip("/"))
    return JSONResponse(content=agent_card_to_json_dict(card))


@router.post("/tasks")
async def submit_analyst_task(
    request: AnalystTaskRequest, agent_service: AnalystAgentServiceDep
) -> JSONResponse:
    logger.info(
        "a2a.task_started",
        expression_count=len(request.expressions),
        evidence_count=len(request.evidence),
    )
    try:
        result = await agent_service.analyze(
            question=request.question,
            expressions=request.expressions,
            evidence=request.evidence,
        )
    except LLMError as exc:
        logger.warning("a2a.task_failed", error_type=type(exc).__name__)
        result = AnalystAgentResult(
            status="failed", answer="", error="The analyst agent's language model is unavailable"
        )
    except Exception:
        logger.exception("a2a.task_failed", error_type="internal")
        result = AnalystAgentResult(
            status="failed", answer="", error="The analyst agent failed to complete the task"
        )
    else:
        logger.info("a2a.task_completed", status=result.status)

    payload = {
        "answer": result.answer,
        "calculations": [
            {
                "expression": c.expression,
                "success": c.success,
                "result": c.result,
                "error": c.error,
            }
            for c in result.calculations
        ],
        "token_usage": result.token_usage,
    }
    task = build_generic_task(
        request_text=request.question or "(calculation only)",
        status=result.status,
        artifact_name=ANALYST_RESULT_ARTIFACT_NAME,
        payload=payload,
        error=result.error,
    )
    return JSONResponse(content=task_to_dict(task))
