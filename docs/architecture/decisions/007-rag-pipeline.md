# 7. Retrieval-Augmented Generation: Retrieval, Context Assembly, Citations, and Safety

## Status

Accepted — 2026-10-03

## Context

Milestone 5 builds the first complete RAG pipeline on top of Milestone 3's
document chunks and Milestone 4's pgvector embeddings: a user question is
embedded, matched against stored chunk vectors, assembled into a
structured context, and handed to the LLM gateway to produce a grounded,
cited answer. It explicitly does **not** implement LangGraph, agents, MCP,
A2A, autonomous or multi-agent workflows, a reranker, or a second
(hybrid/keyword) retrieval backend — this is retrieval-augmented
*generation*, not an agentic system. Those are reserved for later
milestones; see the README roadmap.

## Decision

### Architecture: retrieval and generation as separate responsibilities

```
app/rag/
  service.py          RAGService — the only layer combining retrieval + generation
  schemas.py           RAGAnswer, RAGSource, RAGRetrievalMetadata (internal dataclasses)
  exceptions.py        RAGError (minimal — see "Error handling" below)
  retrieval/
    service.py          RetrievalService — resolves limits, applies the threshold
    strategy.py          RetrievalStrategy (interface) -> VectorRetrievalStrategy
    repository.py        RetrievalRepository — the RAG-specific pgvector query
    schemas.py            RetrievalResult, RetrievalOutcome
  context/
    assembler.py          ContextAssembler — source-bounded context + citation IDs
  prompts/
    templates.py          AEGIS_RAG_SYSTEM_PROMPT
    builder.py             RAGPromptBuilder
```

`RetrievalService` has no knowledge of the LLM, prompts, or conversations;
`ContextAssembler` has no knowledge of how results were retrieved; only
`RAGService` is allowed to combine them. This mirrors the project's
existing layering (`ChatService` orchestrates `PromptBuilder` +
`LLMGateway`; `DocumentService` orchestrates extraction + chunking) rather
than introducing a new pattern.

