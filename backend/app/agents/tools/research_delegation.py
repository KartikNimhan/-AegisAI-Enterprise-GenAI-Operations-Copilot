"""The `delegate_to_research_agent` tool — the agent's A2A capability.

Wraps `app.a2a.client.A2AClient` directly; it does not re-implement
retrieval, generation, or the A2A wire protocol. The agent calls this tool
exactly like any other — the A2A boundary (fetching the Agent Card,
submitting a task, parsing the result) is entirely inside the client, not
duplicated here or in the graph.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.a2a.client import A2AClient
from app.a2a.exceptions import (
    A2AConnectionError,
    A2AInvalidCardError,
    A2ATaskFailedError,
    A2ATimeoutError,
    A2AUntrustedAgentError,
)
from app.agents.tools.base import ToolDefinition, ToolResult
from app.config import Settings

RESEARCH_AGENT_TOOL_NAME = "delegate_to_research_agent"

_ERROR_CODE_BY_EXCEPTION: dict[type[Exception], str] = {
    A2AUntrustedAgentError: "permission_denied",
    A2AInvalidCardError: "validation_error",
    A2ATimeoutError: "transient_error",
    A2AConnectionError: "transient_error",
    A2ATaskFailedError: "internal_error",
}


class ResearchDelegationArgs(BaseModel):
    question: str = Field(min_length=1, description="The research question to delegate.")


def _make_executor(*, client: A2AClient, base_url: str) -> Any:
    async def _execute(args: BaseModel) -> ToolResult:
        assert isinstance(args, ResearchDelegationArgs)
        try:
            result = await client.submit_research_task(base_url, question=args.question)
        except tuple(_ERROR_CODE_BY_EXCEPTION) as exc:
            error_code = _ERROR_CODE_BY_EXCEPTION[type(exc)]
            return ToolResult(success=False, error=str(exc), error_code=error_code)
        return ToolResult(
            success=True,
            data={
                "answer": result.answer,
                "sources": [
                    {
                        "chunk_id": str(source.chunk_id),
                        "document_id": str(source.document_id),
                        "filename": source.filename,
                        "page_number": source.page_number,
                        "similarity": source.similarity,
                    }
                    for source in result.sources
                ],
            },
        )

    return _execute


def build_research_delegation_tool(settings: Settings) -> ToolDefinition:
    client = A2AClient(settings=settings)
    base_url = settings.trusted_a2a_agents[0]
    return ToolDefinition(
        name=RESEARCH_AGENT_TOOL_NAME,
        description=(
            "Delegate an open-ended research question to the specialized Research "
            "Agent, which searches the knowledge base and returns a synthesized, "
            "sourced answer. Prefer this for broad research-style questions; use "
            "search_knowledge_base directly for a quick, specific lookup."
        ),
        args_schema=ResearchDelegationArgs,
        executor=_make_executor(client=client, base_url=base_url),
    )
