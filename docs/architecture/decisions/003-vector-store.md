# 3. PostgreSQL + pgvector as the Initial Vector Storage Approach

## Status

Accepted — 2026-10-03

## Context

The roadmap includes RAG, embeddings, and vector search. AegisAI already
needs a relational database for conversations, documents, and future
domain entities. A separate decision is needed on where vectors for
similarity search will live: a dedicated vector database (e.g., a managed
vector-search service) versus extending the primary relational store.

No embeddings, vector columns, or similarity-search queries are
implemented in this milestone — this decision only fixes the storage
approach so the database image and migration tooling are chosen correctly
from the start.

## Decision

Use PostgreSQL with the `pgvector` extension as the initial vector storage
approach, rather than introducing a separate dedicated vector database.
Concretely:

- `docker-compose.yml` and deployment use the `pgvector/pgvector` Postgres
  image instead of the stock `postgres` image.
- An Alembic migration (`0001_enable_pgvector`) enables the `vector`
  extension so it is available once the RAG milestone adds tables with
  `vector` columns.
- No ORM models, embeddings, or indexes are added yet — this groundwork
  only removes infrastructure friction for that later milestone.

## Consequences

- **Positive**: one database to operate, back up, and reason about
  transactionally — vectors, metadata, and relational data can be joined
  in a single query once implemented.
- **Positive**: avoids standing up and operating a second stateful service
  before there is a concrete workload that needs it.
- **Negative**: pgvector's indexing (IVFFlat/HNSW) and query performance at
  very large scale is different from purpose-built vector databases. If
  corpus size or query latency requirements later exceed what pgvector
  handles well, this decision should be revisited — the `rag/` module
  boundary (see [001-modular-monolith.md](001-modular-monolith.md)) is
  intended to make that swap possible without touching unrelated code.

## Related

- [001-modular-monolith.md](001-modular-monolith.md)