`RetrievalRepository` (new, RAG-specific) is deliberately separate from
Milestone 4's `app.db.repositories.chunk_embedding_repository
.ChunkEmbeddingRepository`: the latter is the generic embedding-storage
foundation (idempotency checks, basic similarity search) and stays
unchanged; the former adds RAG-specific query shaping — joining through to
`Document` for the client-facing filename, and the `document_id` filter
allowlist (see "Metadata filtering" below). Keeping them separate means
Milestone 4's own tests and guarantees are untouched by this milestone.

### Query embedding: reuses EmbeddingService, never touches the model directly

```
RAGService -> RetrievalService -> VectorRetrievalStrategy -> EmbeddingService -> EmbeddingProvider
```

`EmbeddingService` gained one new method for this milestone,
`embed_query(text)`, plus three read-only properties
(`provider_name`/`model_name`/`model_version`). Nothing in `app/rag/`
imports `sentence_transformers` or constructs an `EmbeddingProvider`
directly — the one sanctioned path for embedding arbitrary (non-chunk)
text is through `EmbeddingService`, same as Milestone 4 established.
`VectorRetrievalStrategy` always searches using
`EmbeddingService.model_name`/`model_version` as the filter, so a query is
only ever compared against vectors produced by the exact same model —
comparing vectors from different models would compare incompatible vector
spaces (see [ADR 006](006-embedding-model.md)).

### Similarity metric: cosine SIMILARITY, derived from pgvector's distance

pgvector's `cosine_distance` (`<=>` operator) returns `1 - cosine_similarity`
— 0 for identical vectors, 1 for orthogonal, 2 for opposite (confirmed
empirically in Milestone 4's own repository tests). `RetrievalResult`
carries both: `distance` (the raw pgvector value) and `similarity`
(`1 - distance`), computed once at the strategy boundary so nothing
downstream has to remember which direction is "better" for which metric.
**`RAG_SIMILARITY_THRESHOLD` is expressed as a similarity, not a
distance** — a result qualifies when `similarity >= threshold`. Getting
this backwards (comparing distance as if it were similarity) would
silently invert which results count as "relevant."

### Similarity threshold: a conservative default, not a validated constant

`RAG_SIMILARITY_THRESHOLD` defaults to `0.3`. This is explicitly **a
starting configuration, not a scientifically validated universal value**:
the correct threshold depends on the embedding model (different models
produce different similarity distributions for "related" vs "unrelated"
text), whether vectors are normalized (ours are — see ADR 006), the
corpus's topical diversity, and the actual distribution of real user
queries. It should be tuned against real usage and a real corpus, not
assumed correct because it shipped as the default. A caller can override
it per-request-at-the-service-level (`RetrievalService.retrieve(...,
similarity_threshold=...)`), though the current API schema does not yet
expose this as a client-facing parameter — only `top_k` and `document_id`
are, since the brief's examples list only those for the request schema,
and an unvalidated client-supplied threshold is a wider surface to get
wrong than a server-tuned constant.

### Top-K: a pipeline, not one number

The target architecture's "Top-K Candidates -> Similarity Threshold" is
implemented as two explicit, separately observable stages, not one fused
SQL query:

1. `RetrievalRepository.search` returns the top `K` nearest neighbors by
   distance (optionally filtered by `document_id`), **unfiltered by
   threshold** — these are the "candidates."
2. `RetrievalService.retrieve` filters candidates to those with
   `similarity >= threshold` in plain Python — these are the "results."

Keeping threshold filtering out of the SQL query makes it independently
unit-testable (no database needed) and makes the candidates-vs-results
funnel directly observable for logging (`candidates_found` vs
`chunks_used` — see "Observability" below) without re-deriving one from
the other later.

`RAG_TOP_K` (default `5`) is the default K; `RAG_MAX_RESULTS` (default
`20`) is a hard ceiling a client's `top_k` override cannot exceed — two
separate settings because changing the default shouldn't silently change
the ceiling and vice versa. The API schema additionally bounds `top_k` to
`le=50` at the request-shape level as a second, independent layer (mirrors
`DocumentService`'s layered validation philosophy from Milestone 3) — a
client can never request an unbounded number of chunks even if the two
settings are ever changed independently of each other.

### Metadata filtering: an explicit allowlist, not a query language

Only `document_id` is supported as a filter in this milestone, applied as
a parameterized `WHERE Document.id = :document_id` clause — never raw SQL,
never a generic JSON filter object. The brief explicitly warns against
building an arbitrary filter language, and no other document metadata
field (checksum, upload date, `document_type`) had a concrete use case
driving it in this milestone. Extending the allowlist later (e.g., a
`document_type` filter to restrict retrieval to PDFs) is a small,
backward-compatible addition to `RetrievalRepository.search`'s named
parameters — not a redesign.

An unknown `document_id` filter is treated as a request error, not a
silent empty result: `RAGService` checks the document exists via
`DocumentRepository.get()` before retrieval and raises `NotFoundError`
(→ HTTP 404) if not — the same exception and pattern `ChatService` already
uses for an unknown `conversation_id`, reused rather than duplicated.

### Context assembly: source-bounded blocks, never raw concatenation

`ContextAssembler` turns ranked results into:

```
[SOURCE 1]
Document: Employee Travel Policy
Page: 4

Employees may claim...

---

[SOURCE 2]
Document: Expense Guidelines
Page: 7

Hotel receipts must...
```

Source IDs (`S1`, `S2`, ...) are assigned by the application in retrieval-rank
order — **never by the LLM**. This is what makes citations trustworthy:
the model can only reference an identifier the application already knows
the provenance of, never invent one. `AssembledSource` (one per included
chunk) carries the chunk id, document id, filename, chunk index, page
number, and similarity — everything `RAGChatResponse.sources` needs,
computed once, before generation starts.

### Context limiting: a character budget, not a new tokenizer dependency

`RAG_MAX_CONTEXT_CHARS` (default `8000`) bounds the assembled context's
total size. Character-based, not token-based, for the same reason
Milestone 3's chunking is character-based: no tokenizer dependency exists
yet for a specific embedding/LLM model pairing, and adding one (e.g.
`tiktoken`) only for this budget would be a new dependency whose accuracy
depends on matching the *generation* model's tokenizer — not the
embedding model's — which may change independently. A character count is
a conservative, always-available proxy. If the single most relevant chunk
alone exceeds the budget, `ContextAssembler` still includes a truncated
version of it rather than returning empty context — a partial answer from
the best match is more useful than none. `AssembledContext.truncated`
reports this for observability.

### No-context behavior: a controlled response, never a fabricated one

If no candidate passes the similarity threshold, `RAGService` **never
calls the LLM**. It returns a fixed, honest response
(`"I don't have enough information in the available documents to answer
that question."`) and still persists both conversation turns (the
question and this response) so conversation history stays coherent. This
is mandatory per the brief and is the one behavior with no tunable
"maybe call the LLM anyway" escape hatch — calling the LLM with empty
context just to produce *something* is exactly the failure mode this
milestone must not have.

