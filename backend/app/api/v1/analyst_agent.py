"""Analyst Agent A2A endpoints.

Mirrors `app.api.v1.research_agent`'s shape exactly: `AnalystAgentService`
(reusing `CALCULATOR_TOOL` and `LLMGateway`) does the actual work; this
module only builds the Agent Card and the Task response around its
result. Served only at this versioned path, not the well-known one (see
`app.api.v1.document_agent`'s module docstring for why).
"""

from __future__ import annotations

import dataclasses
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.a2a.agent_card import agent_card_to_json_dict, build_analyst_agent_card, card_base_url
from app.a2a.analyst_agent import AnalystAgentService
from app.a2a.schemas import AnalystAgentResult
from app.a2a.tasks import build_generic_task, task_to_dict
from app.api.schemas.common import EvidenceText, ExpressionText, OptionalUserMessage
from app.config import get_settings
from app.core.exceptions import AppError
from app.core.limits import MAX_EVIDENCE_ITEMS, MAX_EXPRESSIONS
from app.core.rate_limit import LLM_RATE_LIMIT
from app.llm.exceptions import LLMError
from app.llm.gateway import LLMGateway, get_llm_gateway
from app.safety.output_guard import build_output_guard, log_findings

logger = structlog.get_logger(__name__)

# Public Agent Card metadata (see app.api.v1.research_agent); tasks are authenticated.
card_router = APIRouter(prefix="/agents/analyst", tags=["a2a"])
router = APIRouter(prefix="/agents/analyst", tags=["a2a"])

ANALYST_RESULT_ARTIFACT_NAME = "analyst_result"


class AnalystTaskRequest(BaseModel):
    question: OptionalUserMessage = Field(
        default="", description="The question to analyze/synthesize."
    )
    expressions: list[ExpressionText] = Field(
        default_factory=list,
        max_length=MAX_EXPRESSIONS,
        description="Arithmetic expressions to evaluate.",
    )
    evidence: list[EvidenceText] = Field(
        default_factory=list,
        max_length=MAX_EVIDENCE_ITEMS,
        description="Structured evidence supplied by other agents.",
    )


def get_analyst_agent_service(
    gateway: Annotated[LLMGateway, Depends(get_llm_gateway)],
) -> AnalystAgentService:
    return AnalystAgentService(gateway=gateway)


AnalystAgentServiceDep = Annotated[AnalystAgentService, Depends(get_analyst_agent_service)]


@card_router.get("/card")
async def get_analyst_agent_card() -> JSONResponse:
    settings = get_settings()
    card = build_analyst_agent_card(settings, base_url=card_base_url(settings))
    return JSONResponse(content=agent_card_to_json_dict(card))


@router.post("/tasks", dependencies=[LLM_RATE_LIMIT])
async def submit_analyst_task(
    request: AnalystTaskRequest, agent_service: AnalystAgentServiceDep
) -> JSONResponse:
    # Each item is already bounded; the total is too (AIGSEC-009), before any model call. The
    # multi-agent orchestrator trims its evidence to the same total, so it never trips this.
    total = sum(len(item) for item in request.evidence)
    if total > get_settings().analyst_max_evidence_total_chars:
        raise AppError(
            "The evidence is too large for one analyst task",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="evidence_too_large",
        )
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

    # The answer leaves this server: the output guard applies (AIGSEC-015).
    guarded = build_output_guard(get_settings()).redact(result.answer)
    log_findings("a2a_output_redacted", guarded.findings)
    result = dataclasses.replace(result, answer=guarded.text)
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
