"""Request/response schemas for the agent endpoint.

Never exposes internal graph state (the LangGraph `AgentState`, message
history, or tool-call arguments/raw results) — only the final answer,
run/execution metadata, and knowledge-base sources, mirroring the same
"never expose internals" discipline `app.api.schemas.rag` applies.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.agents.schemas import AgentRunResult, AgentSource, ToolUsageSummary
from app.llm.schemas import ModelRole


class AgentRunRequest(BaseModel):
    message: str = Field(min_length=1, description="The user's request.")
    conversation_id: uuid.UUID | None = Field(
        default=None, description="Existing conversation to continue. Omit to start a new one."
    )
    model_role: ModelRole = ModelRole.PRIMARY


class ToolUsageSummaryResponse(BaseModel):
    name: str
    call_count: int
    success_count: int
    failure_count: int

    @classmethod
    def from_summary(cls, summary: ToolUsageSummary) -> ToolUsageSummaryResponse:
        return cls(
            name=summary.name,
            call_count=summary.call_count,
            success_count=summary.success_count,
            failure_count=summary.failure_count,
        )


class AgentSourceResponse(BaseModel):
    document_id: uuid.UUID
    filename: str
    page: int | None = None
    similarity: float

    @classmethod
    def from_source(cls, source: AgentSource) -> AgentSourceResponse:
        return cls(
            document_id=source.document_id,
            filename=source.filename,
            page=source.page_number,
            similarity=source.similarity,
        )


class AgentRunResponse(BaseModel):
    run_id: uuid.UUID
    conversation_id: uuid.UUID
    answer: str
    status: str
    steps: int
    tool_usage: list[ToolUsageSummaryResponse]
    sources: list[AgentSourceResponse]
    duration_ms: float

    @classmethod
    def from_result(cls, result: AgentRunResult) -> AgentRunResponse:
        return cls(
            run_id=result.run_id,
            conversation_id=result.conversation_id,
            answer=result.answer,
            status=result.status,
            steps=result.steps,
            tool_usage=[ToolUsageSummaryResponse.from_summary(t) for t in result.tool_calls],
            sources=[AgentSourceResponse.from_source(s) for s in result.sources],
            duration_ms=result.duration_ms,
        )
