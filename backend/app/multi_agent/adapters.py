"""Agent-specific A2A adapters: each function calls exactly one
specialized agent through `A2AClient.submit_task` (the generic form, not
`submit_research_task` — see ADR 010, "A2A integration") and normalizes
whatever comes back into the one generic `AgentResult` shape the
orchestrator/aggregator reason about.

Never raises: every `A2AError` subtype (connection, timeout, untrusted,
invalid card, task failure) and a raw `asyncio.TimeoutError` (each
adapter wraps its own A2A call in `asyncio.wait_for(...,
settings.multi_agent_agent_timeout_seconds)` — a per-agent budget
independent of the whole workflow's own deadline) are all caught here and
turned into a structured `AgentResult(status=...)` — the same "a remote
failure never crashes the caller" guarantee `ToolRegistry.execute` and
the MCP client already give. A failed/timed-out result's `metadata
["retryable"]` tells `orchestrator.py`'s retry loop whether this was a
transient transport failure worth retrying, or a permanent one that
never is.
"""

from __future__ import annotations

import asyncio
import time
import uuid

import structlog

from app.a2a.client import A2AClient, parse_research_result
from app.a2a.exceptions import A2AError
from app.config import Settings
from app.multi_agent.capabilities import (
    AGENT_ANALYST,
    AGENT_DOCUMENT,
    AGENT_RESEARCH,
    CAPABILITY_DOCUMENT_ANALYSIS,
    CAPABILITY_REGISTRY,
    CAPABILITY_RESEARCH,
    expected_agent_name,
)
from app.multi_agent.models import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_TIMEOUT,
    AgentContext,
    AgentResult,
)
from app.multi_agent.policies import RETRYABLE_A2A_EXCEPTIONS

logger = structlog.get_logger(__name__)


def _coerce_token_usage(raw: dict | None) -> dict | None:
    """The A2A wire format round-trips numbers through a protobuf `Value`,
    which only has a double — an integer token count comes back as e.g.
    `15.0`. Coerce back to int rather than silently storing a float."""
    if raw is None:
        return None
    return {key: (int(value) if value is not None else None) for key, value in raw.items()}


async def call_research_agent(
    *, client: A2AClient, settings: Settings, context: AgentContext
) -> AgentResult:
    start = time.perf_counter()
    try:
        base_url = settings.trusted_a2a_agents[0]
        spec = CAPABILITY_REGISTRY[AGENT_RESEARCH]
        task = await asyncio.wait_for(
            client.submit_task(
                base_url,
                card_path=spec.card_path,
                expected_agent_name=expected_agent_name(settings, AGENT_RESEARCH),
                expected_skill_id=spec.skill_id_by_capability[CAPABILITY_RESEARCH],
                payload={"question": context.user_question},
            ),
            timeout=settings.multi_agent_agent_timeout_seconds,
        )
        result = parse_research_result(task)
    except A2AError as exc:
        return _failed(
            context, agent_name=AGENT_RESEARCH, capability=CAPABILITY_RESEARCH, exc=exc, start=start
        )
    except TimeoutError:
        return _timeout(
            context, agent_name=AGENT_RESEARCH, capability=CAPABILITY_RESEARCH, start=start
        )

    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    if result.status != "completed":
        return AgentResult(
            agent_name=AGENT_RESEARCH,
            capability=CAPABILITY_RESEARCH,
            task_id=context.task_id,
            status=STATUS_FAILED,
            answer="",
            error=result.error or "The research agent reported task failure",
            duration_ms=duration_ms,
        )
    return AgentResult(
        agent_name=AGENT_RESEARCH,
        capability=CAPABILITY_RESEARCH,
        task_id=context.task_id,
        status=STATUS_COMPLETED,
        answer=result.answer,
        sources=[
            {
                "chunk_id": str(s.chunk_id),
                "document_id": str(s.document_id),
                "filename": s.filename,
                "page_number": s.page_number,
                "similarity": s.similarity,
            }
            for s in result.sources
        ],
        metadata={"token_usage": _coerce_token_usage(result.token_usage)},
        duration_ms=duration_ms,
    )


async def call_document_agent(
    *, client: A2AClient, settings: Settings, context: AgentContext
) -> AgentResult:
    start = time.perf_counter()
    try:
        base_url = settings.trusted_a2a_agents[0]
        spec = CAPABILITY_REGISTRY[AGENT_DOCUMENT]
        task = await asyncio.wait_for(
            client.submit_task(
                base_url,
                card_path=spec.card_path,
                expected_agent_name=expected_agent_name(settings, AGENT_DOCUMENT),
                expected_skill_id=spec.skill_id_by_capability[CAPABILITY_DOCUMENT_ANALYSIS],
                payload={"document_ids": [str(d) for d in context.document_ids]},
            ),
            timeout=settings.multi_agent_agent_timeout_seconds,
        )
    except A2AError as exc:
        return _failed(
            context,
            agent_name=AGENT_DOCUMENT,
            capability=CAPABILITY_DOCUMENT_ANALYSIS,
            exc=exc,
            start=start,
        )
    except TimeoutError:
        return _timeout(
            context, agent_name=AGENT_DOCUMENT, capability=CAPABILITY_DOCUMENT_ANALYSIS, start=start
        )

    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    status = task.get("status", {}).get("state", "")
    if status != "TASK_STATE_COMPLETED":
        return AgentResult(
            agent_name=AGENT_DOCUMENT,
            capability=CAPABILITY_DOCUMENT_ANALYSIS,
            task_id=context.task_id,
            status=STATUS_FAILED,
            answer="",
            error=_status_error_message(task) or "The document agent reported task failure",
            duration_ms=duration_ms,
        )

    data = _first_artifact_data(task)
    documents = (data or {}).get("documents", [])
    return AgentResult(
        agent_name=AGENT_DOCUMENT,
        capability=CAPABILITY_DOCUMENT_ANALYSIS,
        task_id=context.task_id,
        status=STATUS_COMPLETED,
        answer=(data or {}).get("answer", ""),
        sources=[
            {
                "document_id": doc.get("document_id"),
                "filename": doc.get("filename"),
                "document_type": doc.get("document_type"),
                "status": doc.get("status"),
            }
            for doc in documents
        ],
        duration_ms=duration_ms,
    )


