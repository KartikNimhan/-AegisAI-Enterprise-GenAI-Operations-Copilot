# System Design

This describes the system as it exists today. It intentionally does not
describe unimplemented future capabilities beyond their reserved module
boundaries — see the roadmap in the [README](../../README.md) and the ADRs
in [decisions/](decisions/) for where those are headed.

## Overview

AegisAI is a modular monolith: a single FastAPI application (`backend/app`)
backed by PostgreSQL (with pgvector available), Redis, and the Groq-backed
LLM gateway, fronted by a Streamlit UI, all orchestrated via Docker Compose
in local development.

```
┌─────────────────┐       HTTP        ┌───────────────────────────────────┐
│ Streamlit UI     │ ─────────────────▶│ FastAPI app (backend)             │
│ (frontend/)      │                   │  api/ -> services/ -> llm/ -> db/ │
└─────────────────┘                   └───────────┬───────────┬───────────┘
                                                   │           │
                                   ┌───────────────┼───────┐   └──────────────┐
                                   ▼               ▼                          ▼
                         ┌──────────────────┐ ┌──────────┐           ┌───────────────┐
                         │ PostgreSQL        │ │ Redis    │           │ Groq API       │
                         │ (+ pgvector ext.) │ │          │           │ (external)     │
                         └──────────────────┘ └──────────┘           └───────────────┘
```

## Backend module boundaries

| Module | Responsibility today |
| --- | --- |
| `api/` | Thin HTTP routing and request/response schemas. No business logic. |
| `core/` | Cross-cutting concerns: logging, middleware, exception handling (including LLM error -> HTTP status mapping). Security/RBAC is reserved, not implemented. |
| `domain/` | Shared domain models/enums. Empty until the first persisted entities are needed. |
| `services/` | Business logic orchestration, called from `api/`. `chat_service.py` is implemented (Milestone 1); other service modules are still reserved. |
| `llm/` | The LLM gateway — a provider-neutral abstraction over chat completion. Implemented in Milestone 1, backed by Groq. See [ADR 002](decisions/002-llm-gateway.md) and [data-flow.md](data-flow.md). |
| `db/` | SQLAlchemy async engine/session and Redis client management, plus connectivity checks used by `/health/ready`. |
| `rag/`, `agents/`, `tools/`, `mcp/`, `memory/`, `evaluation/`, `observability/`, `workers/` | Reserved for future milestones (see the README roadmap). Each is an empty Python package today. |

Dependency direction is one-way: `api` → `services` → `llm`/`domain`/`db`.
Within `llm/`: `gateway.py` → `base.py` (the `LLMProvider` interface) →
`providers/groq.py`. Routes never talk to the database, Redis, or the Groq
SDK directly — `app.llm.providers.groq` is the *only* module in the
codebase allowed to import `groq`.

## Request lifecycle (today)

1. A request hits `CorrelationIdMiddleware` (`core/middleware.py`), which
   assigns or propagates an `X-Request-ID`, binds it to structlog's
   contextvars, and logs the request's completion with method, path,
   status code, and duration.
2. FastAPI routes the request. `/health`, `/health/ready`
   (`api/v1/health.py`), and `/api/v1/chat/completions[/stream]`
   (`api/v1/chat.py`) are implemented; everything else under `/api/v1` is
   reserved for future business endpoints.
3. Unhandled errors — including the typed `LLMError` hierarchy raised by
   the LLM gateway — are caught by handlers registered in
   `core/exceptions.py` and returned as a consistent JSON envelope:
   `{"error": {"code", "message", "request_id"}}`. Raw provider exceptions
   never reach this layer; `GroqProvider` has already translated them.

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

See [ADR 002](decisions/002-llm-gateway.md) for the full rationale and
[data-flow.md](data-flow.md) for the request/streaming flow. In brief:
`api/v1/chat.py` → `services/chat_service.py` → `llm/gateway.py`
(`LLMGateway`) → `llm/base.py` (`LLMProvider` interface) →
`llm/providers/groq.py` (`GroqProvider`) → the `groq` SDK. Model selection
is a deterministic `ModelRole` (`PRIMARY`/`FAST`/`SAFETY`) → configured
model name mapping (`PRIMARY_LLM_MODEL`, `FAST_LLM_MODEL`,
`SAFETY_LLM_MODEL`), not an AI-based router.

## Configuration

All configuration is environment-variable driven via `app/config.py`
(Pydantic Settings), with `.env.example` documenting every supported
variable. The same `Settings` object is the single source of truth for
both the running application and Alembic migrations (`backend/alembic/env.py`).
`GROQ_API_KEY` is stored as a `SecretStr` and is optional: the app starts
and the test suite passes without one, and only the chat endpoints fail
(with a typed 503) until it's set.

## Data flow

See [data-flow.md](data-flow.md) for the readiness-check data flow and the
LLM chat/streaming request flow.
