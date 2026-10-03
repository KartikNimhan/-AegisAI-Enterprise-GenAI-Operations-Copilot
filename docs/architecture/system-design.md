# System Design

This describes the system as it exists today. It intentionally does not
describe unimplemented future capabilities beyond their reserved module
boundaries — see the roadmap in the [README](../../README.md) and the ADRs
in [decisions/](decisions/) for where those are headed.

## Overview

AegisAI is a modular monolith: a single FastAPI application (`backend/app`)
backed by PostgreSQL (conversation/message/document persistence, with
pgvector available for a future milestone), Redis, local filesystem
document storage, and the Groq-backed LLM gateway, fronted by a Streamlit
UI, all orchestrated via Docker Compose in local development.

```
┌─────────────────┐       HTTP        ┌──────────────────────────────────────────────────┐
│ Streamlit UI     │ ─────────────────▶│ FastAPI app (backend)                            │
│ (frontend/)      │                   │  api/ -> services/ -> prompts/, llm/, documents/, db/ │
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
| `domain/` | ORM models (`Conversation`, `Message`, `Document`, `DocumentChunk`) and enums (`MessageRole`, `DocumentStatus`, `DocumentType`). |
| `services/` | Business logic orchestration, called from `api/`. `chat_service.py` (Milestone 1, extended in Milestone 2), `conversation_service.py` (Milestone 2), and `document_service.py` (Milestone 3) are implemented; other service modules are still reserved. |
| `prompts/` | Prompt management — versioned templates + `PromptBuilder`, which assembles `[system, history, new message]`. Implemented in Milestone 2. See [ADR 004](decisions/004-conversation-persistence.md). |
| `llm/` | The LLM gateway — a provider-neutral abstraction over chat completion. Implemented in Milestone 1, backed by Groq. See [ADR 002](decisions/002-llm-gateway.md). |
| `documents/` | Document ingestion: `validation.py`, `normalization.py`, `metadata.py`, `chunk_ids.py`, `extractors/` (one module per `DocumentType`: `pdf.py` via pypdf, `docx.py` via python-docx, `text.py`/`markdown.py`), `chunking/` (`RecursiveChunker`). Implemented in Milestone 3. See [ADR 005](decisions/005-document-ingestion.md). |
| `storage/` | Provider-neutral file storage (`base.py`); `local.py` (`LocalFileStorage`) is the only implementation. Implemented in Milestone 3. |
| `db/` | SQLAlchemy async engine/session, Redis client management, connectivity checks used by `/health/ready`, and `repositories/` (`ConversationRepository`, `MessageRepository`, `DocumentRepository`, `DocumentChunkRepository`) — the only code that issues SQLAlchemy queries. |
| `rag/`, `agents/`, `tools/`, `mcp/`, `memory/`, `evaluation/`, `observability/`, `workers/` | Reserved for future milestones (see the README roadmap). Each is an empty Python package today. |

Dependency direction is one-way: `api` → `services` →
`prompts`/`llm`/`documents`/`storage`/`db`. `domain/` sits below everything
and depends on nothing else in the app (notably, `domain` does not depend
on `llm` — see [ADR 004](decisions/004-conversation-persistence.md) on why
`MessageRole` and `ChatRole` are separate types). Within `llm/`:
`gateway.py` → `base.py` (the `LLMProvider` interface) → `providers/groq.py`.
Routes never talk to the database, Redis, the Groq SDK, the filesystem, or
a parsing library directly — `app.llm.providers.groq` is the *only* module
allowed to import `groq`; `app.documents.extractors` is the only code
allowed to import `pypdf`/`docx`; `app.storage` is the only code that
touches the filesystem; `app.db.repositories` is the only code that builds
SQLAlchemy queries.

## Request lifecycle (today)

1. A request hits `CorrelationIdMiddleware` (`core/middleware.py`), which
   assigns or propagates an `X-Request-ID`, binds it to structlog's
   contextvars, and logs the request's completion with method, path,
   status code, and duration.
2. FastAPI routes the request. `/health`, `/health/ready`
   (`api/v1/health.py`), `/api/v1/chat/completions[/stream]`
   (`api/v1/chat.py`), `/api/v1/conversations[/...]`
   (`api/v1/conversations.py`), and `/api/v1/documents[/...]`
   (`api/v1/documents.py`) are implemented; everything else under
   `/api/v1` is reserved for future business endpoints.
3. Unhandled errors — including the typed `LLMError` hierarchy,
   `NotFoundError`, and `DocumentValidationError` — are caught by handlers
   registered in `core/exceptions.py` and returned as a consistent JSON
   envelope: `{"error": {"code", "message", "request_id"}}`. Raw provider
   exceptions, raw database errors, and raw filesystem paths never reach
   this layer.

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
  unique constraint on `(document_id, chunk_index)`. No embedding/vector
  column yet — that's Milestone 4.
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

## Data flow

See [data-flow.md](data-flow.md) for the readiness-check, chat/streaming
request, conversation-retrieval, and document-ingestion data flows.
