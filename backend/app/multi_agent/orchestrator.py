"""`MultiAgentOrchestrator`: routes a user request to the specialists it
needs, runs independent agents in parallel, runs the Analyst sequentially
after them when synthesis is needed, and aggregates the result — the one
place that ties `router.py`/`capabilities.py`/`policies.py`/`adapters.py`/
`aggregation.py` together. See
docs/architecture/decisions/010-multi-agent-architecture.md for the full
design.

Contains no domain-specific research/document/calculation logic itself —
that all lives in each agent's own A2A-exposed service, reached only
through `A2AClient` (see `adapters.py`). Never imports
`ResearchAgentService`/`DocumentAgentService`/`AnalystAgentService`
directly.
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
import uuid
from collections.abc import Awaitable, Callable

import structlog

from app.a2a.client import A2AClient
from app.config import Settings
from app.llm.gateway import LLMGateway
from app.llm.schemas import ChatMessage, ChatRole, ModelRole
from app.multi_agent.adapters import (
    call_analyst_agent,
    call_document_agent,
    call_research_agent,
    new_task_id,
)
from app.multi_agent.aggregation import ResultAggregator
from app.multi_agent.capabilities import AGENT_ANALYST, agent_for_capability
from app.multi_agent.exceptions import (
    DelegationLimitExceededError,
    MultiAgentError,
    UnauthorizedCapabilityError,
    WorkflowDepthExceededError,
)
from app.multi_agent.models import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_TIMEOUT,
    AgentContext,
    AgentResult,
    WorkflowResult,
)
from app.multi_agent.policies import ORCHESTRATOR, is_transition_allowed
from app.multi_agent.router import RoutingDecision, route

logger = structlog.get_logger(__name__)

_ADAPTER_BY_AGENT: dict[str, Callable[..., Awaitable[AgentResult]]] = {
    "research": call_research_agent,
    "document": call_document_agent,
    AGENT_ANALYST: call_analyst_agent,
}


class MultiAgentOrchestrator:
    def __init__(self, *, settings: Settings, gateway: LLMGateway, a2a_client: A2AClient) -> None:
        self._settings = settings
        self._gateway = gateway
        self._client = a2a_client
        self._aggregator = ResultAggregator()

    async def run(self, *, question: str) -> WorkflowResult:
        workflow_id = str(uuid.uuid4())
        correlation_id = str(uuid.uuid4())
        start = time.perf_counter()
        logger.info(
            "multi_agent.workflow_started", workflow_id=workflow_id, correlation_id=correlation_id
        )

        decision = route(question)
        logger.info(
            "multi_agent.routing_decision",
            workflow_id=workflow_id,
            correlation_id=correlation_id,
            capabilities=list(decision.capabilities),
        )

        if not decision.capabilities:
            answer = await self._direct_answer(question)
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.info(
                "multi_agent.workflow_completed",
                workflow_id=workflow_id,
                status=STATUS_COMPLETED,
                agents_used=[],
                duration_ms=duration_ms,
            )
            return WorkflowResult(
                workflow_id=workflow_id,
                correlation_id=correlation_id,
                status=STATUS_COMPLETED,
                answer=answer,
                duration_ms=duration_ms,
            )

        try:
            agent_results = await asyncio.wait_for(
                self._execute(
                    decision,
                    workflow_id=workflow_id,
                    correlation_id=correlation_id,
                    question=question,
                ),
                timeout=self._settings.multi_agent_timeout_seconds,
            )
        except TimeoutError:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.warning(
                "multi_agent.workflow_failed",
                workflow_id=workflow_id,
                correlation_id=correlation_id,
                reason="timeout",
                duration_ms=duration_ms,
            )
            return WorkflowResult(
                workflow_id=workflow_id,
                correlation_id=correlation_id,
                status=STATUS_TIMEOUT,
                answer="This request took too long to process across all agents involved.",
                duration_ms=duration_ms,
            )
        except MultiAgentError as exc:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.warning(
                "multi_agent.workflow_failed",
                workflow_id=workflow_id,
                correlation_id=correlation_id,
                reason=type(exc).__name__,
                duration_ms=duration_ms,
            )
            return WorkflowResult(
                workflow_id=workflow_id,
                correlation_id=correlation_id,
                status=STATUS_FAILED,
                answer=f"This request could not be processed: {exc}",
                duration_ms=duration_ms,
            )

        answer, status = self._aggregator.combine(agent_results=agent_results)
        token_usage = _aggregate_token_usage(agent_results)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info(
            "multi_agent.workflow_completed",
            workflow_id=workflow_id,
            correlation_id=correlation_id,
            status=status,
            agents_used=[r.agent_name for r in agent_results],
            duration_ms=duration_ms,
        )
        return WorkflowResult(
            workflow_id=workflow_id,
            correlation_id=correlation_id,
            status=status,
            answer=answer,
            agent_results=agent_results,
            token_usage=token_usage,
            duration_ms=duration_ms,
        )

    async def _direct_answer(self, question: str) -> str:
        completion = await self._gateway.chat_completion(
            model_role=ModelRole.FAST,
            messages=[
                ChatMessage(
                    role=ChatRole.SYSTEM,
                    content=(
                        "You are AegisAI's orchestrator. Answer briefly and directly — "
                        "this request did not need a specialized agent."
                    ),
                ),
                ChatMessage(role=ChatRole.USER, content=question),
            ],
        )
        return completion.content

    async def _execute(
        self,
        decision: RoutingDecision,
        *,
        workflow_id: str,
        correlation_id: str,
        question: str,
    ) -> list[AgentResult]:
        agent_keys: list[str] = []
        for capability in decision.capabilities:
            agent_key = agent_for_capability(capability)
            if agent_key is None:
                raise UnauthorizedCapabilityError(
                    f"No agent registered for capability {capability!r}"
                )
            if not is_transition_allowed(source=ORCHESTRATOR, target=agent_key):
                raise UnauthorizedCapabilityError(
                    f"{ORCHESTRATOR} -> {agent_key} is not an allowed workflow transition"
                )
            if agent_key not in agent_keys:
                agent_keys.append(agent_key)

        if len(agent_keys) > self._settings.max_agent_delegations:
            raise DelegationLimitExceededError(
                f"Workflow would make {len(agent_keys)} agent calls, "
                f"exceeding max_agent_delegations={self._settings.max_agent_delegations}"
            )

        analyst_needed = AGENT_ANALYST in agent_keys
        tier1_keys = [key for key in agent_keys if key != AGENT_ANALYST]
        if analyst_needed and self._settings.max_agent_depth < 2:
            raise WorkflowDepthExceededError(
                f"Analyst synthesis would reach depth 2, exceeding "
                f"max_agent_depth={self._settings.max_agent_depth}"
            )

        tier1_results = await self._run_tier1(
            tier1_keys,
            decision,
            workflow_id=workflow_id,
            correlation_id=correlation_id,
            question=question,
        )

        if not analyst_needed:
            return tier1_results

        evidence = [r.answer for r in tier1_results if r.status == STATUS_COMPLETED and r.answer]
        analyst_context = AgentContext(
            task_id=new_task_id(),
            correlation_id=correlation_id,
            workflow_id=workflow_id,
            user_question=question,
            expressions=list(decision.expressions),
            evidence=evidence,
            depth=2,
        )
        analyst_result = await self._call_with_retry(AGENT_ANALYST, analyst_context)
        return [*tier1_results, analyst_result]

    async def _run_tier1(
        self,
        tier1_keys: list[str],
        decision: RoutingDecision,
        *,
        workflow_id: str,
        correlation_id: str,
        question: str,
    ) -> list[AgentResult]:
        if not tier1_keys:
            return []

        contexts = {
            key: AgentContext(
                task_id=new_task_id(),
                correlation_id=correlation_id,
                workflow_id=workflow_id,
                user_question=question,
                document_ids=list(decision.document_ids),
                expressions=list(decision.expressions) if key == AGENT_ANALYST else [],
                depth=1,
            )
            for key in tier1_keys
        }

        parallel = len(tier1_keys) > 1
        if parallel:
            logger.info(
                "multi_agent.parallel_started",
                workflow_id=workflow_id,
                correlation_id=correlation_id,
                agents=tier1_keys,
            )
        results = await asyncio.gather(
            *(self._call_with_retry(key, contexts[key]) for key in tier1_keys)
        )
        if parallel:
            logger.info(
                "multi_agent.parallel_completed",
                workflow_id=workflow_id,
                correlation_id=correlation_id,
            )
        return list(results)

    async def _call_with_retry(self, agent_key: str, context: AgentContext) -> AgentResult:
        adapter = _ADAPTER_BY_AGENT[agent_key]
        logger.info(
            "multi_agent.agent_started", agent=agent_key, correlation_id=context.correlation_id
        )
        result = await adapter(client=self._client, settings=self._settings, context=context)
        retries_used = 0
        while (
            result.status in (STATUS_FAILED, STATUS_TIMEOUT)
            and result.metadata.get("retryable")
            and retries_used < self._settings.multi_agent_max_retries
        ):
            retries_used += 1
            logger.info(
                "multi_agent.agent_retry",
                agent=agent_key,
                correlation_id=context.correlation_id,
                attempt=retries_used,
            )
            result = await adapter(client=self._client, settings=self._settings, context=context)

        if result.status == STATUS_COMPLETED:
            logger.info(
                "multi_agent.agent_completed",
                agent=agent_key,
                correlation_id=context.correlation_id,
                duration_ms=result.duration_ms,
            )
        return dataclasses.replace(result, retry_count=retries_used) if retries_used else result


def _aggregate_token_usage(agent_results: list[AgentResult]) -> dict:
    total_input = 0
    total_output = 0
    total: int = 0
    any_known = False
    for result in agent_results:
        usage = result.metadata.get("token_usage")
        if not usage:
            continue
        any_known = True
        total_input += usage.get("input_tokens") or 0
        total_output += usage.get("output_tokens") or 0
        total += usage.get("total_tokens") or 0
    if not any_known:
        return {}
    return {"input_tokens": total_input, "output_tokens": total_output, "total_tokens": total}
