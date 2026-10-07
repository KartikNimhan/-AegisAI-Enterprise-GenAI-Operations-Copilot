"""Application-level request/result types for the Research Agent.

Deliberately separate from `a2a.types` (the protocol-level `Task`/
`Artifact`/`Part` the wire format actually uses — see `agent_card.py` and
`research_agent.py`): this is the structured *content* the Research Agent
produces, carried inside a `Part.data` field on the wire. Mirrors
`app.rag.schemas.RAGSource`'s shape, not reused directly, since a research
result has no `[S1]`-style inline citation contract the way a RAG answer
does (see ADR 009, "Research Agent").
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ResearchSource:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    page_number: int | None
    similarity: float


@dataclass(frozen=True)
class ResearchResult:
    status: str  # "completed" | "failed"
    answer: str
    sources: list[ResearchSource] = field(default_factory=list)
    error: str | None = None
