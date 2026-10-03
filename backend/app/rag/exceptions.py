"""Typed exceptions for RAG orchestration.

Deliberately minimal: RAG failure modes mostly already have a typed
exception somewhere in the codebase, and `RAGService` lets those propagate
to the existing registered handlers rather than wrapping them in a new
type (see `app.core.exceptions`):

- Query embedding failures -> `app.embeddings.exceptions.EmbeddingProviderError` /
  `EmbeddingDimensionMismatchError` (already mapped to 502/500).
- LLM generation failures -> the `app.llm.exceptions.LLMError` hierarchy
  (already mapped to 429/503/504/502/400).
- An unknown `conversation_id` or `document_id` filter -> `app.core.exceptions.NotFoundError`
  (already mapped to 404) — the same exception `ChatService` raises for an
  unknown conversation, reused rather than duplicated.

`RAGError` exists only as a base for a genuinely RAG-specific failure that
doesn't fit one of the above, should a future addition to this module need
one (e.g. a future reranker failing).
"""

from __future__ import annotations


class RAGError(Exception):
    """Base class for RAG-specific errors not already covered by an
    existing typed exception elsewhere in the codebase."""
