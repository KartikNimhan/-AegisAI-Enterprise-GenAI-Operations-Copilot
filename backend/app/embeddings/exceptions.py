"""Typed exceptions for embedding generation.

Mirrors the pattern established in `app.llm.exceptions` and
`app.documents.exceptions`: provider-specific failures (a model failing to
load, inference raising) are translated to these before leaving
`providers/`, so nothing outside this module ever sees a raw
`sentence_transformers`/`torch` exception.
"""

from __future__ import annotations


class EmbeddingError(Exception):
    """Base class for all embedding-related errors."""


class EmptyInputError(EmbeddingError):
    """Raised for an empty text or an empty batch — never silently embeds
    nothing and calls it success."""


class EmbeddingProviderError(EmbeddingError):
    """The provider failed to produce embeddings (model load or inference
    failure). Caught by `EmbeddingService`, which decides whether to retry
    the batch or record it as failed — never propagated as a raw
    provider/library exception."""


class EmbeddingDimensionMismatchError(EmbeddingError):
    """A provider returned a vector whose length doesn't match the
    configured/expected dimension — caught before anything is persisted,
    since pgvector's column width is fixed and a silent mismatch would
    otherwise surface as a confusing database error instead of a clear one
    here.
    """


class DocumentNotReadyError(EmbeddingError):
    """Raised when embedding is requested for a document that isn't in
    `DocumentStatus.PROCESSED` — there are no (trustworthy) chunks to
    embed yet. Maps to HTTP 400 (see `core/exceptions.py`)."""
