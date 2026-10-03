# Development Setup

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python package/project manager)
- Python 3.12+ (uv can install this for you: `uv python install 3.12`)
- Docker + Docker Compose (for PostgreSQL and Redis)

## 1. Clone and install dependencies

```bash
uv sync --all-groups
```

This creates `.venv/` and installs both runtime and development
dependencies (pytest, ruff, pyright) from `uv.lock`.

## 2. Configure environment variables

```bash
cp .env.example .env
```

The defaults in `.env.example` match `docker-compose.yml`'s Postgres/Redis
credentials, so no edits are required to run everything via Docker Compose.

## 3. Start PostgreSQL and Redis

Option A — only the datastores, running the API locally for fast reload:

```bash
docker compose up -d postgres redis
```

Option B — the full stack (API + datastores) in containers:

```bash
docker compose up --build
```

## 4. Run database migrations

```bash
cd backend
uv run alembic upgrade head
```

This applies `0001_enable_pgvector`, which enables the `vector` Postgres
extension (no application tables exist yet).

## 5. Run the API locally

```bash
cd backend
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Then check:

- http://localhost:8000/health — liveness
- http://localhost:8000/health/ready — readiness (requires Postgres + Redis)
- http://localhost:8000/docs — interactive OpenAPI docs

Or via `make run` / `make docker-up` from the repo root (see the
[Makefile](../../Makefile)).

## 6. Run the Streamlit frontend (optional)

```bash
cd frontend/streamlit
uv run streamlit run app.py
```

It only verifies backend connectivity in this milestone — see the README
roadmap for what's planned.

## Running checks

```bash
uv run pytest            # unit tests always run; integration tests
                          # skip themselves if Postgres/Redis aren't reachable
uv run ruff check .      # lint
uv run ruff format .     # format
uv run pyright           # type check
```

Or `make check` to run lint + typecheck + test together.

## Creating a new migration

```bash
cd backend
uv run alembic revision --autogenerate -m "describe the change"
```

Autogenerate only picks up models imported in `backend/alembic/env.py` —
remember to import new domain models there as they're added.