async def call_analyst_agent(
    *, client: A2AClient, settings: Settings, context: AgentContext
) -> AgentResult:
    start = time.perf_counter()
    needs_calculation = bool(context.expressions)
    needs_synthesis = bool(context.evidence)
    capability = _dominant_analyst_capability(needs_calculation, needs_synthesis)
    try:
        base_url = settings.trusted_a2a_agents[0]
        spec = CAPABILITY_REGISTRY[AGENT_ANALYST]
        task = await asyncio.wait_for(
            client.submit_task(
                base_url,
                card_path=spec.card_path,
                expected_agent_name=expected_agent_name(settings, AGENT_ANALYST),
                expected_skill_id=spec.skill_id_by_capability[capability],
                payload={
                    "question": context.user_question,
                    "expressions": context.expressions,
                    "evidence": context.evidence,
                },
            ),
            timeout=settings.multi_agent_agent_timeout_seconds,
        )
    except A2AError as exc:
        return _failed(
            context, agent_name=AGENT_ANALYST, capability=capability, exc=exc, start=start
        )
    except TimeoutError:
        return _timeout(context, agent_name=AGENT_ANALYST, capability=capability, start=start)

    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    status = task.get("status", {}).get("state", "")
    if status != "TASK_STATE_COMPLETED":
        return AgentResult(
            agent_name=AGENT_ANALYST,
            capability=capability,
            task_id=context.task_id,
            status=STATUS_FAILED,
            answer="",
            error=_status_error_message(task) or "The analyst agent reported task failure",
            duration_ms=duration_ms,
        )

    data = _first_artifact_data(task) or {}
    return AgentResult(
        agent_name=AGENT_ANALYST,
        capability=capability,
        task_id=context.task_id,
        status=STATUS_COMPLETED,
        answer=data.get("answer", ""),
        sources=data.get("calculations", []),
        metadata={"token_usage": _coerce_token_usage(data.get("token_usage"))},
        duration_ms=duration_ms,
    )


def _dominant_analyst_capability(needs_calculation: bool, needs_synthesis: bool) -> str:
    if needs_synthesis:
        return "synthesis"
    return "calculation" if needs_calculation else "synthesis"


def _first_artifact_data(task: dict) -> dict | None:
    for artifact in task.get("artifacts", []):
        for part in artifact.get("parts", []):
            data = part.get("data")
            if data is not None:
                return data
    return None


def _status_error_message(task: dict) -> str | None:
    message = task.get("status", {}).get("message", {})
    for part in message.get("parts", []):
        if "text" in part:
            return part["text"]
    return None


def _failed(
    context: AgentContext, *, agent_name: str, capability: str, exc: Exception, start: float
) -> AgentResult:
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.warning(
        "multi_agent.agent_failed",
        agent=agent_name,
        capability=capability,
        correlation_id=context.correlation_id,
        error_type=type(exc).__name__,
        duration_ms=duration_ms,
    )
    return AgentResult(
        agent_name=agent_name,
        capability=capability,
        task_id=context.task_id,
        status=STATUS_FAILED,
        answer="",
        error=str(exc),
        metadata={"retryable": isinstance(exc, RETRYABLE_A2A_EXCEPTIONS)},
        duration_ms=duration_ms,
    )


def _timeout(
    context: AgentContext, *, agent_name: str, capability: str, start: float
) -> AgentResult:
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.warning(
        "multi_agent.agent_failed",
        agent=agent_name,
        capability=capability,
        correlation_id=context.correlation_id,
        error_type="timeout",
        duration_ms=duration_ms,
    )
    return AgentResult(
        agent_name=agent_name,
        capability=capability,
        task_id=context.task_id,
        status=STATUS_TIMEOUT,
        answer="",
        error=f"{agent_name} agent timed out",
        metadata={"retryable": True},
        duration_ms=duration_ms,
    )


__all__ = [
    "call_research_agent",
    "call_document_agent",
    "call_analyst_agent",
]

# A stable task-id prefix so logs/tests can recognize a generated task id
# at a glance without parsing a UUID.
TASK_ID_PREFIX = "task-"


def new_task_id() -> str:
    return f"{TASK_ID_PREFIX}{uuid.uuid4()}"