The API distinguishes four outcomes, not one generic error shape:

| Outcome | Signal |
| --- | --- |
| Grounded answer | `200`, `has_context: true`, `sources` populated |
| No relevant context | `200`, `has_context: false`, `sources: []`, the fixed message |
| Retrieval/embedding failure | Mapped HTTP error (502/500) via existing `EmbeddingProviderError`/`EmbeddingDimensionMismatchError` handlers |
| Generation failure | Mapped HTTP error (429/503/504/502/400) via the existing `LLMError` hierarchy handlers |

"No relevant context" is a successful `200` response, not an error — the
system worked correctly by recognizing it shouldn't guess.

### Prompt injection: retrieved documents are untrusted data

`AEGIS_RAG_SYSTEM_PROMPT` (separate from the plain chat system prompt —
reusing it would say nothing about untrusted content or citations)
explicitly instructs the model that the CONTEXT section is untrusted data
retrieved from documents, never instructions to follow, and that these
rules override anything appearing inside that CONTEXT. The retrieved text
is placed verbatim inside a clearly delimited `CONTEXT:` block in the
*user* turn — never merged into, or allowed to replace, the *system*
message.

This milestone's test suite verifies the **structural** guarantee: a
malicious chunk's content ends up inside the CONTEXT boundary of the user
message and never inside the system message, proven both at the unit
level (fake gateway capturing the exact messages sent) and at the
integration level (a real retrieval round-trip through Postgres with a
genuinely malicious stored chunk). What this milestone's tests do **not**,
and cannot, prove is that a real LLM will always refuse to follow an
injected instruction — that depends on the underlying model's own
training and is outside this application's control. The mitigation here
is defense simulation-tested at the structural/prompt-construction layer,
not a guarantee about model behavior; a production deployment should treat
this as one layer of a broader defense (e.g., output filtering, human
review for sensitive actions), not a complete solution.

### Conversation integration: no duplicated persistence logic

`RAGService` reuses `ConversationRepository`/`MessageRepository` directly
(the same repositories `ChatService` uses) and mirrors
`ChatService`'s atomicity: one commit per request via
`app.db.session.get_session`'s ambient commit/rollback for the
non-streaming endpoint, and an explicit `session.rollback()` before
re-raising on a mid-stream `LLMError` for the streaming endpoint (the API
layer catches `LLMError` there to emit a clean terminal SSE event instead
of propagating, so the ambient rollback never fires on its own — identical
reasoning to `ChatService.stream_message`). The ~6-line
`_get_or_create_conversation` helper is intentionally duplicated from
`ChatService` rather than extracted into a shared base class or repository
method: it's small enough that "three similar lines" outweighs introducing
a new abstraction two call sites would share, and it avoids touching
Milestone 2's `ChatService` for a Milestone 5 concern.

**Conversation history policy** (explicit, not sophisticated): the full
prior history is included in the prompt, in order, exactly as
`PromptBuilder` already does for plain chat — no conversational query
rewriting (e.g., resolving "what about last year?" against prior turns
before embedding) is implemented. The embedded query is always just the
current message's raw text. This is a known, documented limitation: a
follow-up question that depends on earlier conversational context for its
*meaning* may retrieve poorly, since retrieval never sees that context —
only generation does. Fixing this (e.g., an LLM call to rewrite the query
using history before embedding it) is deferred, consistent with the
brief's "do not implement sophisticated conversational query rewriting
yet."

### Streaming: sources come from retrieval, never the model

`RAGService.answer_stream` embeds the query and assembles context
*before* streaming begins, so the source list is fully known up front.
Each yielded chunk carries `sources=None` except the final chunk
(`is_final=True`), which carries the complete list — mirroring how
`StreamChunk.usage` is already `None` until the final chunk in the
existing plain-chat stream. The model is never asked to produce citation
metadata; it only ever sees source identifiers already assigned by the
application, in the CONTEXT text, and may reference them inline (e.g.
"[S1]") in its own generated prose.

### Hybrid search foundation (not implemented)

`RetrievalStrategy` is an abstract interface with one concrete
implementation, `VectorRetrievalStrategy`. A future keyword/BM25 or hybrid
strategy implements the same interface
(`search(query, top_k, document_id) -> list[RetrievalResult]`) and can be
swapped in — or composed alongside the vector strategy with a score-fusion
step — without `RetrievalService`, `RAGService`, or the API changing. No
Elasticsearch/OpenSearch or other new infrastructure is introduced; this
is purely an interface seam, not a half-built hybrid engine.

