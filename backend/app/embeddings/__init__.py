"""Text embedding: a provider-neutral abstraction over turning text into
vectors, plus application-level orchestration (batching, idempotency,
persistence) in `service.py`.

`EmbeddingService` -> `EmbeddingProvider` (interface, `base.py`) ->
`providers/local.py` (`LocalEmbeddingProvider`, Sentence Transformers).
Nothing outside `providers/local.py` imports `sentence_transformers`.

This module does not implement RAG retrieval, reranking, or query
rewriting — see docs/architecture/decisions/006-embedding-model.md for
what this milestone does and doesn't do.
"""
