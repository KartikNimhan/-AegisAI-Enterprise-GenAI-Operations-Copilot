# AegisAI — Enterprise GenAI Operations Copilot

AegisAI is a production-oriented, modular-monolith backend (plus a thin
Streamlit UI) intended to progressively grow into an enterprise GenAI
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
an agent swarm. Memory beyond plain conversation history is **not**
implemented yet — see [Roadmap](#roadmap) below.

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
  citations and retrieval metadata in the response.
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
  (the MCP Inspector, an IDE). See
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
- Docker + Docker Compose (backend, PostgreSQL with pgvector, Redis).
- Unit tests (fast, no live infra, API key, or embedding model download
  required) and integration tests that skip gracefully when
  Postgres/Redis/`GROQ_API_KEY`/the real embedding model aren't available
  or opted into, via pytest.
- Ruff (lint + format) and pyright (type checking), both run in CI.
- A minimal Streamlit page that checks backend connectivity.

## Stack

Python 3.12+ · uv · FastAPI · Pydantic v2 + pydantic-settings · SQLAlchemy
2.x (async) · PostgreSQL + pgvector · Alembic · Redis · Groq SDK · pypdf ·
python-docx · Sentence Transformers · LangGraph · MCP SDK · a2a-sdk ·
httpx · pytest · Ruff · pyright · Docker/Docker Compose · Streamlit

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
  memory/         agent memory beyond conversation history (reserved)
  evaluation/     evaluation harness (reserved)
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

## Quickstart

```bash
uv sync --all-groups
cp .env.example .env          # optionally set GROQ_API_KEY for real LLM calls
docker compose up -d postgres redis
cd backend && uv run alembic upgrade head && cd ..
cd backend && uv run uvicorn app.main:app --reload
```

Then visit http://localhost:8000/health, http://localhost:8000/health/ready,
and http://localhost:8000/docs.

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

Or `make check` (lint + typecheck + test). See the [Makefile](Makefile) for
all available targets (`run`, `docker-up`, `migrate`, ...).

## Roadmap

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
failure-aware aggregation, retries, and timeouts) are done. Remaining, in
rough order, each as its own milestone: memory beyond conversation
history → evaluation → security/RBAC → observability/LLMOps → async
workers → Kubernetes → multimodal/voice.

Architecture decisions made ahead of their implementation are recorded in
[docs/architecture/decisions/](docs/architecture/decisions/).

## License

[MIT](LICENSE)
