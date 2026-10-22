# AegisAI — Enterprise GenAI Operations Copilot

AegisAI is a production-oriented, modular-monolith backend (plus a React
UI) intended to progressively grow into an enterprise GenAI
operations platform: an LLM gateway with multi-model routing, RAG,
embeddings/vector search, LangGraph agents, tool calling, MCP, multi-agent
workflows (A2A), memory, evaluation, security/RBAC, observability/LLMOps,
async workers, and eventually containerized/Kubernetes deployment.

**Milestone 0** built the project foundation. **Milestone 1** added a
production-quality, provider-neutral LLM gateway backed by Groq.
**Milestone 2** turned that into a real conversational application:
persisted conversations/messages, prompt management, and model-role
selection, for both plain and streaming chat. **Milestone 3** adds document
intelligence and ingestion — upload, validate, store, extract, normalize,
and chunk PDF/DOCX/TXT/Markdown files. **Milestone 4** turns those chunks
into semantic vectors — a provider-neutral embedding pipeline (local
Sentence Transformers), pgvector storage with multi-model/version support,
idempotent batch embedding, and a basic similarity-search foundation.
**Milestone 5** builds the first complete retrieval-augmented generation
pipeline on top of that: query embedding, pgvector similarity search with
metadata filtering and a similarity threshold, source-bounded context
assembly with citations the LLM can reference but never invents, a
dedicated RAG prompt that treats retrieved documents as untrusted data, a
mandatory no-fabrication no-context response, and both plain and streaming
RAG chat endpoints. **Milestone 6** adds the first agentic layer: a
single, LangGraph-orchestrated agent with controlled tool calling
(knowledge-base search, a safe AST-based calculator, document metadata
lookup), an explicit tool registry with no path to arbitrary code
execution, configurable step/tool-call/timeout safety limits, and both
plain and streaming agent endpoints that never expose chain-of-thought.
**Milestone 7** adds MCP and A2A interoperability: an MCP server
re-exposing the same three internal tools over a standardized tool
boundary (discovered, not hardcoded, by the agent's MCP client), one
small remote Research Agent reached through a real A2A boundary (an
Agent Card, a task lifecycle, an explicit trusted-agent allowlist — never
called directly), and the M6 agent extended to use internal, MCP, and
A2A capabilities side by side through the same `ToolRegistry`. See
[ADR 009](docs/architecture/decisions/009-mcp-a2a-architecture.md) for
the full reasoning, including why this is one MCP server and one remote
agent, not a multi-agent platform. **Milestone 8** adds production-
oriented multi-agent orchestration on top of that same A2A boundary: a
`MultiAgentOrchestrator` that deterministically routes a request to up to
three specialized agents (Research — reused from M7; Document; Analyst —
both new), runs independent agents in parallel and a synthesis step
sequentially after them, aggregates structured results without
fabricating a failed agent's answer, and enforces explicit capability
authorization, workflow transition policy, loop/delegation limits,
per-agent and whole-workflow timeouts, and limited retries for transient
failures only. See
[ADR 010](docs/architecture/decisions/010-multi-agent-architecture.md)
for the full reasoning, including why this is exactly three agents, not
an agent swarm. **Milestone 9** builds the user-facing Copilot UI and an
enterprise operations dashboard on top of that same M8 API — originally a
Streamlit app, since migrated to a **React + TypeScript + Vite**
single-page app (`frontend/web/`) with a Copilot chat page, a Documents
page, an Operations dashboard (real document-status counts only — no
fabricated request/execution metrics), and a System Status page (live
Postgres/Redis checks plus configuration facts, clearly distinguished).
The frontend performs no orchestration of its own — every Copilot turn is
one call to `POST /api/v1/multi-agent/run`. The original Streamlit app
(`frontend/streamlit/`) is still in the repo and still has its own test
suite and Dockerfile, but is no longer the default UI — see
[ADR 011](docs/architecture/decisions/011-copilot-ui-architecture.md) for
the original reasoning and the [UI](#ui) section below for how to run
either one. **Milestone 10** containerizes that existing system (no
application redesign): a production-oriented multi-stage Docker image for
the backend and for each frontend, an extended `docker-compose.yml` (the
React frontend, the Streamlit frontend behind a `legacy-ui` profile, a
one-off migration service, and real healthchecks), and a Kubernetes
deployment foundation (`infra/kubernetes/`) — Deployments/Services/
ConfigMaps, Secret *templates* (never a real credential committed), a
migration Job, and clearly-labeled dev/staging-only Postgres/Redis
manifests, since this project has not made a cloud-provider decision.
The Kubernetes frontend manifests target the React app (nginx-unprivileged, container port 8080); its nginx
proxies `/api/` to the ClusterIP-only backend, so the browser needs no
separate backend URL (see
[`infra/kubernetes/README.md`](infra/kubernetes/README.md), which also notes
that these manifests have not been applied to a real cluster). See
[ADR 012](docs/architecture/decisions/012-deployment-architecture.md) for
the original reasoning, including exactly what was and wasn't validated
given this environment's own Docker/Kubernetes limitations.
`infra/terraform/` is an empty placeholder — no Terraform has been
written; nothing there is deployable. Agent memory beyond plain conversation
history is implemented (per-user, bounded, see [ADR 015](docs/architecture/decisions/015-agent-memory-and-rag-hardening.md))
but its migration (0008) has not been applied to any database by this work.

## Official Project Roadmap

| # | Milestone | Main skills covered |
|---|---|---|
| **M0** | Foundation & Architecture | FastAPI, PostgreSQL, Docker, config, logging, testing |
| **M1** | LLM Gateway | Groq, multiple models, streaming, retries, provider abstraction |
| **M2** | Conversational AI | Chat, prompt engineering, history, SSE streaming, token tracking |
| **M3** | Document Intelligence | PDF/DOCX/TXT, extraction, normalization, chunking, storage |
| **M4** | Embeddings | Sentence Transformers, vectors, pgvector, similarity, batching, versioning |
| **M5** | Production RAG | Retrieval, metadata filtering, top-K, context assembly, citations |
| **M6** | Agentic AI | LangGraph, tool calling, workflows, state, memory |
| **M7** | MCP + A2A Multi-Agent | MCP servers/tools, A2A communication, multi-agent orchestration |
| **M8** | GenAI UI + APIs | Streamlit/React, WebSockets/SSE, chat UI, document UI, dashboards |
| **M9** | Production / MLOps / Responsible AI | Docker, Kubernetes, CI/CD, monitoring, evaluation, security, governance |

This is the **official project milestone structure**. Use it as the source of
truth for future roadmap discussions, progress tracking, and milestone
completion reviews. The table defines each milestone's scope and the skills it
covers; it is not evidence of completion and carries no status. The
milestone numbers used elsewhere in this README, in the ADRs, and in code
comments (for example "Milestone 10" or "Milestone 12") are the project's
earlier working numbering and are not redefined by this table.

## What's implemented today

- FastAPI application with thin routing, a modular package layout, and
  structured (JSON) logging with request correlation IDs.
- `GET /health` (liveness) and `GET /health/ready` (readiness: checks
  PostgreSQL and Redis connectivity).
- Async SQLAlchemy 2.x engine/session wired to PostgreSQL, with Alembic
  migrations. The `pgvector` extension is enabled and backs the
  `chunk_embeddings` table's vector column (see Embeddings below).
- Async Redis connectivity.
- Consistent JSON error responses for unhandled exceptions and HTTP errors.
- **An LLM gateway** (`backend/app/llm/`) — a provider-neutral abstraction
  over chat completion, backed by [Groq](https://console.groq.com/) as the
  first real provider. Deterministic model routing via `ModelRole`
  (`primary` / `fast` / `safety`), sync and streaming (SSE) completion,
  typed errors, retries with backoff, and secret-free structured logging.
  See [ADR 002](docs/architecture/decisions/002-llm-gateway.md).
- **Persisted conversations** (`backend/app/domain/models/`,
  `backend/app/db/repositories/`) — `Conversation`/`Message` tables, a
  repository layer, and a `PromptBuilder` (`backend/app/prompts/`) that
  assembles `[system, history, new message]` from a versioned system
  prompt. A chat turn (user message + assistant reply) is persisted
  atomically — if the LLM call fails, nothing is saved for that turn. See
  [ADR 004](docs/architecture/decisions/004-conversation-persistence.md).
- `POST /api/v1/chat/completions` and `POST /api/v1/chat/completions/stream`
  — create or continue a conversation, streamed responses persisted once
  (accumulated), as one assistant message, after completion.
- `GET /api/v1/conversations`, `GET /api/v1/conversations/{id}` (with
  ordered messages), `DELETE /api/v1/conversations/{id}`.
- **Document ingestion** (`backend/app/documents/`, `backend/app/storage/`)
  — upload PDF/DOCX/TXT/Markdown, with layered validation (extension,
  declared MIME type, magic bytes, size), SHA-256 checksum-based duplicate
  detection, provider-neutral local file storage, format-specific text
  extraction (`pypdf`, `python-docx`), conservative normalization, and
  deterministic, page-aware chunking (`RecursiveChunker`) — all tracked
  through a `Document`/`DocumentChunk` lifecycle
  (`uploaded → processing → processed | failed`). A processing failure
  never loses the upload record or leaves partial chunks behind. See
  [ADR 005](docs/architecture/decisions/005-document-ingestion.md).
- `POST /api/v1/documents`, `GET /api/v1/documents`,
  `GET /api/v1/documents/{id}`, `GET /api/v1/documents/{id}/chunks`,
  `DELETE /api/v1/documents/{id}`.
- **Embeddings** (`backend/app/embeddings/`) — a provider-neutral
  embedding abstraction (`EmbeddingProvider`), backed by a local
  [Sentence Transformers](https://www.sbert.net/) model
  (`all-MiniLM-L6-v2`, 384-dim, CPU inference, no API key) as the only
  implementation. `EmbeddingService` batches chunks, skips work already
  done (idempotent per chunk/model/version), and persists vectors to a
  dedicated `chunk_embeddings` table (pgvector), with every row stamped
  with the exact provider/model/version/dimension that produced it — so a
  chunk can have embeddings from multiple models at once. A basic,
  pgvector-cosine-distance similarity-search foundation (not RAG — no
  retrieval pipeline, reranking, or query rewriting yet) is included and
  tested against real Postgres. See
  [ADR 006](docs/architecture/decisions/006-embedding-model.md).
- `POST /api/v1/documents/{id}/embeddings` (trigger — synchronous,
  explicit, not automatic on upload), `GET /api/v1/documents/{id}/embeddings`
  (coverage status) — neither ever returns a raw vector.
- **Retrieval-augmented generation** (`backend/app/rag/`) — `RAGService`
  orchestrates: embed the question via the existing `EmbeddingService`,
  retrieve ranked chunks via pgvector (`RetrievalService` ->
  `VectorRetrievalStrategy`, an explicit seam for a future hybrid
  strategy), filter by a configurable similarity threshold, assemble
  `[SOURCE n]`-delimited context with application-assigned citation IDs
  (never invented by the LLM), build a dedicated RAG prompt that treats
  retrieved content as untrusted data, call the LLM gateway, and attach
  structured sources to the response. A question with no sufficiently
  relevant context gets a fixed, honest "I don't have enough
  information..." response — the LLM is never called just to produce
  something. Optional `document_id` filtering, both plain and streaming
  endpoints, and conversation persistence reused from Milestone 2 (no
  duplicated logic). See
  [ADR 007](docs/architecture/decisions/007-rag-pipeline.md).
- `POST /api/v1/rag/chat` and `POST /api/v1/rag/chat/stream` — ask a
  question grounded in ingested documents, with structured source
  citations and retrieval metadata in the response. Retrieval can be
  narrowed with validated metadata filters on top of `document_id`
  (`document_types`, `filename`, `created_after`, `created_before`; they only
  ever narrow what the caller may already read). Inline `[S1]` citations are
  checked against the sources that were actually retrieved: an id that was not
  retrieved is removed from the answer (streamed and stored text too) and
  reported in `invalid_citations` (this checks that a source was *retrieved*, not
  that it *supports* the sentence it follows; it is not fact checking); each returned source says whether the
  answer `cited` it.
- **Agentic AI** (`backend/app/agents/`) — a single LangGraph-orchestrated
  agent with explicit, controlled tool calling: `AgentService` builds a
  `StateGraph` where an `agent` node asks the (extended) `LLMGateway`
  whether a registered tool is needed, and a `tools` node is the *only*
  code that executes one — the LLM never executes a tool directly. Three
  tools are registered: `search_knowledge_base` (reuses `RetrievalService`
  directly — agentic RAG, not a second retrieval path), `calculator` (an
  AST-based safe arithmetic evaluator — never `eval`/`exec`, with
  operand/exponent magnitude bounds against computational DoS), and
  `get_document_metadata` (reuses `DocumentRepository`, returns only
  already-safe fields). Every tool call's model-generated arguments are
  JSON-schema-validated before execution, and a failure becomes a
  structured result the model sees as data — never a crash or a fabricated
  success. Configurable `AGENT_MAX_STEPS`/`AGENT_MAX_TOOL_CALLS` stop a
  runaway loop with a controlled response (checked before acting, not
  after), and `AGENT_TIMEOUT_SECONDS` is a wall-clock backstop. See
  [ADR 008](docs/architecture/decisions/008-agent-architecture.md).
- **Agent memory** (`backend/app/memory/`) — short notes the agent keeps
  about one user across conversations (`save_memory` tool, notes recalled into
  the prompt as labelled untrusted data). Private to the owning user (not
  shared with the organization or administrators), bounded (length, count per
  user, writes per run, prompt size, expiry) and fully user-controlled:
  `GET/POST /api/v1/memories`, `PATCH/DELETE /api/v1/memories/{id}`,
  `DELETE /api/v1/memories` (forget everything). Settings: `AGENT_MEMORY_ENABLED`
  (`true`), `AGENT_MEMORY_MAX_ITEM_CHARS` (`500`), `AGENT_MEMORY_MAX_ITEMS_PER_USER`
  (`200`), `AGENT_MEMORY_MAX_WRITES_PER_RUN` (`3`; `0` disables the tool),
  `AGENT_MEMORY_MAX_RECALLED` (`8`), `AGENT_MEMORY_MAX_PROMPT_CHARS` (`2000`),
  `AGENT_MEMORY_TTL_DAYS` (`90`). Needs migration 0008.
- `POST /api/v1/agents/run` and `POST /api/v1/agents/run/stream` — ask the
  agent a question; the response includes the final answer, a per-tool
  usage summary, knowledge-base sources when used, and run status. The
  streaming endpoint emits only safe, structured events
  (`tool_started`/`tool_completed`/`answer_delta`/`completed`) — never the
  model's intermediate reasoning.
- **MCP interoperability** (`backend/app/mcp/`) — an MCP server
  (`mcp==2.3.0`) re-exposing the same three internal tools plus a
  `document://{document_id}` resource over the Model Context Protocol
  (thin adapters, not a second implementation). The agent's MCP client
  *discovers* tools from the server (never hardcoded), validates each
  against an explicit server/tool allowlist
  (`TRUSTED_MCP_SERVERS`/`TRUSTED_MCP_TOOLS`), and wraps each approved one
  as the same `ToolDefinition` an internal tool uses — the graph needed no
  changes to support MCP. An MCP failure degrades to "no MCP tools,"
  never a broken agent. `scripts/mcp_stdio_server.py` runs the same
  server over the standard stdio transport for an external MCP client
  (the MCP Inspector, an IDE). It has no signed-in caller, so it **refuses to
  start** unless you choose whose data it serves: `MCP_STDIO_USER_ID` +
  `MCP_STDIO_ORGANIZATION_ID` (one user's data, same ownership rules as the API) or
  `MCP_STDIO_ALLOW_UNRESTRICTED=true` (every organization's data). See
  [ADR 009](docs/architecture/decisions/009-mcp-a2a-architecture.md).
- **A2A interoperability** (`backend/app/a2a/`) — one small, specialized
  remote **Research Agent** (`a2a-sdk==1.2.1`), reached only through a
  real A2A protocol boundary: a spec-accurate Agent Card
  (`GET /.well-known/agent-card.json`), a real task lifecycle
  (`POST /api/v1/agents/research/tasks`, submitted → working →
  completed/failed), and an explicit trusted-agent allowlist
  (`TRUSTED_A2A_AGENTS`) checked before any call. The orchestrator never
  calls the Research Agent's implementation directly — only through
  `A2AClient`, registered into the same `ToolRegistry` as
  `delegate_to_research_agent`, whose own argument schema has no
  endpoint/URL field the model could redirect. One orchestrator, one
  remote agent — not a multi-agent swarm. See
  [ADR 009](docs/architecture/decisions/009-mcp-a2a-architecture.md).
- **Multi-agent orchestration** (`backend/app/multi_agent/`) — a
  `MultiAgentOrchestrator` that deterministically routes a request
  (`router.py`, regex/keyword-based, no live model call) to up to three
  specialized agents — **Research** (reused from M7), **Document** (new,
  safe metadata lookup via `DocumentRepository`), **Analyst** (new, safe
  calculator + evidence synthesis via `LLMGateway`, never reaching any
  external system of its own) — reached only through `A2AClient`, never
  by importing a specialist's implementation. Independent agents run in
  parallel (`asyncio.gather`); the Analyst runs sequentially after them
  when synthesis/calculation is needed. A static capability registry and
  workflow-transition policy make an uncontrolled delegation network
  structurally impossible (`Analyst -> Research` is not an allowed
  transition at all); `MAX_AGENT_DEPTH`/`MAX_AGENT_DELEGATIONS` enforce
  this numerically too. Every specialist call is normalized into a
  structured `AgentResult` that never raises — a partial failure is
  reported (`status: "partial"`), never fabricated — with limited retries
  for transient A2A failures only, independent per-agent and whole-
  workflow timeouts, and per-workflow correlation ids threaded through
  every `multi_agent.*`/`a2a.*` observability event. See
  [ADR 010](docs/architecture/decisions/010-multi-agent-architecture.md).
- **Docker + Docker Compose** — multi-stage, non-root production images
  for the backend (root `Dockerfile`) and for each frontend
  (`frontend/web/Dockerfile`, the default; `frontend/streamlit/Dockerfile`,
  behind a `legacy-ui` Compose profile), orchestrated by
  `docker-compose.yml` alongside PostgreSQL+pgvector and Redis, with real
  healthchecks (not just `depends_on`) and a one-off `migrate` service for
  running the existing Alembic migrations. See
  [ADR 012](docs/architecture/decisions/012-deployment-architecture.md).
- **Kubernetes deployment foundation** (`infra/kubernetes/`) — plain
  `kubectl apply`-able manifests (no Helm/operator): Deployments/Services/
  ConfigMaps for the backend and frontend, Secret *templates* (a real
  Secret is never committed), a migration Job, and clearly dev/staging-
  labeled Postgres/Redis manifests for clusters without a managed
  database/cache. Hardened security context (non-root, no privilege
  escalation, dropped capabilities) on every container. See
  [infra/kubernetes/README.md](infra/kubernetes/README.md) and
  [ADR 012](docs/architecture/decisions/012-deployment-architecture.md).
- Unit tests (fast, no live infra, API key, or embedding model download
  required) and integration tests that skip gracefully when
  Postgres/Redis/`GROQ_API_KEY`/the real embedding model aren't available
  or opted into, via pytest.
- Ruff (lint + format) and pyright (type checking), both run in CI
  (backend and frontend).
- **Copilot UI** (`frontend/web/`, React + TypeScript + Vite) — a
  single-page app with four pages: **Copilot** (`pages/CopilotPage.tsx`,
  the main chat interface over `POST /api/v1/multi-agent/run` — answer
  primary, sources/workflow status secondary and collapsed, never
  chain-of-thought), **Documents** (`pages/DocumentsPage.tsx`, upload/
  list/inspect/delete against the existing Milestone 3 document API),
  **Operations** (`pages/OperationsPage.tsx`, real document-status counts
  from `GET /api/v1/operations/summary`; no fabricated request/
  agent-execution metrics), and **System Status**
  (`pages/SystemStatusPage.tsx`, live Postgres/Redis checks plus
  configuration facts from `GET /api/v1/system/status`, clearly
  distinguished from each other), plus **Conversations**
  (`pages/ConversationsPage.tsx`: list, read, delete with confirmation, and
  continue a saved conversation in the Copilot via `/?conversation=<id>`) and
  **Memory** (`pages/MemoryPage.tsx`: list, add, edit, delete and "forget
  everything" for the notes the agent keeps, against `/api/v1/memories`). The
  Copilot's mode selector offers a streamed document answer, plain chat, an
  agent (each tool it uses is shown as it runs) and the multi-agent workflow.
  `src/api/` is the one place every
  backend call is made, normalizing every failure into a single
  `BackendError`. The original Streamlit app (`frontend/streamlit/`,
  same four pages, same API contracts) is still in the repo, still
  tested, and still buildable, but is no longer the default UI — see
  [ADR 011](docs/architecture/decisions/011-copilot-ui-architecture.md)
  for the original design reasoning (still accurate for both UIs' shared
  backend-contract boundary) and the [UI](#ui) section below for how to
  run either one.
- **Authentication** (Milestone 12, Phase 1a, `backend/app/auth/` and
  `backend/app/core/security.py`) — the API verifies OIDC bearer tokens
  (signature, issuer, audience, expiry, required claims) against the provider's
  public keys and maps them to an internal user, organization and role stored in
  the database. Every `/api/v1` route is protected by default; see
  [Authentication setup](#authentication-setup) for configuration and for what
  is still missing (a user admin API) and for the data-isolation rules. Sign-in is in the React
  app (`frontend/web/src/auth/`) and accounts are linked with
  `scripts/provision_identity.py`.
- **Evaluation harness** (Milestone 11, `backend/app/evaluation/`,
  `scripts/evaluate.py`) — runs a version-controlled dataset through the real
  retrieval pipeline and reports recall, context inclusion, operational failure
  and no-answer abstention rates, compared against a stored baseline. It makes
  no LLM call, so `answer_correctness` and `citation_precision` are reported as
  skipped. Details in `backend/tests/evaluation/README.md`.

## Stack

Python 3.12+ · uv · FastAPI · Pydantic v2 + pydantic-settings · SQLAlchemy
2.x (async) · PostgreSQL + pgvector · Alembic · Redis · Groq SDK · pypdf ·
python-docx · Sentence Transformers · LangGraph · MCP SDK · a2a-sdk ·
httpx · pytest · Ruff · pyright · Docker/Docker Compose · React ·
TypeScript · Vite · Vitest · nginx · (legacy UI: Streamlit)

## Architecture

A modular monolith — one deployable FastAPI application with hard internal
module boundaries, so capabilities can be added incrementally without a
microservices rewrite. See
[docs/architecture/decisions/001-modular-monolith.md](docs/architecture/decisions/001-modular-monolith.md)
for the reasoning.

```
backend/app/
  api/            thin HTTP routes + request/response schemas
  core/           logging, middleware, exception handling (security/RBAC reserved)
  domain/         ORM models (Conversation, Message, Document, DocumentChunk,
                  ChunkEmbedding) + enums (MessageRole, DocumentStatus, DocumentType)
  services/       business logic orchestration
    chat_service.py          conversation lifecycle, prompt, LLM call, persistence
    conversation_service.py  list/get/delete (thin, no LLM concerns)
    document_service.py      upload/validate/store/extract/normalize/chunk/persist
  prompts/        prompt management — implemented (see ADR 004)
    templates.py     versioned PromptTemplate(s), e.g. the AegisAI system prompt
    builder.py       PromptBuilder: [system, history, new message]
  llm/            LLM gateway — implemented, Groq-backed (see ADR 002)
    base.py         provider-neutral LLMProvider interface
    gateway.py       LLMGateway: routing, retries, standardized responses
    schemas.py       ModelRole, ChatMessage, CompletionResponse, StreamChunk,
                     ToolSpec/ToolCall (tool calling, Milestone 6)
    exceptions.py    typed LLMError hierarchy
    providers/groq.py  the only module allowed to import the `groq` SDK
  documents/      document ingestion — implemented (see ADR 005)
    validation.py    extension/MIME/size/magic-byte checks, safe filenames
    normalization.py conservative whitespace/encoding cleanup
    chunk_ids.py     deterministic (UUID5) chunk identifiers
    extractors/      one module per DocumentType: pdf.py (pypdf), docx.py
                     (python-docx), text.py / markdown.py (no dependency)
    chunking/        RecursiveChunker: character-based, per-page, overlap-aware
  storage/        provider-neutral file storage — implemented (see ADR 005)
    base.py         DocumentStorage interface
    local.py        LocalFileStorage — the only implementation so far
  embeddings/     text embedding — implemented (see ADR 006)
    base.py         provider-neutral EmbeddingProvider interface
    service.py      EmbeddingService: batching, idempotency, persistence,
                     embed_query (Milestone 5)
    schemas.py       EmbeddingJobResult, EmbeddingStatus, SimilarityMatch
    exceptions.py    typed EmbeddingError hierarchy
    providers/local.py  the only module allowed to import sentence_transformers
  rag/            retrieval-augmented generation — implemented (see ADR 007)
    service.py       RAGService: the only layer combining retrieval + generation
    schemas.py       RAGAnswer, RAGSource, RAGRetrievalMetadata
    exceptions.py    RAGError (minimal — most failures reuse existing types)
    retrieval/       RetrievalService, RetrievalStrategy/VectorRetrievalStrategy,
                     RetrievalRepository (RAG-specific pgvector query)
    context/          ContextAssembler: source-bounded context + citation IDs
    prompts/          AEGIS_RAG_SYSTEM_PROMPT, RAGPromptBuilder
  agents/         single-agent LangGraph orchestration — implemented (see ADR 008)
    service.py       AgentService: build state, run the graph, persist, extract results
    graph.py         the StateGraph: agent node -> should_continue -> tools | END
    schemas.py       AgentState, AgentRunResult, ToolUsageSummary, AgentSource
    messages.py      LangChain-message <-> ChatMessage boundary translation
    prompts.py       AEGIS_AGENT_SYSTEM_PROMPT
    exceptions.py    AgentError, AgentTimeoutError
    tools/           ToolRegistry/ToolDefinition + calculator, get_document_metadata,
                     search_knowledge_base, research_delegation (A2A, Milestone 7)
                     — the only path from a tool name to code
  multi_agent/    multi-agent orchestration — implemented (see ADR 010)
    orchestrator.py  MultiAgentOrchestrator: route -> authorize -> tier-1
                     (parallel) -> Analyst (sequential) -> aggregate
    router.py        route(): deterministic regex/keyword capability routing
    capabilities.py  CAPABILITY_REGISTRY: agent -> capabilities/Card path
    policies.py      ALLOWED_TRANSITIONS, retryable-exception allowlist
    models.py        AgentContext, AgentResult, WorkflowResult
    adapters.py      per-agent A2A adapters -> normalized AgentResult
    aggregation.py   ResultAggregator: combine results, never fabricate
  tools/          reserved for a possible future non-agent-specific tool need
                  (Milestone 6's own tool calling lives in agents/tools/ above)
  mcp/            Model Context Protocol — implemented (see ADR 009)
    server.py       build_mcp_server: thin MCP adapters over the same
                     ToolDefinition.executor the internal agent uses
    client.py       discover_mcp_tool_definitions: discovery + allowlist +
                     wraps each approved tool as a ToolDefinition
    exceptions.py    typed MCPError hierarchy
  a2a/            Agent2Agent — implemented (see ADR 009/010)
    agent_card.py    build_research_agent_card/document_agent_card/
                     analyst_agent_card (real a2a.types AgentCard)
    research_agent.py ResearchAgentService: retrieve + synthesize (reuses
                     RetrievalService/LLMGateway directly, not RAGService)
    document_agent.py DocumentAgentService: safe metadata lookup, no LLM
                     (Milestone 8)
    analyst_agent.py AnalystAgentService: safe calculator + evidence
                     synthesis (Milestone 8)
    tasks.py         build_generic_task/build_task/task_to_dict (real
                     a2a.types Task/Artifact)
    client.py        A2AClient: the only way the orchestrator reaches any
                     specialist — trusted-agent allowlist, Card
                     validation, task submission/parsing (submit_task is
                     the generic form Milestone 8 uses for all 3 agents)
    exceptions.py    typed A2AError hierarchy
  memory/         agent memory (per-user notes, bounded; ADR 015)
  auth/           authentication (M12 Phase 1a): tokens.py verifies OIDC bearer
                   tokens, jwks.py looks up signing keys (cache + circuit breaker),
                   service.py maps a verified token to an internal Principal
  evaluation/     evaluation harness - implemented (M11): dataset.py, metrics.py,
                   runner.py, report.py, baseline.py; CLI in scripts/evaluate.py
  observability/  LLMOps observability (reserved)
  workers/        async workers (reserved)
  db/             SQLAlchemy session + Redis client management
    repositories/   ConversationRepository, MessageRepository,
                     DocumentRepository, DocumentChunkRepository,
                     ChunkEmbeddingRepository — the only code that issues
                     SQLAlchemy queries
```

Routes never contain business logic or database queries; they delegate to
`services/`, `rag/`, or `agents/`, which depend on `prompts/`, `llm/`,
`documents/`, `storage/`, `embeddings/`, and `db/`. The LLM call chain is
strictly `api -> service -> LLMGateway -> LLMProvider interface ->
GroqProvider -> groq SDK`; the embedding call chain is strictly
`api -> EmbeddingService -> EmbeddingProvider interface ->
LocalEmbeddingProvider -> sentence_transformers`; the RAG call chain is
`api -> RAGService -> RetrievalService -> RetrievalStrategy ->
EmbeddingService/RetrievalRepository`; the agent call chain is
`api -> AgentService -> StateGraph -> ToolRegistry -> (calculator |
DocumentRepository | RetrievalService | mcp.client | a2a.client)`, with
every LLM call (plain or tool-calling) going through the same
`LLMGateway` — `agents/` never imports a provider SDK or
`sentence_transformers` directly, and the tool registry is the only path
from a tool name to executable code, whether that tool is internal,
MCP-discovered, or the A2A delegation tool. The MCP call chain is
`agents/tools/registry.py -> mcp.client.discover_mcp_tool_definitions ->
mcp.client.Client -> mcp.server.build_mcp_server -> (the same
ToolDefinition.executor an internal tool uses)` — never a second
implementation of a tool's logic. The A2A call chain is
`agents/tools/research_delegation.py -> a2a.client.A2AClient -> HTTP ->
api/v1/research_agent.py -> a2a.research_agent.ResearchAgentService ->
RetrievalService/LLMGateway` — the orchestrator never imports
`ResearchAgentService` directly, only `A2AClient`. The multi-agent call
chain is `api/v1/multi_agent.py -> multi_agent.orchestrator
.MultiAgentOrchestrator -> multi_agent.router.route (deterministic) ->
multi_agent.adapters.call_{research,document,analyst}_agent ->
a2a.client.A2AClient.submit_task -> HTTP -> api/v1/{research,document,
analyst}_agent.py -> each agent's own service -> multi_agent.aggregation
.ResultAggregator` — `multi_agent/` never imports a specialist's service
class directly, and contains no research/document/calculation logic of
its own.
Nothing above `providers/groq.py` ever imports `groq`; nothing outside
`documents/extractors/` imports `pypdf`/`docx`; nothing outside
`embeddings/providers/local.py` imports `sentence_transformers`; nothing
outside `storage/` touches the filesystem; nothing outside
`db/repositories/` (and, for the RAG-specific retrieval query,
`rag/retrieval/repository.py`) builds a SQLAlchemy query; nothing outside
`agents/tools/` calls a registered tool's executor. See
[docs/architecture/system-design.md](docs/architecture/system-design.md)
for the full picture and
[docs/architecture/data-flow.md](docs/architecture/data-flow.md) for the
readiness-check, chat/streaming, conversation-retrieval,
document-ingestion, embedding, RAG, and agent data flows.

The frontend is a separate, thin client — not part of the backend's own
module boundaries above. **`frontend/web/`** (React + TypeScript + Vite)
is the default UI:

```
frontend/web/
  src/
    App.tsx             route table (Copilot/Documents/Operations/System Status)
    config.ts            resolves the API base URL (runtime config.js ->
                          build-time VITE_API_BASE_URL -> localhost:8000)
    components/
      Shell/              Sidebar/Topbar/AppShell — the app's layout
      Chat/               composer, message bubbles, workflow-details panel
      Documents/          uploader (real upload progress), status pills
    pages/
      CopilotPage.tsx     one call to POST /api/v1/multi-agent/run, no
                          orchestration of its own
      DocumentsPage.tsx    upload/list/inspect/delete (existing M3 API)
      OperationsPage.tsx    real document-status counts only
      SystemStatusPage.tsx  live Postgres/Redis checks + configuration facts
    api/
      client.ts            the one function that calls fetch; BackendError
      copilot.ts            POST /api/v1/multi-agent/run
      documents.ts           the existing document endpoints
      operations.ts          GET /api/v1/operations/summary
      system.ts              GET /api/v1/system/status
      health.ts               GET /health (liveness)
  Dockerfile              multi-stage: npm build -> static nginx image
  docker-entrypoint.sh    validates + writes config.js from API_BASE_URL at container start
  nginx.conf.template     static app + /api/ proxy to BACKEND_UPSTREAM (empty API_BASE_URL = same origin)
```

Vitest + Testing Library tests live alongside the files they cover
(`*.test.tsx`/`*.test.ts`), mocking `fetch` — no real backend required.

**`frontend/streamlit/`** is the original Streamlit app — same four
pages, same backend API contracts, still tested and buildable, but no
longer the default (see the [UI](#ui) section below for how to run it).

See [ADR 011](docs/architecture/decisions/011-copilot-ui-architecture.md)
for the original frontend architecture reasoning (still accurate for
both UIs' shared backend-contract boundary), including why the frontend
performs no orchestration of its own and why the Operations dashboard
omits request/agent-execution metrics.

## Quickstart

```bash
uv sync --all-groups
cp .env.example .env          # optionally set GROQ_API_KEY for real LLM calls
docker compose up -d postgres redis
cd backend && uv run alembic upgrade head && cd ..
cd backend && uv run uvicorn app.main:app --reload
```

Then visit http://localhost:8000/health, http://localhost:8000/health/ready,
and http://localhost:8000/docs (served only because `.env.example` sets
`ENVIRONMENT=local`). With the `AUTH_*` variables blank, every protected route
answers `503`; see [Authentication setup](#authentication-setup) below.

## Authentication setup

The API is an OIDC **resource server** (Milestone 12, Phase 1a). Every
`/api/v1` route requires an `Authorization: Bearer <access token>` issued by
your identity provider, except the three agent-card routes
(`/api/v1/agents/*/card`). `/health`, `/health/ready` and
`/.well-known/agent-card.json` are also public. The API stores no passwords or
signing secrets; it only fetches the provider's public keys.

Three settings tell it which provider to trust (public identifiers, not
secrets; see `.env.example` and `backend/app/config.py`):

| Variable | Meaning |
|---|---|
| `AUTH_ISSUER` | Must equal the token's `iss` claim **exactly** |
| `AUTH_AUDIENCE` | The API audience that must appear in the token's `aud` |
| `AUTH_JWKS_URL` | The provider's key-set URL, fetched **by the backend** (it may differ from the issuer's host) |

Optional tuning (defaults in `.env.example`): `AUTH_ALLOWED_ALGORITHMS`
(asymmetric algorithms only, default `["RS256"]`), `AUTH_LEEWAY_SECONDS`
(0-60), `AUTH_JWKS_CACHE_SECONDS`, `AUTH_JWKS_MIN_REFRESH_SECONDS`,
`AUTH_JWKS_TIMEOUT_SECONDS`, `AUTH_JWKS_FAILURE_COOLDOWN_SECONDS` (0-60).

**What `ENVIRONMENT` changes**

| | `ENVIRONMENT=local` (the default, and in `.env.example`) | Any other value |
|---|---|---|
| Used by | Running the API directly with `uvicorn` | Compose sets `docker`; the Kubernetes ConfigMap sets `kubernetes`; the backend image defaults to `production` |
| `AUTH_*` unset | The API starts, but every protected route answers `503` | The API **refuses to start** and names the missing variables |
| URLs | `http` allowed | `AUTH_ISSUER` and `AUTH_JWKS_URL` must be `https` (loopback hosts excepted) |
| `DEBUG` | May be `true` | Must be `false` |
| `/docs`, `/openapi.json` | Served | Not served (404) |
| `TRUSTED_A2A_AGENTS` | Not checked | Each entry must be `https` (loopback excepted) |

**Docker Compose: configure before starting the stack**

The Compose backend runs with `ENVIRONMENT=docker`, so it does not start until
all three variables are set. Compose reads them from the shell environment or
from the repo-root `.env` file (which is git-ignored); the containers never read
`.env` themselves.

1. Put your identity provider's values in `.env` (placeholders shown; use your
   provider's real URLs):

   ```bash
   AUTH_ISSUER=https://idp.example.com/realms/aegis
   AUTH_AUDIENCE=aegisai-api
   AUTH_JWKS_URL=https://idp.example.com/realms/aegis/protocol/openid-connect/certs
   ```

2. `make docker-up`, then `make docker-migrate` (migrations do not need the
   `AUTH_*` values).
3. If the backend container exits, run `docker compose logs backend`. A missing
   value is reported as `Authentication is not configured for
   ENVIRONMENT='docker': set ...`.

Because the key set is fetched from **inside** the backend container,
`localhost` there means the container itself, and plain `http` is accepted only
for loopback hosts. A provider running on your host machine therefore cannot be
used over `http`; use an `https` URL that the container can reach.

**Kubernetes:** the same three keys are in `infra/kubernetes/backend-configmap.yaml`,
empty on purpose. The API will not start until you set them.

**Signing in (React UI)**

The React app signs people in itself: the OpenID Connect authorization-code flow
with PKCE. It is a public client, so it holds no secret, and tokens stay in the
browser tab's `sessionStorage`. Tell it which provider to use (public values, not
secrets):

| Variable | Meaning |
|---|---|
| `OIDC_AUTHORITY` | The provider's issuer URL exactly as the **browser** reaches it (normally the same value as `AUTH_ISSUER`) |
| `OIDC_CLIENT_ID` | The id of the public client registered for this app (default `aegisai-web`) |

Set them in `.env` next to the `AUTH_*` values (Compose passes them to the
frontend container), in `infra/kubernetes/frontend-configmap.yaml`, or as
`VITE_OIDC_AUTHORITY` / `VITE_OIDC_CLIENT_ID` for `npm run dev`. With
`OIDC_AUTHORITY` empty the app shows "Sign-in is not configured".

In your identity provider, register that client as:

- **public** (no client secret), authorization-code flow only, **PKCE required**
  (`S256`);
- valid redirect URI **and** post-logout redirect URI: the app's origin with a
  trailing slash (`http://localhost:3000/` for Compose, `http://localhost:5173/`
  for `npm run dev`);
- the app's origin allowed as a web origin (the browser fetches the provider's
  discovery document and keys itself);
- access tokens that carry the API audience (`AUTH_AUDIENCE`) in `aud`. With
  Keycloak this normally means an audience mapper on the client. The backend
  answers `401` to a token without it.

**Creating the first user**

Signing in is not enough: the backend must also know the person. Someone who
signs in without an account sees "Your account is not set up yet", with the
**subject** and **issuer** an operator needs. The operator links them:

```bash
# preview (changes nothing), then write
uv run python scripts/provision_identity.py --organization "Acme" \
    --email admin@example.com --subject <subject shown on screen> --role admin --dry-run
uv run python scripts/provision_identity.py --organization "Acme" \
    --email admin@example.com --subject <subject shown on screen> --role admin --yes
```

It writes to the database named by `DATABASE_URL` (the default matches the Compose
Postgres on port 5433) after migrations have run (`make docker-migrate`). It prints
the target (host, port, database; never the password) and will not write without
`--yes`. `--issuer` defaults to `AUTH_ISSUER` and must equal the token's `iss`
exactly. It only adds rows and is safe to repeat; it refuses, rather than changes,
a disabled user or organization, a different role or organization for an existing
email, or an identity already linked to someone else.

**Data isolation and roles**

Conversations and documents have an owner (see
[ADR 013](docs/architecture/decisions/013-data-isolation.md)):

- A **conversation** (and its messages) is private to its owner. Nobody else can read, continue
  or delete it, administrators included.
- A **document** (and its chunks and embeddings) is private to its owner by default. The owner can
  share it with their organization (`PATCH /api/v1/documents/{id}/visibility` with
  `{"visibility": "organization"}`) and take it back. Members of the organization can then read
  and search it, but only its owner, or an **administrator** of the organization, can delete or
  re-share it. An administrator can remove a member's private document without being able to read it.
- Nothing is ever visible across organizations, and a resource you may not see is a `404`, the
  same as one that does not exist.
- `GET /api/v1/system/status` (infrastructure facts) is for administrators only.
- `GET /api/v1/operations/summary` counts documents by status: a member's counts cover what they
  can read; an administrator's cover their whole organization (aggregate numbers only, never titles,
  owners or content).

*Upgrading a database that already holds data* (created before ownership existed). Back it up
first. Then, in this order:

```bash
# 1. the user who should receive the existing data must already be provisioned (above)
docker compose run --rm migrate alembic upgrade 0006   # adds the owner columns; changes no row
uv run python scripts/assign_legacy_data.py --email you@example.com --organization "Acme" --dry-run
uv run python scripts/assign_legacy_data.py --email you@example.com --organization "Acme" --yes
docker compose run --rm migrate alembic upgrade head   # makes the owner required
```

Until step 3 the old conversations and documents are invisible to everyone (not exposed).
`alembic upgrade head` on a database that still has unassigned rows stops safely at revision 0006
with a message saying how many; nothing is changed. A fresh database needs only `upgrade head`.
`assign_legacy_data.py` never guesses: you must name both the user (`--email`) and the organization
(`--organization`), both must exist, be active and agree, or nothing changes. It only fills in a
*missing* owner and accepts `--expect-conversations N` / `--expect-documents N` to assert what it
will assign. It has not been run against any database.

**Rate limits and audit events**

Expensive operations are limited per signed-in user in a sliding window (see
[ADR 014](docs/architecture/decisions/014-rate-limits-and-audit-events.md)): language-model requests
(chat, RAG, agents, multi-agent, and the Research/Analyst agent tasks), document uploads, and
embedding jobs. Over the limit a request gets `429` with `Retry-After` and a generic message; it
never reaches the service. If the limiter itself cannot enforce, the request gets `503` instead of
being let through.

| Setting | Default | Meaning |
|---|---|---|
| `RATE_LIMIT_ENABLED` | `true` | `false` switches every limit off |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | length of the sliding window (1 to 86400) |
| `RATE_LIMIT_LLM_REQUESTS` | `30` | model requests per user per window; `0` = unlimited |
| `RATE_LIMIT_DOCUMENT_UPLOADS` | `10` | uploads per user per window; `0` = unlimited |
| `RATE_LIMIT_EMBEDDING_JOBS` | `5` | embedding jobs per user per window; `0` = unlimited |
| `RATE_LIMIT_MAX_TRACKED_KEYS` | `100000` | cap on in-memory counters (see ADR 014) |

Application metrics are opt-in (see [docs/operations/observability.md](docs/operations/observability.md)):

| Setting | Default | Meaning |
|---|---|---|
| `METRICS_ENABLED` | `false` | `true` mounts `GET /metrics` and starts recording; otherwise nothing is recorded and the route is a 404 |
| `METRICS_TOKEN` | unset | bearer token a scraper must send; required outside local development, at least 16 characters, no leading/trailing whitespace (a trailing newline from a secret file is rejected); keep it out of version control |
| `MAX_REQUEST_BODY_BYTES` | `16777216` | largest non-upload request body; larger gets 413 before parsing |
| `A2A_MAX_RESPONSE_BYTES` / `A2A_TOTAL_TIMEOUT_SECONDS` | `1048576` / `30` | cap on one agent response, and a deadline for the whole exchange (on top of the per-phase timeout) |
| `LLM_STREAM_TOTAL_TIMEOUT_SECONDS` | `300` | deadline for a whole model stream |
| `EMBEDDING_DIMENSION` | `384` | must equal the vector column; the API refuses to start otherwise |
| `CHAT_HISTORY_MAX_MESSAGES` / `CHAT_HISTORY_MAX_CHARS` | `40` / `24000` | conversation history replayed to the model per turn: the newest whole messages within both bounds ([ADR 016](docs/architecture/decisions/016-input-bounds-and-history-limits.md)) |
| `DOCUMENT_MAX_UNCOMPRESSED_BYTES` / `DOCUMENT_MAX_PDF_PAGES` / `DOCUMENT_MAX_EXTRACTED_CHARS` | `67108864` / `2000` / `20000000` | what an uploaded file may expand to; exceeding one fails that document with a clear message |

The defaults are starting points to review, not recommendations. **Counts are kept in memory per
process**: with several workers or replicas each keeps its own, so the effective limit is
(limit x processes). Nothing is shared through Redis. A multi-agent request uses several model
admissions (the request itself plus each model-backed agent it calls with your own token).

Security-sensitive actions (document upload, sharing, embedding request and deletion, conversation
deletion, and every rate-limit refusal) write one structured `audit` log line naming the user,
organization, role, resource id and outcome (`success`, `not_found`, `limited`), and never any
content, file name, e-mail address or token. These are log lines, not a tamper-evident store.

For what has and has not been verified, the per-milestone evidence, known security limitations,
the migration order and the remaining work, see
[docs/operations/production-readiness.md](docs/operations/production-readiness.md).

**What is not available yet**

- **The legacy Streamlit app has no sign-in**, so it cannot call this backend.
- **No self-service sign-up or invitations, and no admin API for users.**
  Accounts are created with the command above.
- **Data isolation has not been run against a real database yet.** It is covered by offline tests
  (the access rules executed as SQL, every repository query, the migrations' rendered SQL, the
  backfill command, the HTTP error behavior). The database-backed suites that exercise it end to
  end (`backend/tests/integration/test_data_isolation.py`, and
  `test_ownership_migration.py` with `RUN_MIGRATION_ROUNDTRIP=1`) are written but have not been
  executed. There is no API to manage users or roles, and `admin` has no capability beyond
  deleting or re-sharing documents in its organization and viewing system status.
- **Silent renewal needs refresh tokens** from your provider; without them a user
  signs in again when the access token expires.
- **Verification status.** The sign-in flow is covered by unit tests with a mocked
  provider. It has not yet been run against a real identity provider in a browser,
  so expect to adjust the provider-side client settings above.

Responses: `401` missing, invalid or expired token; `403` valid token but the
identity is unlinked or disabled; `503` authentication not configured, key set
unreachable, or the identity lookup failed.

## UI

**React (default).** In a second terminal, against the backend above:

```bash
cd frontend/web && npm install && npm run dev
```

Then visit http://localhost:5173 — Vite's dev server, with
`VITE_API_BASE_URL` (default `http://localhost:8000`) pointing it at the
backend. The Copilot, Conversations, Documents, Memory, Operations, and System Status
pages are all in the left sidebar. The Copilot streams its answer over Server-Sent Events
(`POST /api/v1/rag/chat/stream`, read with `fetch` so the bearer token can be sent): text
appears as it is written, with a Stop button, sources when it finishes, and an explicit
"Try again" after a failure (there is no automatic reconnect: a retry would repeat a request
that costs model tokens). The previous multi-agent workflow remains selectable. Signing in needs `VITE_OIDC_AUTHORITY` and
`VITE_OIDC_CLIENT_ID` (see [Authentication setup](#authentication-setup)).

**Streamlit (legacy).** Not supported against an authentication-enabled backend
(it has no sign-in flow, so it cannot call a backend that requires bearer tokens).
Instead of the above:

```bash
cd frontend/streamlit && uv run --group frontend streamlit run app.py
```

Then visit http://localhost:8501. `AEGIS_BACKEND_URL` (default
`http://localhost:8000`) and `AEGIS_BACKEND_TIMEOUT_SECONDS` (default
`30.0`) point it at a backend running on a different host/port.

### Run the whole stack in containers

Alternatively, run everything — backend, the React frontend, Postgres,
Redis — in Docker:

```bash
cp .env.example .env            # optionally set GROQ_API_KEY
# Set AUTH_ISSUER, AUTH_AUDIENCE and AUTH_JWKS_URL in .env first: the Compose
# backend refuses to start without them (see "Authentication setup" above).
make docker-up                  # builds + starts backend, frontend, postgres, redis
make docker-migrate             # runs the existing Alembic migrations once
```

Then check http://localhost:8000/health (backend; the interactive `/docs`
page is served only when `ENVIRONMENT=local`, so it is off in Compose) and open
http://localhost:3000 (Copilot UI; it asks you to sign in with the identity
provider from `OIDC_AUTHORITY`, and `scripts/provision_identity.py` links your
account). `make docker-logs` tails every
service's logs; `make docker-down` stops the stack. To also run the
legacy Streamlit UI in Docker instead/alongside (port 8501):
`docker compose --profile legacy-ui up -d frontend-streamlit`. See
[ADR 012](docs/architecture/decisions/012-deployment-architecture.md)
for the full container/Kubernetes architecture, and
[infra/kubernetes/README.md](infra/kubernetes/README.md) for deploying
to a Kubernetes cluster. There the frontend's nginx proxies `/api/` and
`/health` to the backend, so the backend needs no externally reachable URL
(structurally validated only; never applied to a real cluster).

To run a real Groq request locally, set `GROQ_API_KEY` in `.env` (get one at
https://console.groq.com/keys), then:

```bash
# Starts a new conversation (omit conversation_id)
curl -X POST http://localhost:8000/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"message": "Say hello in five words.", "model_role": "fast"}'

# Continue it (reuse the conversation_id from the response above)
curl -X POST http://localhost:8000/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"conversation_id": "<id-from-above>", "message": "Now say it in French.", "model_role": "fast"}'

curl -N -X POST http://localhost:8000/api/v1/chat/completions/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "Count from 1 to 5.", "model_role": "fast"}'

# Review what got persisted
curl http://localhost:8000/api/v1/conversations
curl http://localhost:8000/api/v1/conversations/<id>
```

Document upload doesn't need `GROQ_API_KEY` at all:

```bash
curl -X POST http://localhost:8000/api/v1/documents -F "file=@/path/to/a.pdf"

curl http://localhost:8000/api/v1/documents
curl http://localhost:8000/api/v1/documents/<id>
curl http://localhost:8000/api/v1/documents/<id>/chunks
```

Once a document's status is `processed`, generate embeddings for it (the
first call downloads and caches the ~90MB model, so it's slower than
subsequent calls):

```bash
curl -X POST http://localhost:8000/api/v1/documents/<id>/embeddings
curl http://localhost:8000/api/v1/documents/<id>/embeddings   # coverage status
```

With embeddings in place, ask a question grounded in that document (needs
`GROQ_API_KEY` for a real generated answer — retrieval itself doesn't):

```bash
curl -X POST http://localhost:8000/api/v1/rag/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What does this document say about travel expenses?"}'

# Restrict retrieval to one document, and stream the answer
curl -N -X POST http://localhost:8000/api/v1/rag/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "Summarize the key points.", "document_id": "<id>"}'
```

A question with no relevant ingested content returns `has_context: false`
and a fixed "I don't have enough information..." answer — the LLM is never
called in that case, so it works even without `GROQ_API_KEY` set for that
specific response.

Ask the agent a question — it decides for itself whether to search the
knowledge base, use the calculator, look up document metadata, or just
answer directly (needs `GROQ_API_KEY`):

```bash
curl -X POST http://localhost:8000/api/v1/agents/run \
  -H "Content-Type: application/json" \
  -d '{"message": "What is 250 * 0.18, and what does our travel policy say about hotel expenses?"}'

# Stream safe progress events (tool_started/tool_completed/answer_delta/completed)
curl -N -X POST http://localhost:8000/api/v1/agents/run/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "What is 12 * 7?"}'
```

The response includes the final answer, a per-tool usage summary, and any
knowledge-base sources consulted — never raw graph state or a tool's raw
arguments/result payload.

Ask the agent something that benefits from the Research Agent (it decides
whether to call `delegate_to_research_agent`, an MCP tool, or an internal
one):

```bash
curl -X POST http://localhost:8000/api/v1/agents/run \
  -H "Content-Type: application/json" \
  -d '{"message": "Research what our documents say about the refund policy."}'
```

Inspect the Research Agent's own A2A boundary directly:

```bash
curl http://localhost:8000/.well-known/agent-card.json

curl -X POST http://localhost:8000/api/v1/agents/research/tasks \
  -H "Content-Type: application/json" \
  -d '{"question": "What is our refund policy?"}'
```

Ask the full multi-agent orchestrator a question — it decides which of
the three specialized agents (if any) to delegate to:

```bash
curl -X POST http://localhost:8000/api/v1/multi-agent/run \
  -H "Content-Type: application/json" \
  -d '{"message": "Compare the travel reimbursement policy with document <uuid>."}'
```

The response includes the final answer, workflow/correlation ids, which
agents were used (and their status — a partial failure is reported, never
hidden), flattened sources, and aggregate token usage.

Without `GROQ_API_KEY` set, the app still starts and `/docs` still lists
every endpoint — chat, grounded-RAG, and agent requests respond with a
`503 llm_unavailable` instead (and persist nothing, per the atomic-turn
design — see
[ADR 004](docs/architecture/decisions/004-conversation-persistence.md)).
The conversation endpoints work regardless, since they don't call Groq.

Full setup instructions: [docs/development/setup.md](docs/development/setup.md).

## Running checks

```bash
uv run pytest       # unit + integration; integration tests skip without live
                     # Postgres/Redis, the Groq live tests (chat + agent
                     # tool selection) skip without a real GROQ_API_KEY, and
                     # the real-embedding-model tests (embeddings + RAG
                     # pipeline + Recall@K) skip unless explicitly opted
                     # into — none are required to pass
uv run ruff check .
uv run ruff format .
uv run pyright
```

Run the opt-in real Groq tests explicitly with (covers plain chat and the
agent's real tool-selection behavior):

```bash
GROQ_API_KEY=sk-... uv run pytest -m llm_integration -v
```

Run the opt-in real-embedding-model tests explicitly with (downloads/loads
the real Sentence Transformers model; covers the Milestone 4 embedding
test, the full RAG pipeline test, and the Recall@K evaluation):

```bash
RUN_EMBEDDING_INTEGRATION=1 uv run pytest -m embedding_integration -v
```

Run the opt-in real MCP stdio transport test explicitly with (spawns
`scripts/mcp_stdio_server.py` as a real subprocess against live Postgres):

```bash
RUN_MCP_STDIO_INTEGRATION=1 uv run pytest -m mcp_integration -v
```

Run the opt-in real A2A HTTP transport tests explicitly with (a real
`uvicorn` server on a real socket; add `GROQ_API_KEY` for the tier that
also makes a real Groq call through the full A2A stack):

```bash
RUN_A2A_LIVE_INTEGRATION=1 uv run pytest -m a2a_integration -v
RUN_A2A_LIVE_INTEGRATION=1 GROQ_API_KEY=sk-... uv run pytest -m a2a_integration -v
```

Run the opt-in real multi-agent workflow tests explicitly with (the same
real-socket pattern, through the full Research + Document + Analyst
orchestration; add `GROQ_API_KEY` for the tier that also makes a real
Groq call):

```bash
RUN_MULTI_AGENT_LIVE_INTEGRATION=1 uv run pytest -m multi_agent_integration -v
RUN_MULTI_AGENT_LIVE_INTEGRATION=1 GROQ_API_KEY=sk-... \
    uv run pytest -m multi_agent_integration -v
```

Run the React frontend's checks (no real backend/network — every `fetch`
call is mocked in its tests):

```bash
cd frontend/web && npm ci && npm run lint && npm run build && npm run test
```

Run the legacy Streamlit frontend's test suite (no real backend/network —
every backend call is mocked; `--group frontend` is needed since
`streamlit`/its test runner aren't in the default dependency set):

```bash
uv run --group frontend pytest frontend/streamlit/tests -v
```

Validate the deployment configuration itself (no Docker daemon or
Kubernetes cluster required for either of these — see
[ADR 012](docs/architecture/decisions/012-deployment-architecture.md),
"Testing"):

```bash
docker compose config               # or: make docker-config
uv run python infra/kubernetes/validate_manifests.py   # or: make k8s-validate
```

Or `make check` (lint + typecheck + test + test-frontend). See the
[Makefile](Makefile) for all available targets (`run`, `run-frontend`,
`docker-build`, `docker-up`, `docker-down`, `docker-migrate`,
`docker-shell`, `k8s-validate`, `migrate`, ...).

## Implementation history and remaining work

> This section records what the project's earlier working milestone numbering
> covered and what remains. It uses that older numbering (which includes
> "Milestone 10" to "Milestone 12") and does not define the milestone
> structure; the [Official Project Roadmap](#official-project-roadmap) above does.

Milestone 0 (foundation), Milestone 1 (LLM gateway), Milestone 2
(conversational chat + persistence), Milestone 3 (document ingestion),
Milestone 4 (embeddings & vector storage), Milestone 5 (retrieval-
augmented generation), Milestone 6 (single-agent LangGraph orchestration
with controlled tool calling), Milestone 7 (MCP + A2A interoperability: an
MCP server/client for the same internal tools, and one remote Research
Agent reached through a real A2A boundary), and Milestone 8 (production-
oriented multi-agent orchestration: a deterministic orchestrator routing
to Research/Document/Analyst specialists through that same A2A boundary,
with explicit capability authorization, loop/delegation limits, partial-
failure-aware aggregation, retries, and timeouts), and Milestone 9 (the
Copilot UI/operations dashboard over the M8 API, with a Documents page, a
real-data-only Operations dashboard, and a System Status page — no
orchestration logic in the frontend; originally Streamlit, since migrated
to React/TypeScript/Vite, with Streamlit kept as a legacy, still-tested
option), and Milestone 10 (a Docker/Kubernetes deployment foundation for
that existing system: production-oriented multi-stage images for the
backend and each frontend, an extended Compose stack with real
healthchecks, and `kubectl apply`-able Kubernetes manifests with hardened
security context and Secret templates — no application redesign; the K8s
frontend manifests target the React app and its nginx proxies `/api/` to the
backend; the manifests are validated structurally only and have never been
applied to a cluster — see
[infra/kubernetes/README.md](infra/kubernetes/README.md)) are done.

Since then: a retrieval-level **evaluation harness** (Milestone 11, see
`backend/tests/evaluation/README.md`; answer-quality metrics are skipped because
they need a live LLM) and the first part of security, **bearer-token
authentication** and browser sign-in (Milestone 12; see [Authentication
setup](#authentication-setup)). Not started or not finished, in rough order,
each as its own milestone: the rest of
security/RBAC (further role-based permissions and a user admin API;
ownership-based data isolation is implemented, see
[ADR 013](docs/architecture/decisions/013-data-isolation.md)) → observability/LLMOps → async workers →
multimodal/voice. No document in the repository defines Milestones 11-13
beyond the code, ADR addenda and evaluation README that mention them.

Architecture decisions made ahead of their implementation are recorded in
[docs/architecture/decisions/](docs/architecture/decisions/).

## License

[MIT](LICENSE)
