# System Design

This describes the system as it exists today. It intentionally does not
describe unimplemented future capabilities beyond their reserved module
boundaries — see the roadmap in the [README](../../README.md) and the ADRs
in [decisions/](decisions/) for where those are headed.

## Overview

AegisAI is a modular monolith: a single FastAPI application (`backend/app`)
backed by PostgreSQL (conversation/message/document/embedding persistence,
using pgvector for vector storage and similarity search), Redis, local
filesystem document storage, a local Sentence Transformers embedding
model, and the Groq-backed LLM gateway, fronted by a Streamlit UI, all
orchestrated via Docker Compose in local development.

```
┌─────────────────┐       HTTP        ┌──────────────────────────────────────────────────┐
│ Streamlit UI     │ ─────────────────▶│ FastAPI app (backend)                            │
│ (frontend/)      │                   │  api/ -> services/, rag/, agents/ -> prompts/, llm/, documents/, embeddings/, db/ │
└─────────────────┘                   └──┬──────────────┬──────────────────┬─────────────┘
                                          │              │                  │
                          ┌───────────────┼──────┐       │        ┌────────┴────────┐
                          ▼               ▼       ▼       ▼        ▼
                ┌──────────────────┐ ┌──────────┐    ┌───────────────┐  ┌──────────────┐
                │ PostgreSQL        │ │ Redis    │    │ Groq API       │  │ Local disk    │
                │ conversations,    │ │          │    │ (external)     │  │ data/uploads/ │
                │ messages,         │ │          │    │               │  │ (DocumentStorage)│
                │ documents, chunks │ │          │    │               │  │               │
                │ + pgvector        │ │          │    │               │  │               │
                └──────────────────┘ └──────────┘    └───────────────┘  └──────────────┘
```

## Backend module boundaries

