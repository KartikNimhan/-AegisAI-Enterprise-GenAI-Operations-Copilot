"""Request/response schemas for the multi-agent orchestration endpoint.

Never exposes internal implementation details (A2A task JSON, raw Agent
Cards, routing internals) — only the final answer, workflow metadata, a
per-agent usage summary, and flattened sources, the same "never expose
internals" discipline `app.api.schemas.agents`/`app.api.schemas.rag` apply.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.multi_agent.models import AgentResult, WorkflowResult


class MultiAgentRunRequest(BaseModel):
    message: str = Field(min_length=1, description="The user's request.")


class AgentResultResponse(BaseModel):
    agent_name: str
    capability: str
    status: str
    error: str | None = None
    duration_ms: float
    retry_count: int

    @classmethod
    def from_result(cls, result: AgentResult) -> AgentResultResponse:
        return cls(
            agent_name=result.agent_name,
            capability=result.capability,
            status=result.status,
            error=result.error,
            duration_ms=result.duration_ms,
            retry_count=result.retry_count,
        )


class MultiAgentRunResponse(BaseModel):
    workflow_id: str
    correlation_id: str
    status: str
    answer: str
    agents_used: list[AgentResultResponse]
    sources: list[dict]
    token_usage: dict
    duration_ms: float

    @classmethod
    def from_workflow_result(cls, result: WorkflowResult) -> MultiAgentRunResponse:
        sources: list[dict] = []
        for agent_result in result.agent_results:
            for source in agent_result.sources:
                sources.append({"agent_name": agent_result.agent_name, **source})
        return cls(
            workflow_id=result.workflow_id,
            correlation_id=result.correlation_id,
            status=result.status,
            answer=result.answer,
            agents_used=[AgentResultResponse.from_result(r) for r in result.agent_results],
            sources=sources,
            token_usage=result.token_usage,
            duration_ms=result.duration_ms,
        )
