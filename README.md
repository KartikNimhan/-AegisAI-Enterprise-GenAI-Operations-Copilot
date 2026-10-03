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
RAG retrieval, LangGraph, agents, MCP, A2A, and memory beyond plain
conversation history are **not** implemented yet — see
[Roadmap](#roadmap) below.

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
python-docx · Sentence Transformers · pytest · Ruff · pyright ·
Docker/Docker Compose · Streamlit

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
    schemas.py       ModelRole, ChatMessage, CompletionResponse, StreamChunk
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
    service.py      EmbeddingService: batching, idempotency, persistence
    schemas.py       EmbeddingJobResult, EmbeddingStatus, SimilarityMatch
    exceptions.py    typed EmbeddingError hierarchy
    providers/local.py  the only module allowed to import sentence_transformers
  rag/            RAG retrieval (reserved)
  agents/         LangGraph agents (reserved)
  tools/          tool calling (reserved)
  mcp/            Model Context Protocol (reserved)
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
`services/`, which depends on `prompts/`, `llm/`, `documents/`, `storage/`,
`embeddings/`, and `db/`. The LLM call chain is strictly
`api -> service -> LLMGateway -> LLMProvider interface -> GroqProvider ->
groq SDK`; the embedding call chain is strictly `api -> EmbeddingService ->
EmbeddingProvider interface -> LocalEmbeddingProvider ->
sentence_transformers` — nothing above `providers/groq.py` ever imports
`groq`; nothing outside `documents/extractors/` imports `pypdf`/`docx`;
nothing outside `embeddings/providers/local.py` imports
`sentence_transformers`; nothing outside `storage/` touches the
filesystem; nothing outside `db/repositories/` builds a SQLAlchemy query.
See [docs/architecture/system-design.md](docs/architecture/system-design.md)
for the full picture and
[docs/architecture/data-flow.md](docs/architecture/data-flow.md) for the
readiness-check, chat/streaming, conversation-retrieval,
document-ingestion, and embedding data flows.

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

Without `GROQ_API_KEY` set, the app still starts and `/docs` still lists
every endpoint — chat requests respond with a `503 llm_unavailable` instead
(and persist nothing, per the atomic-turn design — see
[ADR 004](docs/architecture/decisions/004-conversation-persistence.md)).
The conversation endpoints work regardless, since they don't call Groq.

Full setup instructions: [docs/development/setup.md](docs/development/setup.md).

## Running checks

```bash
uv run pytest       # unit + integration; integration tests skip without live
                     # Postgres/Redis, the Groq live test skips without a
                     # real GROQ_API_KEY, and the embedding live test skips
                     # unless explicitly opted into — none are required to pass
uv run ruff check .
uv run ruff format .
uv run pyright
```

Run the opt-in real Groq test explicitly with:

```bash
GROQ_API_KEY=sk-... uv run pytest -m llm_integration -v
```

Run the opt-in real embedding-model test explicitly with (downloads/loads
the real Sentence Transformers model):

```bash
RUN_EMBEDDING_INTEGRATION=1 uv run pytest -m embedding_integration -v
```

Or `make check` (lint + typecheck + test). See the [Makefile](Makefile) for
all available targets (`run`, `docker-up`, `migrate`, ...).

## Roadmap

Milestone 0 (foundation), Milestone 1 (LLM gateway), Milestone 2
(conversational chat + persistence), Milestone 3 (document ingestion), and
Milestone 4 (embeddings & vector storage) are done. Remaining, in rough
order, each as its own milestone: RAG retrieval → LangGraph agents & tool
calling → MCP → multi-agent workflows (A2A) → memory beyond conversation
history → evaluation → security/RBAC → observability/LLMOps → async
workers → Kubernetes → multimodal/voice.

Architecture decisions made ahead of their implementation are recorded in
[docs/architecture/decisions/](docs/architecture/decisions/).

## License

[MIT](LICENSE)
