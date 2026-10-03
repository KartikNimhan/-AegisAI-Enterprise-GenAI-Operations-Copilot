# AegisAI — Enterprise GenAI Operations Copilot

AegisAI is a production-oriented, modular-monolith backend (plus a thin
Streamlit UI) intended to progressively grow into an enterprise GenAI
operations platform: an LLM gateway with multi-model routing, RAG,
embeddings/vector search, LangGraph agents, tool calling, MCP, multi-agent
workflows (A2A), memory, evaluation, security/RBAC, observability/LLMOps,
async workers, and eventually containerized/Kubernetes deployment.

**Milestone 0** built the project foundation. **Milestone 1** adds a
production-quality, provider-neutral LLM gateway backed by Groq. RAG,
agents, LangGraph, MCP, A2A, memory, and document processing are **not**
implemented yet — see [Roadmap](#roadmap) below.

## What's implemented today

- FastAPI application with thin routing, a modular package layout, and
  structured (JSON) logging with request correlation IDs.
- `GET /health` (liveness) and `GET /health/ready` (readiness: checks
  PostgreSQL and Redis connectivity).
- Async SQLAlchemy 2.x engine/session wired to PostgreSQL, with Alembic
  migrations. A migration enables the `pgvector` extension ahead of the RAG
  milestone (no vector columns or models exist yet).
- Async Redis connectivity.
- Consistent JSON error responses for unhandled exceptions and HTTP errors.
- **An LLM gateway** (`backend/app/llm/`) — a provider-neutral abstraction
  over chat completion, backed by [Groq](https://console.groq.com/) as the
  first real provider. Deterministic model routing via `ModelRole`
  (`primary` / `fast` / `safety`), sync and streaming (SSE) completion,
  typed errors, retries with backoff, and secret-free structured logging.
  See [ADR 002](docs/architecture/decisions/002-llm-gateway.md).
- `POST /api/v1/chat/completions` and `POST /api/v1/chat/completions/stream`
  — thin dev endpoints exercising the gateway end to end.
- Docker + Docker Compose (backend, PostgreSQL with pgvector, Redis).
- Unit tests (fast, no live infra or API key required) and integration
  tests that skip gracefully when Postgres/Redis/`GROQ_API_KEY` aren't
  available, via pytest.
- Ruff (lint + format) and pyright (type checking), both run in CI.
- A minimal Streamlit page that checks backend connectivity.

## Stack

Python 3.12+ · uv · FastAPI · Pydantic v2 + pydantic-settings · SQLAlchemy
2.x (async) · PostgreSQL + pgvector · Alembic · Redis · Groq SDK · pytest ·
Ruff · pyright · Docker/Docker Compose · Streamlit

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
  domain/         shared domain models/enums (empty until first persisted entity)
  services/       business logic orchestration (chat_service.py implemented)
  llm/            LLM gateway — implemented, Groq-backed (see ADR 002)
    base.py         provider-neutral LLMProvider interface
    gateway.py       LLMGateway: routing, retries, standardized responses
    schemas.py       ModelRole, ChatMessage, CompletionResponse, StreamChunk
    exceptions.py    typed LLMError hierarchy
    providers/groq.py  the only module allowed to import the `groq` SDK
  rag/            RAG / embeddings / vector search (reserved)
  agents/         LangGraph agents (reserved)
  tools/          tool calling (reserved)
  mcp/            Model Context Protocol (reserved)
  memory/         agent/conversation memory (reserved)
  evaluation/     evaluation harness (reserved)
  observability/  LLMOps observability (reserved)
  workers/        async workers (reserved)
  db/             SQLAlchemy session + Redis client management
```

Routes never contain business logic; they delegate to `services/`, which
depends on `llm/`, `domain/`, and `db/`. The LLM call chain is strictly
`api -> service -> LLMGateway -> LLMProvider interface -> GroqProvider ->
groq SDK` — nothing above `providers/groq.py` ever imports `groq`. See
[docs/architecture/system-design.md](docs/architecture/system-design.md)
for the full picture and
[docs/architecture/data-flow.md](docs/architecture/data-flow.md) for the
readiness-check and chat/streaming data flows.

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
curl -X POST http://localhost:8000/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"message": "Say hello in five words.", "model_role": "fast"}'

curl -N -X POST http://localhost:8000/api/v1/chat/completions/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "Count from 1 to 5.", "model_role": "fast"}'
```

Without `GROQ_API_KEY` set, the app still starts and `/docs` still lists
both endpoints — they respond with a `503 llm_unavailable` instead.

Full setup instructions: [docs/development/setup.md](docs/development/setup.md).

## Running checks

```bash
uv run pytest       # unit + integration; integration tests skip without live
                     # Postgres/Redis, and the Groq live test skips without
                     # a real GROQ_API_KEY — neither is required to pass
uv run ruff check .
uv run ruff format .
uv run pyright
```

Run the opt-in real Groq test explicitly with:

```bash
GROQ_API_KEY=sk-... uv run pytest -m llm_integration -v
```

Or `make check` (lint + typecheck + test). See the [Makefile](Makefile) for
all available targets (`run`, `docker-up`, `migrate`, ...).

## Roadmap

Milestone 0 (foundation) and Milestone 1 (LLM gateway) are done. Remaining,
in rough order, each as its own milestone: RAG / embeddings / vector search
→ LangGraph agents & tool calling → MCP → multi-agent workflows (A2A) →
memory → evaluation → security/RBAC → observability/LLMOps → async workers
→ Kubernetes → multimodal/voice.

Architecture decisions made ahead of their implementation are recorded in
[docs/architecture/decisions/](docs/architecture/decisions/).

## License

[MIT](LICENSE)
