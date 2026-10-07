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
    # `None` when no LLM call was made (the no-evidence short-circuit),
    # never a fabricated/estimated count — mirrors `TokenUsage`'s own
    # "None means unknown/not applicable" convention (see app.llm.schemas).
    token_usage: dict | None = None


@dataclass(frozen=True)
class DocumentReference:
    """Safe document metadata only — never a filesystem path, checksum, or
    raw content. Mirrors the same fields `get_document_metadata`/the
    Milestone 3 document API already consider client-facing."""

    document_id: uuid.UUID
    filename: str
    document_type: str
    status: str
    page_count: int | None
    character_count: int | None


@dataclass(frozen=True)
class DocumentAgentResult:
    status: str  # "completed" | "failed"
    answer: str
    documents: list[DocumentReference] = field(default_factory=list)
    error: str | None = None


@dataclass(frozen=True)
class CalculationResult:
    expression: str
    success: bool
    result: float | int | None
    error: str | None = None


@dataclass(frozen=True)
class AnalystAgentResult:
    status: str  # "completed" | "failed"
    answer: str
    calculations: list[CalculationResult] = field(default_factory=list)
    error: str | None = None
    token_usage: dict | None = None