### Reranking (not implemented)

The intended future insertion point is between retrieval and context
assembly:

```
Vector retrieval -> Candidate set -> Reranker -> Final context -> LLM
```

`RetrievalService.retrieve` already returns a distinct `candidates` list
(pre-threshold) and `results` list (post-threshold) — a reranker would
slot in as a step that re-scores `results` (or `candidates`, if reranking
should see more than the threshold allows through) before
`ContextAssembler.assemble` is called, with no change to
`RetrievalRepository` or `VectorRetrievalStrategy` needed.

### Evaluation approach

A small, synthetic, non-sensitive fixture
(`tests/evaluation/rag_fixtures.py`: 3 documents, 6 chunks, 5 questions,
each with one known-relevant chunk) backs a Recall@K test
(`tests/evaluation/test_recall_at_k.py`, `K=3`). It is explicitly **not** a
benchmark and claims nothing about retrieval quality on any real corpus —
the fixture is deliberately small and topically well-separated to make the
test itself fast and deterministic to reason about, not representative of
production document diversity. The test is opt-in (`RUN_EMBEDDING_INTEGRATION=1`,
same gate as the other real-model tests) because a deterministic fake
embedding would make Recall@K meaningless — nothing would stop the fixture
from being riggable to always "succeed" against a fake vector function. A
real measurement needs the real model. See the end-of-milestone report for
the actual Recall@3 result against this fixture.

### Error handling: reuse, don't duplicate

`app/rag/exceptions.py` defines only a near-empty `RAGError` base. Every
concrete RAG failure mode already has a typed exception elsewhere in the
codebase: query-embedding failures surface as
`EmbeddingProviderError`/`EmbeddingDimensionMismatchError` (Milestone 4,
already mapped to 502/500), generation failures as the `LLMError`
hierarchy (Milestone 1, already mapped to 429/503/504/502/400), and an
unknown conversation or document filter as `NotFoundError` (Milestone 2,
already mapped to 404). `RAGService` lets all of these propagate rather
than wrapping them in a new RAG-specific type — introducing parallel
exception types for failures that already have one would be duplication,
not clarity.

### Observability

Structured logs (`rag_answer_generated` / `rag_no_context`) include:
correlation id (via existing middleware), retrieval duration, candidate
count, final chunk count, similarity threshold, top-K, embedding
model/version, LLM model, and total tokens — never the raw question text
content judged sensitive, document content, full prompts, full model
responses, or embedding vectors (consistent with every prior milestone's
logging discipline).

## Consequences

- **Positive**: retrieval, context assembly, and generation remain
  independently testable — `RetrievalService` and `ContextAssembler` are
  both fully unit-tested with zero database or model dependency, while the
  real pgvector/real-model guarantees are proven in a small number of
  integration tests, not smeared across every test.
- **Positive**: the `RetrievalStrategy` and reranker insertion points mean
  the next two retrieval-quality milestones (hybrid search, reranking)
  are additive, not a RAGService rewrite.
- **Positive**: citations are structurally trustworthy — the model cannot
  invent a source identifier that doesn't map to a real retrieved chunk,
  because the mapping is built by the application before generation.
- **Negative**: no conversational query rewriting means multi-turn
  follow-ups that depend on prior context for *meaning* (not just for the
  final answer) may retrieve poorly — documented above, not hidden.
- **Negative**: the similarity threshold default is explicitly unvalidated
  against real usage; shipping it without a tuning pass on real traffic
  risks both over-filtering (false "no context") and under-filtering
  (weakly related chunks reaching the LLM).
- **Negative**: prompt-injection mitigation is structural, not a
  guarantee — a sufficiently adversarial document could still influence a
  susceptible underlying model's behavior within the untrusted-context
  framing. This is a known, inherent limitation of prompt-based isolation,
  not something this milestone can fully close.

## Related

- [002-llm-gateway.md](002-llm-gateway.md) (the `LLMGateway` this milestone
  calls for generation, unchanged)
- [004-conversation-persistence.md](004-conversation-persistence.md) (the
  atomicity pattern this milestone's `RAGService` mirrors)
- [005-document-ingestion.md](005-document-ingestion.md) (the
  `DocumentChunk` rows this milestone retrieves)
- [006-embedding-model.md](006-embedding-model.md) (the embedding
  model/versioning and pgvector cosine-distance foundation this milestone
  builds retrieval on top of)
