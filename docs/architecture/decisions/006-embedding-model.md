# 6. Embeddings: Model Choice, Storage, Versioning, and Similarity Search

## Status

Accepted — 2026-10-03

(Numbered 006, not 005 as originally suggested when this milestone was
scoped — 005 was already used by
[005-document-ingestion.md](005-document-ingestion.md) from Milestone 3.)

## Context

Milestone 4 turns the `DocumentChunk` rows Milestone 3 produces into
semantic vectors stored in PostgreSQL via pgvector, and proves a basic
similarity-search query works correctly end to end. It explicitly does
**not** implement RAG retrieval, hybrid search, reranking, LangGraph,
agents, MCP, A2A, autonomous workflows, or LLM-based query rewriting —
all deferred to later milestones. The goal is a correct, idempotent,
model-versioned embedding pipeline that a future RAG milestone can build
on without rework, the same relationship Milestone 3 has to this one.

## Decision

### Model choice: sentence-transformers/all-MiniLM-L6-v2

Verified directly against the model's Hugging Face model card and the
`sentence-transformers` v6.1.0 package documentation (not assumed from
training-data memory, per this milestone's explicit instruction):

- **384-dimensional** output, confirmed both in the model card and
  empirically (`len(model.encode("text"))`).
- **Apache 2.0** licensed, ~22.7M parameters, maps sentences/paragraphs to
  a dense vector space — designed for semantic similarity/search, which is
  exactly this milestone's use case.
- Ships a built-in `Normalize` module (visible in the model's
  `modules.json`), so `.encode()` output is unit-length (L2 norm = 1.0) by
  default. Confirmed empirically. `normalize_embeddings=True` is still
  passed explicitly to `.encode()` as defensive practice — correct
  regardless of whether a future model swap keeps that built-in behavior.
- Runs on CPU in well under a second for a handful of short chunks (no GPU
  required), which matches this milestone's local-inference, no-task-queue
  scope.

Chosen over a hosted embeddings API (e.g. OpenAI, Cohere) because it
requires no API key, no network call per embedding, and no additional
per-token cost — consistent with document ingestion (Milestone 3) already
being fully local/offline. A hosted provider remains a future
`EmbeddingProvider` implementation if warranted; nothing here precludes it.

### Architecture: provider-neutral, mirroring the LLM gateway and storage patterns

```
EmbeddingService (orchestration: batching, idempotency, persistence)
  -> EmbeddingProvider (interface, app/embeddings/base.py)
    -> LocalEmbeddingProvider (app/embeddings/providers/local.py)
      -> sentence_transformers.SentenceTransformer
```

`app.embeddings.providers.local` is the only module allowed to import
`sentence_transformers`, the same rule Milestone 1 applies to `groq` and
Milestone 3 applies to `pypdf`/`python-docx`. The model is constructed
lazily on first use via a double-checked-locking `lru_cache`-decorated
factory (`get_local_embedding_provider`) — mirroring `get_llm_gateway` and
`get_document_storage` — so importing this module, or even constructing
`EmbeddingService`, never triggers a ~90MB model download/load; only the
first real `embed_texts` call does.

`embed_texts`/`embed_text` are `async def`, but Sentence Transformers
inference is CPU-bound, synchronous code underneath — both model loading
and `.encode()` are offloaded via `asyncio.to_thread`, the same pattern
Milestone 3 uses for `pypdf`/`python-docx` extraction and chunking. The
interface does not pretend this work is natively async; it just ensures
it never blocks the event loop.

### Schema: one row per (chunk, model, version) — not one row per chunk

```sql
chunk_embeddings (
  id                        uuid primary key,
  document_chunk_id         uuid references document_chunks(id) on delete cascade,
  embedding                 vector(384),
  embedding_provider        varchar(50),
  embedding_model           varchar(200),
  embedding_model_version   varchar(50),
  embedding_dimension       integer,
  created_at                timestamptz,
  unique (document_chunk_id, embedding_model, embedding_model_version)
)
```

A dedicated table — not a vector column bolted onto `document_chunks` —
because a chunk can have embeddings from multiple models (or versions of
the same model) coexisting at once, which a single-model-per-chunk design
could never represent without destructive migration. This is the
mechanism the brief called for: "support multiple embedding models or
versions per chunk, not one permanent model."

**Idempotency** is enforced at two layers: the unique constraint
`(document_chunk_id, embedding_model, embedding_model_version)` is the
final, database-level safety net, and `EmbeddingService` additionally
pre-checks `get_embedded_chunk_ids` before even calling the model, so a
re-triggered embedding job for an already-fully-embedded document does no
model inference at all, not just no duplicate insert.

**`embedding_model_version`** is an application-level label (currently
`"1"`), not the Hugging Face revision hash. It exists so a "new
generation" of vectors can be marked even without changing
`embedding_model` — e.g., if normalization or pooling logic changes in a
way that would make old and new vectors incompatible for comparison. Every
row stamps `embedding_provider`/`embedding_model`/`embedding_model_version`/
`embedding_dimension` independently of the *current* `Settings` value, so
historical vectors stay correctly attributable after a future config
change — reading `Settings.embedding_model` tells you what the app would
embed *new* text with today, never what produced an existing stored
vector.

### The vector column's fixed width is a documented, accepted limitation

pgvector requires a fixed dimension per column. `chunk_embeddings.embedding`
is `vector(384)`, matching `sentence-transformers/all-MiniLM-L6-v2`
specifically — not read from `Settings` at migration time, because
changing it requires a schema migration regardless of what a config file
says at runtime. A future embedding model with a *different* dimension
(e.g. a 768-dim model) would need a new column or a new table, not a
config change. This is called out explicitly rather than solved
generically here (e.g. via a `jsonb`/variable-length representation) —
doing so would sacrifice the whole reason to use pgvector (native indexed
vector distance operators) for a problem this milestone doesn't yet have.

### Similarity search: exact cosine distance, no index yet

`ChunkEmbeddingRepository.similarity_search` uses pgvector's
`cosine_distance` (the `<=>` operator), filtered to one
`(embedding_model, embedding_model_version)` pair per query — mixing
vectors from different models in one ranking would compare incompatible
vector spaces, not a meaningful similarity order. Cosine distance was
chosen over L2/inner-product because the embeddings are unit-normalized
(see above), making cosine similarity and normalized inner product
equivalent, and cosine is the conventional choice for sentence-embedding
similarity.

**No HNSW/IVFFlat index is added in this migration.** This is a deliberate,
documented decision, not an oversight: an approximate-nearest-neighbor
index trades correctness for speed, and at this milestone's corpus size
(development-scale, no production traffic yet), an exact sequential scan
is both correct and fast enough — adding index-tuning complexity (list
counts, `ef_search`, recall/latency tradeoffs) ahead of a real need would
be premature optimization. When a vector index is eventually justified by
real data volume, `vector_cosine_ops` is the correct operator class to
pair with the `cosine_distance` query already in place — no query-layer
change needed, only an added index.

This is the "basic similarity-search foundation" the brief calls for, not
a RAG pipeline: it returns chunk id, document id, content, distance, and
model metadata — no query rewriting, filtering, reranking, or
context-assembly logic, all explicitly out of scope here.

### Orchestration: `EmbeddingService`

Mirrors `DocumentService`'s shape (validate preconditions, paginate
through chunks, persist, report outcome) but **commits once per request**
like `ChatService`, not twice like `DocumentService` — `embed_document` is
a single logical unit of work with no durable side effect (like a stored
file) that must survive a later failure the way an uploaded file does.
Each batch's persistence is still wrapped in `session.begin_nested()` (a
`SAVEPOINT`), so one batch's failure (a transient provider error exhausting
retries, or an unexpected persistence error) is recorded as
`failed_count` for that batch without discarding embeddings already
committed to the same transaction from earlier batches in the same
request.