| Module | Responsibility today |
| --- | --- |
| `api/` | Thin HTTP routing and request/response schemas. No business logic, no database queries. |
| `core/` | Cross-cutting concerns: logging, middleware, exception handling (including LLM error -> HTTP status mapping, and `NotFoundError`). Security/RBAC is reserved, not implemented. |
| `domain/` | ORM models (`Conversation`, `Message`, `Document`, `DocumentChunk`, `ChunkEmbedding`) and enums (`MessageRole`, `DocumentStatus`, `DocumentType`). |
| `services/` | Business logic orchestration, called from `api/`. `chat_service.py` (Milestone 1, extended in Milestone 2), `conversation_service.py` (Milestone 2), and `document_service.py` (Milestone 3) are implemented; other service modules are still reserved. |
| `prompts/` | Prompt management — versioned templates + `PromptBuilder`, which assembles `[system, history, new message]`. Implemented in Milestone 2. See [ADR 004](decisions/004-conversation-persistence.md). |
| `llm/` | The LLM gateway — a provider-neutral abstraction over chat completion. Implemented in Milestone 1, backed by Groq. See [ADR 002](decisions/002-llm-gateway.md). |
| `documents/` | Document ingestion: `validation.py`, `normalization.py`, `metadata.py`, `chunk_ids.py`, `extractors/` (one module per `DocumentType`: `pdf.py` via pypdf, `docx.py` via python-docx, `text.py`/`markdown.py`), `chunking/` (`RecursiveChunker`). Implemented in Milestone 3. See [ADR 005](decisions/005-document-ingestion.md). |
| `storage/` | Provider-neutral file storage (`base.py`); `local.py` (`LocalFileStorage`) is the only implementation. Implemented in Milestone 3. |
| `embeddings/` | Text embedding — a provider-neutral abstraction (`base.py`) over turning text into vectors, plus `service.py` (`EmbeddingService`, orchestration: batching, idempotency, persistence, and — new in Milestone 5 — `embed_query`). `providers/local.py` (`LocalEmbeddingProvider`, Sentence Transformers) is the only implementation and the only module allowed to import `sentence_transformers`. Implemented in Milestone 4. See [ADR 006](decisions/006-embedding-model.md). |
| `rag/` | Retrieval-augmented generation: `service.py` (`RAGService`, the only layer combining retrieval with generation), `retrieval/` (`RetrievalService`, `RetrievalStrategy`/`VectorRetrievalStrategy`, `RetrievalRepository`), `context/` (`ContextAssembler`), `prompts/` (`AEGIS_RAG_SYSTEM_PROMPT`, `RAGPromptBuilder`). Implemented in Milestone 5. See [ADR 007](decisions/007-rag-pipeline.md). |
| `agents/` | Single-agent LangGraph orchestration with controlled tool calling: `service.py` (`AgentService`), `graph.py` (the `StateGraph`), `schemas.py` (`AgentState` and result types), `messages.py` (LangChain-message ↔ `ChatMessage` boundary), `prompts.py` (`AEGIS_AGENT_SYSTEM_PROMPT`), `tools/` (`ToolRegistry`/`ToolDefinition` + internal tools `calculator`, `get_document_metadata`, `search_knowledge_base`, plus the Milestone 7 `research_delegation.py` A2A tool and MCP-discovered tools registered at build time). Implemented in Milestone 6, extended in Milestone 7. See [ADR 008](decisions/008-agent-architecture.md) and [ADR 009](decisions/009-mcp-a2a-architecture.md). |
| `mcp/` | Model Context Protocol server + client: `server.py` (`build_mcp_server`, thin adapters over the same `ToolDefinition.executor` internal tools use, plus the `document://{document_id}` resource), `client.py` (`discover_mcp_tool_definitions`, discovery + allowlist + wraps each approved tool as a `ToolDefinition`), `exceptions.py`. Implemented in Milestone 7. See [ADR 009](decisions/009-mcp-a2a-architecture.md). |
| `a2a/` | Agent2Agent: the Research/Document/Analyst agents and the client that reaches them. `agent_card.py` (`build_research_agent_card`/`document_agent_card`/`analyst_agent_card`, real `a2a.types.AgentCard`), `research_agent.py`/`document_agent.py`/`analyst_agent.py` (each agent's own service — `ResearchAgentService`/`DocumentAgentService`/`AnalystAgentService` — reusing `RetrievalService`/`DocumentRepository`/`CALCULATOR_TOOL`/`LLMGateway` directly), `tasks.py` (`build_generic_task`/`build_task`/`task_to_dict`, real `a2a.types.Task`/`Artifact`), `client.py` (`A2AClient`, the only way any orchestrator reaches a specialist — trusted-agent allowlist, Card validation, `submit_task`/`submit_research_task`), `exceptions.py`. Research Agent implemented in Milestone 7; Document/Analyst Agents and the generalized `submit_task` in Milestone 8. See [ADR 009](decisions/009-mcp-a2a-architecture.md)/[ADR 010](decisions/010-multi-agent-architecture.md). |
| `multi_agent/` | Multi-agent orchestration: `orchestrator.py` (`MultiAgentOrchestrator` — route, authorize, run tier-1 agents in parallel, run the Analyst sequentially, aggregate), `router.py` (deterministic regex/keyword routing policy), `capabilities.py` (the static agent/capability registry), `policies.py` (allowed workflow transitions, the retryable-exception allowlist), `models.py` (`AgentContext`/`AgentResult`/`WorkflowResult`), `adapters.py` (per-agent A2A adapters that never raise), `aggregation.py` (`ResultAggregator`), `exceptions.py`. Implemented in Milestone 8. See [ADR 010](decisions/010-multi-agent-architecture.md). |
| `db/` | SQLAlchemy async engine/session, Redis client management, connectivity checks used by `/health/ready`, and `repositories/` (`ConversationRepository`, `MessageRepository`, `DocumentRepository`, `DocumentChunkRepository`, `ChunkEmbeddingRepository`) — the only code that issues SQLAlchemy queries. |
| `tools/`, `memory/`, `evaluation/`, `observability/`, `workers/` | Reserved for future milestones (see the README roadmap). Each is an empty Python package today. (Milestone 6's tool calling lives in `app.agents.tools`, not the top-level `tools/` — see that row above.) |

Dependency direction is one-way: `api` → `services`/`rag`/`agents` →
`prompts`/`llm`/`documents`/`storage`/`embeddings`/`db`. `domain/` sits
below everything and depends on nothing else in the app (notably, `domain`
does not depend on `llm` — see
[ADR 004](decisions/004-conversation-persistence.md) on why `MessageRole`
and `ChatRole` are separate types). Within `llm/`: `gateway.py` →
`base.py` (the `LLMProvider` interface) → `providers/groq.py`. Within
`embeddings/`: `service.py` → `base.py` (the `EmbeddingProvider`
interface) → `providers/local.py`. Within `rag/`: `service.py` →
`retrieval/service.py` → `retrieval/strategy.py` (the `RetrievalStrategy`
interface) → `retrieval/repository.py`, and separately `service.py` →
`context/assembler.py` and `prompts/builder.py`; `rag/` never imports
`sentence_transformers`, `app.db.repositories.chunk_embedding_repository`,
or a provider SDK directly — it only ever reaches the embedding model
through `EmbeddingService` and the LLM through `LLMGateway`, the same as
every other service. Within `agents/`: `service.py` → `graph.py` (the
`StateGraph`) → `tools/registry.py` (which assembles the explicit
`ToolRegistry` — the only path from a tool name to an executable
function); `agents/` never imports a provider SDK or
`sentence_transformers` either — the knowledge-base tool reaches pgvector
only through the existing `RetrievalService`, and all LLM calls (including
tool-calling ones) go through the existing `LLMGateway`. Routes never talk
to the database, Redis, the Groq SDK, the filesystem, a parsing library,
or an embedding model directly — `app.llm.providers.groq` is the *only*
module allowed to import `groq`; `app.documents.extractors` is the only
code allowed to import `pypdf`/`docx`; `app.embeddings.providers.local` is
the only code allowed to import `sentence_transformers`; `app.storage` is
the only code that touches the filesystem; `app.db.repositories` (and, for
the RAG-specific retrieval query, `app.rag.retrieval.repository`) is the
only code that builds SQLAlchemy queries; `app.agents.tools` is the only
code that calls a registered tool's executor.

## Request lifecycle (today)

1. A request hits `CorrelationIdMiddleware` (`core/middleware.py`), which
   assigns or propagates an `X-Request-ID`, binds it to structlog's
   contextvars, and logs the request's completion with method, path,
   status code, and duration.
2. FastAPI routes the request. `/health`, `/health/ready`
   (`api/v1/health.py`), `/api/v1/chat/completions[/stream]`
   (`api/v1/chat.py`), `/api/v1/conversations[/...]`
   (`api/v1/conversations.py`), `/api/v1/documents[/...]`, including
   `/api/v1/documents/{id}/embeddings` (`api/v1/documents.py`),
   `/api/v1/rag/chat[/stream]` (`api/v1/rag.py`), and
   `/api/v1/agents/run[/stream]` (`api/v1/agents.py`) are implemented;
   everything else under `/api/v1` is reserved for future business
   endpoints.
3. Unhandled errors — including the typed `LLMError` hierarchy,
   `NotFoundError`, `DocumentValidationError`, `DocumentNotReadyError`,
   `EmbeddingProviderError`, `EmbeddingDimensionMismatchError`, and
   `AgentTimeoutError` — are caught by handlers registered in
   `core/exceptions.py` and returned as a consistent JSON envelope:
   `{"error": {"code", "message", "request_id"}}`. The RAG and agent
   endpoints both reuse these same handlers rather than registering
   duplicate ones per milestone (see [ADR 007](decisions/007-rag-pipeline.md)
   and [ADR 008](decisions/008-agent-architecture.md), "Error handling").
   Raw provider exceptions, raw database errors, and raw filesystem paths
   never reach this layer.

## Health and readiness

- `GET /health` — liveness only; always returns `200 {"status": "ok"}` if
  the process is running.
- `GET /health/ready` — readiness; checks PostgreSQL (`SELECT 1`) and Redis
  (`PING`) with a short timeout each, returning `200` with
  `{"status": "ready", "database": "ok", "redis": "ok"}` when both succeed,
  or `503` with `"status": "degraded"` and per-dependency detail otherwise.
  (Groq is not part of this check — see [data-flow.md](data-flow.md) for
  why the chat endpoints fail fast instead.)

## LLM Gateway

See [ADR 002](decisions/002-llm-gateway.md) for the full rationale. In
brief: `ChatService` → `llm/gateway.py` (`LLMGateway`) → `llm/base.py`
(`LLMProvider` interface) → `llm/providers/groq.py` (`GroqProvider`) → the
`groq` SDK. Model selection is a deterministic `ModelRole`
(`primary`/`fast`/`safety`) → configured model name mapping
(`PRIMARY_LLM_MODEL`, `FAST_LLM_MODEL`, `SAFETY_LLM_MODEL`), not an
AI-based router.

## Conversation persistence

See [ADR 004](decisions/004-conversation-persistence.md) for the full
rationale and [data-flow.md](data-flow.md) for the request flow. In brief:

- **Schema** (migration `0002_add_conversations_and_messages`):
  `conversations` (`id`, `title`, `created_at`, `updated_at`) and
  `messages` (`id`, `conversation_id` FK `ON DELETE CASCADE`, `role`
  — `VARCHAR` + `CHECK` constraint, not a native Postgres enum —
  `content`, `model`, `provider`, `finish_reason`, `request_id`,
  `input_tokens`, `output_tokens`, `total_tokens`, `created_at`), with a
  composite index on `(conversation_id, created_at)` for ordered history
  reads.
- **`ChatService`** orchestrates: resolve-or-create the conversation, load
  prior messages via `MessageRepository`, build the prompt via
  `PromptBuilder`, call `LLMGateway`, persist both the user and assistant
  messages, update the conversation's `updated_at`.
- **Atomicity**: a chat turn is all-or-nothing — see
  [ADR 004](decisions/004-conversation-persistence.md) for why, and how
  this is enforced identically for both the plain and streaming endpoints
  despite streaming's additional complexity (an SSE error event can't
  become an HTTP error status after the stream has started).
- **`ConversationService`** is a thin read/delete layer for
  `GET /api/v1/conversations`, `GET /api/v1/conversations/{id}`, and
  `DELETE /api/v1/conversations/{id}` — no LLM/prompt concerns.

## Document ingestion

See [ADR 005](decisions/005-document-ingestion.md) for the full rationale
and [data-flow.md](data-flow.md) for the request flow. In brief:

- **Schema** (migration `0003_add_documents_and_document_chunks`):
  `documents` (`id`, `filename` — internal storage key — `original_filename`,
  `content_type`, `document_type`, `file_size`, `checksum` (indexed, for
  duplicate detection), `status`, `error_message`, `page_count`,
  `character_count`, `metadata` JSONB, `created_at`, `updated_at`,
  `processed_at`) and `document_chunks` (`id` — a deterministic UUID5, not
  a random UUID4, see the ADR — `document_id` FK `ON DELETE CASCADE`,
  `chunk_index`, `content`, `character_count`, `token_count` (currently
  always `null` — see the ADR), `metadata` JSONB, `created_at`), with a
  unique constraint on `(document_id, chunk_index)`.
- **`DocumentService`** orchestrates: validate -> checksum -> duplicate
  check -> store -> extract -> normalize -> build metadata -> chunk ->
  persist, updating `DocumentStatus` throughout
  (`UPLOADED -> PROCESSING -> PROCESSED | FAILED`).
- **Two commits per upload** (not one, unlike `ChatService`): the
  `UPLOADED` row is committed once storage succeeds, and the processing
  outcome (`PROCESSED` + chunks, or `FAILED` + a safe error message) is
  committed separately — so a processing failure never erases the record
  that an upload happened. See the ADR for why, and for a correctness
  lesson learned about mixing the application's clock with Postgres's own
  for timestamps that need to compare consistently.
- **Storage** is provider-neutral (`app.storage.DocumentStorage`);
  `LocalFileStorage` is the only implementation, keyed by the document's
  own id (never the client's filename), under `Settings.document_storage_dir`.
- **Extraction** is one module per `DocumentType` (`app.documents.extractors`):
  `pypdf` for PDF, `python-docx` for DOCX, a dependency-free encoding
  fallback chain for TXT/Markdown.
- **Chunking** (`RecursiveChunker`) is character-based (not token-based —
  see the ADR), splits per-page so every chunk has an exact, unambiguous
  page reference, and produces deterministic chunk ids reproducible from
  `(document checksum, chunk size, chunk overlap, chunk index)`.

## Embeddings

See [ADR 006](decisions/006-embedding-model.md) for the full rationale and
[data-flow.md](data-flow.md) for the request flow. In brief:

- **Schema** (migration `0004_add_chunk_embeddings`): `chunk_embeddings`
  (`id`, `document_chunk_id` FK `ON DELETE CASCADE`, `embedding` —
  `vector(384)`, fixed-width per the ADR — `embedding_provider`,
  `embedding_model`, `embedding_model_version`, `embedding_dimension`,
  `created_at`), with a unique constraint on `(document_chunk_id,
  embedding_model, embedding_model_version)` — one row per (chunk, model,
  version), not per chunk, so a chunk can have embeddings from multiple
  models/versions at once.
- **Model**: `sentence-transformers/all-MiniLM-L6-v2` (384-dim, CPU
  inference, locally hosted — no API key, no network call per embedding),
  run via `LocalEmbeddingProvider` (`app.embeddings.providers.local`),
  the only module allowed to import `sentence_transformers`. Model loading
  and inference are both offloaded via `asyncio.to_thread`.
- **`EmbeddingService`** orchestrates: validate the document is
  `PROCESSED` -> page through its chunks in
  `Settings.embedding_batch_size`-sized batches -> skip chunks already
  embedded for the current model/version (idempotency) -> embed the rest
  (with bounded retry on transient provider failures) -> persist each
  batch inside a `SAVEPOINT`. Commits once per request, like `ChatService`
  — unlike `DocumentService`'s two-commit pattern, since there's no
  durable side effect (like a stored file) that must survive a later
  in-request failure. See the ADR for why.
- **Triggering is explicit and synchronous**: `POST
  /api/v1/documents/{id}/embeddings`, not automatic on upload and not
  queued — the brief's stated scope for this milestone. `GET
  /api/v1/documents/{id}/embeddings` reports coverage status
  (`not_started` / `partial` / `complete` / `no_chunks`) and model
  metadata — never a raw vector.
- **Similarity search** (`ChunkEmbeddingRepository.similarity_search`) uses
  pgvector's cosine distance, filtered to one `(model, version)` pair, with
  no approximate-nearest-neighbor index yet — an intentional, documented
  deferral (see the ADR) since exact search is correct and fast enough at
  this milestone's corpus size. This is a foundation, not RAG: no query
  rewriting, filtering, or reranking.

## RAG Pipeline

See [ADR 007](decisions/007-rag-pipeline.md) for the full rationale and
[data-flow.md](data-flow.md) for the request flow. In brief:

- **No new tables** — RAG reads `chunk_embeddings`/`document_chunks`/
  `documents` (Milestones 3–4) and writes to the existing
  `conversations`/`messages` tables (Milestone 2); sources are returned in
  the API response but not persisted to the database in this milestone.
- **`RetrievalService`** resolves `top_k` (default `RAG_TOP_K=5`, capped at
  `RAG_MAX_RESULTS=20`) and the similarity threshold (default
  `RAG_SIMILARITY_THRESHOLD=0.3`, a cosine *similarity* — `1 -
  cosine_distance` — not a raw distance), delegates the actual search to a
  `RetrievalStrategy` (`VectorRetrievalStrategy` is the only
  implementation — an explicit seam for a future hybrid strategy), then
  filters the returned candidates by the threshold in plain Python.
- **`VectorRetrievalStrategy`** embeds the query via
  `EmbeddingService.embed_query` (never a raw `EmbeddingProvider`) and
  searches pgvector via `RetrievalRepository` — a RAG-specific query
  (joins through to `Document` for the filename, supports an explicit
  `document_id` filter) kept separate from Milestone 4's generic
  `ChunkEmbeddingRepository`.
- **`ContextAssembler`** turns ranked results into `[SOURCE n]`-delimited
  blocks with document/page headers, assigning stable source IDs
  (`S1`, `S2`, ...) the LLM can cite but never invents, bounded by
  `RAG_MAX_CONTEXT_CHARS` (default `8000`, character-based — see the ADR
  for why not token-based).
- **`RAGService`** orchestrates: resolve/create the conversation ->
  validate an optional `document_id` filter exists (`NotFoundError` ->
  404 if not) -> retrieve -> **no qualifying results: return a fixed
  "I don't have enough information..." response without ever calling the
  LLM** -> otherwise assemble context -> build the RAG prompt
  (`AEGIS_RAG_SYSTEM_PROMPT`, explicitly distinct from the plain chat
  prompt) -> call `LLMGateway` -> persist both turns -> attach sources.
  Commits once per request (like `ChatService`), not twice (unlike
  `DocumentService`) — see the ADR for why.
- **Prompt injection**: the RAG system prompt instructs the model that
  retrieved CONTEXT is untrusted data, never instructions, and that these
  rules override anything inside it. Tested both at the unit level (a
  fake gateway capturing the exact messages sent) and the integration
  level (a real malicious chunk retrieved through real Postgres) — proving
  the structural boundary, not a guarantee about any specific model's
  behavior (see the ADR).
- **Streaming** (`POST /api/v1/rag/chat/stream`) retrieves and assembles
  context before streaming begins, so sources are known up front; each
  SSE chunk carries `sources: null` except the final one, mirroring how
  `usage` is already `None` until the final chunk of the plain chat
  stream.
- **Evaluation**: a small Recall@K fixture
  (`tests/evaluation/rag_fixtures.py` + `test_recall_at_k.py`, opt-in,
  real embedding model) — illustrative, not a benchmark; see the ADR and
  the end-of-milestone report for the actual result.

## Agents

See [ADR 008](decisions/008-agent-architecture.md) for the full rationale
and [data-flow.md](data-flow.md) for the request flow. In brief:

- **No new tables** — like RAG, the agent reads/writes the existing
  `conversations`/`messages` tables only; per-run workflow state
  (`AgentState`) lives only in memory for the duration of one LangGraph
  invocation and is never persisted.
- **`AgentService`** orchestrates: resolve/create the conversation -> load
  history -> build the initial LangGraph state -> invoke the graph
  (wrapped in `asyncio.wait_for(..., timeout=AGENT_TIMEOUT_SECONDS)`) ->
  extract the final answer/tool-usage-summary/knowledge-base sources ->
  persist only the user question and final assistant answer (never
  intermediate tool traffic) -> return a normalized result.
- **The graph** (`app/agents/graph.py`, LangGraph `StateGraph`,
  `langgraph==1.2.12`): `agent` node calls `LLMGateway.chat_completion`
  (extended this milestone with an optional `tools` parameter) and never
  executes a tool itself; `tools` node is the only code that calls
  `ToolRegistry.execute`; `should_continue` routes to `tools` (under both
  limits), a `max_steps`/`max_tool_calls` stop node, or `END` — every path
  terminates in a bounded number of steps.
- **Three internal tools** (`app.agents.tools`): `calculator` (AST-based
  arithmetic — never `eval`/`exec` — with operand/exponent magnitude
  bounds against computational DoS), `get_document_metadata` (reuses
  `DocumentRepository.get`), `search_knowledge_base` (reuses
  `RetrievalService.retrieve` directly — agentic RAG, not a duplicate
  retrieval path). Milestone 7 adds **MCP-discovered tools** (the same
  three capabilities, reached over the Model Context Protocol —
  `mcp_calculator`, `mcp_get_document_metadata`,
  `mcp_search_knowledge_base`) and one **A2A delegation tool**
  (`delegate_to_research_agent`, reaching the remote Research Agent only
  through `A2AClient`). `build_tool_registry` is `async` so MCP discovery
  can run at registry-construction time; a broken/unavailable MCP server
  degrades to "no MCP tools," never a broken agent. The registry is an
  explicit, closed allowlist regardless of capability source: an
  unregistered tool name can never execute. See
  [ADR 009](decisions/009-mcp-a2a-architecture.md).
- **Tool arguments are untrusted input**: every call goes through
  JSON-parsing, then `args_schema.model_validate` (Pydantic), before an
  executor ever runs; `ToolRegistry.execute` never raises — it always
  returns a structured `ToolResult(success, data, error, error_code)`,
  even when the executor itself throws.
- **Safety limits**: `AGENT_MAX_STEPS` (default `8`) and
  `AGENT_MAX_TOOL_CALLS` (default `10`) are checked *before* acting, not
  after, and produce a controlled `AgentRunResult` (HTTP `200`,
  `status: "max_steps_exceeded"`/`"max_tool_calls_exceeded"`) — the same
  "safe self-stop is not an error" reasoning as RAG's "no context."
  `AGENT_TIMEOUT_SECONDS` (default `60.0`) is a wall-clock backstop that
  *does* map to an error (`AgentTimeoutError` -> HTTP `504`), since a
  timeout means the run didn't complete at all.
- **Streaming** (`POST /api/v1/agents/run/stream`) emits only
  `tool_started`/`tool_completed`/`answer_delta`/`completed` events —
  never an intermediate `AIMessage`'s free-text reasoning. The final
  answer is delivered as one complete `answer_delta`, not token-streamed —
  see the ADR for why (tool-call decisions need complete structured
  output, so the agent's internal LLM calls are never themselves
  streaming).
- **Evaluation**: a 9-scenario deterministic fixture
  (`tests/evaluation/agent_fixtures.py` + `test_agent_evaluation.py`) run
  against the real graph/tool registry with every LLM response scripted —
  a behavioral regression checklist, not a measurement of real-model
  accuracy; see the ADR.

## MCP and A2A

See [ADR 009](decisions/009-mcp-a2a-architecture.md) for the full
rationale. In brief:

- **MCP** standardizes the *tool* boundary. `app.mcp.server.build_mcp_server`
  wraps the same three internal `ToolDefinition`s as MCP tools (no second
  implementation) plus a `document://{document_id}` resource.
  `app.mcp.client.discover_mcp_tool_definitions` discovers tools from the
  server (never hardcoded), validates both the server identity
  (`TRUSTED_MCP_SERVERS`) and each tool name (`TRUSTED_MCP_TOOLS`) against
  an explicit allowlist, and wraps each approved tool as the same
  `ToolDefinition` abstraction an internal tool uses. Transport is the
  MCP SDK's in-process `Client(server)` mode for the agent's own calls
  (this reference implementation runs the server and the agent in the
  same process); `scripts/mcp_stdio_server.py` runs the identical server
  over the standard stdio transport for an external MCP client.
- **A2A** standardizes the *agent* boundary. One remote Research Agent
  (`app.a2a.research_agent.ResearchAgentService`, reusing
  `RetrievalService`/`LLMGateway` directly) is reached only through
  `app.a2a.client.A2AClient` — the orchestrator never imports
  `ResearchAgentService`. `A2AClient` fetches and validates the Research
  Agent's Agent Card (`GET /.well-known/agent-card.json`, a real
  `a2a.types.AgentCard`) against both a base-URL allowlist
  (`TRUSTED_A2A_AGENTS`) and the card's own identity/skill, then submits a
  task (`POST /api/v1/agents/research/tasks`) and parses the resulting
  `Task` (real `a2a.types.Task`/`TaskState`) back into a structured
  result — never trusting the response shape blindly. The task handling
  is synchronous (no task store/polling) since this Research Agent's work
  fits comfortably inside one HTTP request's timeout budget.
- Both protocols converge on the same `ToolRegistry` the M6 agent already
  had: MCP tools and the A2A delegation tool are registered exactly like
  an internal tool, so `app/agents/graph.py`'s dispatch logic needed no
  changes — only a `capability` label (`internal`/`mcp`/`a2a`) added to
  its existing observability events.
- **Trust is never derived from model output**: `TRUSTED_MCP_SERVERS`/
  `TRUSTED_MCP_TOOLS`/`TRUSTED_A2A_AGENTS` are fixed at startup from
  configuration; `delegate_to_research_agent`'s own argument schema has
  no endpoint/URL field the LLM could populate to redirect the call.

## Multi-agent orchestration

See [ADR 010](decisions/010-multi-agent-architecture.md) for the full
rationale. In brief:

- **`MultiAgentOrchestrator`** (`app.multi_agent.orchestrator`) routes a
  request (`app.multi_agent.router.route` — deterministic regex/keyword,
  no live model call) to up to three specialists — **Research** (reused
  from Milestone 7), **Document** (new: safe metadata lookup via
  `DocumentRepository`, no LLM call), **Analyst** (new: safe calculator +
  evidence synthesis via `LLMGateway`, no external system access of its
  own) — reached only through `A2AClient.submit_task` (the generalized
  form of Milestone 7's `submit_research_task`), never by importing a
  specialist's service class.
- **Parallel + sequential**: independent specialists (Research, Document)
  run concurrently via `asyncio.gather`; the Analyst — the one agent
  capable of calculation/cross-specialist synthesis — always runs
  sequentially afterward, consuming their answers as `evidence`.
- **Context isolation**: `AgentContext` is the only thing a specialist
  call receives — never the full conversation history or another agent's
  internal reasoning, only the fields that specialist actually needs.
- **Structured, never-raising results**: every specialist call normalizes
  into `AgentResult` inside `app.multi_agent.adapters` — any A2A failure
  or per-call timeout becomes a structured result, never an exception
  that could crash the orchestrator or corrupt an unrelated parallel
  call's result. `ResultAggregator` never fabricates a result for an
  agent that didn't complete (`status: "partial"` when some did and some
  didn't).
- **Hard boundaries, not just conventions**: a static capability registry
  (`app.multi_agent.capabilities.CAPABILITY_REGISTRY`) plus a workflow
  transition policy (`app.multi_agent.policies.ALLOWED_TRANSITIONS`) make
  `Analyst -> Research` (or any transition not explicitly listed)
  structurally impossible, backed by numeric `MAX_AGENT_DEPTH`/
  `MAX_AGENT_DELEGATIONS` ceilings checked before any call. Only
  `metadata["retryable"]` results (a genuinely transient A2A connection/
  timeout failure) are ever retried, up to `MULTI_AGENT_MAX_RETRIES` —
  never a validation/authorization/task-content failure.
- **Timeouts**: `MULTI_AGENT_AGENT_TIMEOUT_SECONDS` bounds one specialist
  call (including its own retries); `MULTI_AGENT_TIMEOUT_SECONDS` is a
  coarser whole-workflow backstop.
- **No new endpoint for an arbitrary agent/URL**: `POST /api/v1/multi-
  agent/run`'s request schema has exactly one field, `message` — there is
  no way for a caller to redirect the orchestrator anywhere but the
  already-trusted agents.

## Configuration

All configuration is environment-variable driven via `app/config.py`
(Pydantic Settings), with `.env.example` documenting every supported
variable. The same `Settings` object is the single source of truth for
both the running application and Alembic migrations (`backend/alembic/env.py`).
`GROQ_API_KEY` is stored as a `SecretStr` and is optional: the app starts
and the test suite passes without one, and only the chat endpoints fail
(with a typed 503) until it's set. Document ingestion settings
(`DOCUMENT_STORAGE_DIR`, `DOCUMENT_MAX_UPLOAD_SIZE_BYTES`,
`DOCUMENT_CHUNK_SIZE`, `DOCUMENT_CHUNK_OVERLAP`, `DOCUMENT_ALLOWED_TYPES`)
all have working defaults, so document upload works out of the box too.
Embedding settings (`EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`,
`EMBEDDING_MODEL_VERSION`, `EMBEDDING_DIMENSION`, `EMBEDDING_BATCH_SIZE`,
`EMBEDDING_DEVICE`, `EMBEDDING_NORMALIZE`, `EMBEDDING_MAX_RETRIES`) also
have working defaults; the model downloads from Hugging Face on first use
(~90MB) and is cached locally afterward — no API key needed. RAG settings
(`RAG_TOP_K`, `RAG_MAX_RESULTS`, `RAG_SIMILARITY_THRESHOLD`,
`RAG_MAX_CONTEXT_CHARS`) likewise have working defaults; the similarity
threshold default is explicitly a conservative starting point, not a
validated constant — see [ADR 007](decisions/007-rag-pipeline.md). Agent
settings (`AGENT_MAX_STEPS`, `AGENT_MAX_TOOL_CALLS`,
`AGENT_TIMEOUT_SECONDS`) likewise have working, explicitly-conservative
defaults, not production-tuned claims — see
[ADR 008](decisions/008-agent-architecture.md). MCP settings
(`MCP_CLIENT_TIMEOUT_SECONDS`, `TRUSTED_MCP_SERVERS`,
`TRUSTED_MCP_TOOLS`) and A2A settings (`A2A_CLIENT_TIMEOUT_SECONDS`,
`TRUSTED_A2A_AGENTS`, `RESEARCH_AGENT_NAME`) likewise have working
defaults that point at this project's own in-process MCP server and
localhost Research Agent — never a user-supplied or runtime-discovered
endpoint — see [ADR 009](decisions/009-mcp-a2a-architecture.md).
`DOCUMENT_AGENT_NAME`/`ANALYST_AGENT_NAME` and multi-agent settings
(`MULTI_AGENT_TIMEOUT_SECONDS`, `MULTI_AGENT_AGENT_TIMEOUT_SECONDS`,
`MULTI_AGENT_MAX_RETRIES`, `MAX_AGENT_DEPTH`, `MAX_AGENT_DELEGATIONS`)
likewise have working, explicitly-conservative defaults — see
[ADR 010](decisions/010-multi-agent-architecture.md).

## Data flow

See [data-flow.md](data-flow.md) for the readiness-check, chat/streaming
request, conversation-retrieval, document-ingestion, embedding, RAG,
agent, MCP tool-call, A2A task, and multi-agent workflow data flows.
