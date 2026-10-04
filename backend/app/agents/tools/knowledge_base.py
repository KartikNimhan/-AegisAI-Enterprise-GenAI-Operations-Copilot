"""The `search_knowledge_base` tool — agentic RAG.

Wraps `app.rag.retrieval.service.RetrievalService` directly; it does not
re-implement vector search, re-embed anything itself, or touch pgvector.
This is the same retrieval infrastructure `RAGService` (Milestone 5) uses —
the agent is a second caller of `RetrievalService`, not a parallel
retrieval path. Prompt construction and citation-ID assignment
(`[S1]`-style, `ContextAssembler`) are deliberately NOT reused here: a tool
result is data the agent reasons over, not a rendered RAG prompt — see
ADR 008, "Agentic RAG".
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.agents.tools.base import ToolDefinition, ToolResult
from app.rag.retrieval.service import RetrievalService

_DEFAULT_TOP_K = 5
_MAX_TOP_K = 20


class KnowledgeBaseSearchArgs(BaseModel):
    query: str = Field(min_length=1, description="The question or topic to search for.")
    document_id: uuid.UUID | None = Field(
        default=None, description="Restrict the search to a single document, if known."
    )
    top_k: int | None = Field(
        default=None,
        ge=1,
        le=_MAX_TOP_K,
        description="Maximum number of results to return (defaults to a server setting).",
    )


def _make_executor(retrieval: RetrievalService) -> Any:
    async def _execute(args: BaseModel) -> ToolResult:
        assert isinstance(args, KnowledgeBaseSearchArgs)
        outcome = await retrieval.retrieve(
            query=args.query, top_k=args.top_k, document_id=args.document_id
        )
        if not outcome.results:
            return ToolResult(
                success=True,
                data={"results": [], "message": "No relevant knowledge base content found."},
            )
        return ToolResult(
            success=True,
            data={
                "results": [
                    {
                        "chunk_id": str(result.chunk_id),
                        "document_id": str(result.document_id),
                        "filename": result.filename,
                        "page_number": result.page_number,
                        "similarity": round(result.similarity, 4),
                        "content": result.content,
                    }
                    for result in outcome.results
                ]
            },
        )

    return _execute


def build_knowledge_base_tool(retrieval: RetrievalService) -> ToolDefinition:
    return ToolDefinition(
        name="search_knowledge_base",
        description=(
            "Search the organization's ingested documents for content relevant to a "
            "query. Returns ranked excerpts with their source document and page. Use "
            "this for any question that depends on organizational documents/policies "
            "rather than general knowledge."
        ),
        args_schema=KnowledgeBaseSearchArgs,
        executor=_make_executor(retrieval),
    )