Processing is explicitly **synchronous and triggered via API**
(`POST /api/v1/documents/{id}/embeddings`), not automatic on upload and
not running on a task queue — matching the milestone's stated scope. The
seam for a future background worker already exists without rework:
`EmbeddingService.embed_document(document_id)` takes only a document id
and does not assume anything about its caller, the same seam Milestone 3
built into `DocumentService._process`.

**Batching**: chunks are paged through `DocumentChunkRepository.list_by_document`
(`Settings.embedding_batch_size` chunks at a time, default 32 — not an
unbounded "load all chunks" call), so memory use stays bounded regardless
of document size. Each batch's text list is sent to the provider in one
`embed_texts` call (one model invocation per batch, not per chunk) for
efficiency; a transient provider failure retries the batch (bounded by
`Settings.embedding_max_retries`, exponential backoff capped at 4s) before
being recorded as failed and left for a future re-trigger to pick up via
the same idempotency check.

## Consequences

- **Positive**: multiple models/versions can coexist per chunk with zero
  schema change — directly supports a future model migration (re-embed
  with a new model while the old vectors remain queryable) without any
  data loss or downtime.
- **Positive**: the similarity-search foundation (correct, tested against
  real pgvector with hand-crafted vectors proving exact cosine-distance
  ordering) is ready for a future RAG milestone to build retrieval on top
  of, without needing to revisit this layer.
- **Positive**: CPU-only local inference means this milestone has zero new
  external dependencies (no API key, no network call, no additional
  per-request cost) — consistent with Milestone 3's fully offline
  ingestion pipeline.
- **Negative**: CPU-only inference is slow relative to a GPU or a hosted
  API for large corpora — acceptable for this milestone's local
  development scope and explicitly not addressed here; `EMBEDDING_DEVICE`
  is configurable (`cpu`/`cuda`/`mps`) for whenever that becomes relevant.
- **Negative**: exact (non-indexed) similarity search does not scale
  indefinitely — explicitly deferred, with the index strategy and the
  specific operator class to use already documented above for when it's
  needed.
- **Negative**: the fixed `vector(384)` column width means switching to a
  different-dimension model later requires a migration, not just a config
  change — documented above as an accepted tradeoff for keeping pgvector's
  native vector operators rather than a variable-length representation.

## Related

- [001-modular-monolith.md](001-modular-monolith.md) (the provider-neutral,
  single-import-point pattern this ADR reuses for embeddings)
- [003-vector-store.md](003-vector-store.md) (pgvector extension setup,
  Milestone 0)
- [005-document-ingestion.md](005-document-ingestion.md) (the
  `DocumentChunk` rows this milestone consumes, and the two-commit pattern
  this ADR deliberately does not reuse, and why)
