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
credentials. Running the API locally (`ENVIRONMENT=local`) needs no further edits,
but with `AUTH_ISSUER`, `AUTH_AUDIENCE` and `AUTH_JWKS_URL` blank every protected
route answers `503`. The full Compose stack (Option B below) additionally
**requires** those three values: its backend runs with `ENVIRONMENT=docker` and
refuses to start without them. See "Authentication setup" in the root
[README](../../README.md#authentication-setup).

## 3. Start PostgreSQL and Redis

Option A — only the datastores, running the API locally for fast reload:

```bash
docker compose up -d postgres redis
```

Option B — the full stack (API + datastores) in containers (set the `AUTH_*`
values in `.env` first, see above):

```bash
docker compose up --build
```

Both options need `REDIS_PASSWORD` set first (in your shell or the root `.env`; see
`.env.example`): the Compose Redis refuses to start without one, and its ports are published on
`127.0.0.1` only. A **native Windows setup** (PostgreSQL and Redis for Windows installed locally,
no Docker) needs no change: leave `REDIS_PASSWORD` empty if your Redis has no `requirepass`, and
keep `RATE_LIMIT_BACKEND=memory`. See [docs/security](../security/README.md) for every
security-related setting.

## 4. Run database migrations

```bash
cd backend
uv run alembic upgrade head
```

This applies every migration in `backend/alembic/versions/` (currently `0001`
to `0005`: the `vector` extension, conversations and messages, documents and
chunks, chunk embeddings, and the identity tables).

## 5. Run the API locally

```bash
cd backend
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Then check:

- http://localhost:8000/health — liveness
- http://localhost:8000/health/ready — readiness (requires Postgres + Redis)
- http://localhost:8000/docs — interactive OpenAPI docs (served only when
  `ENVIRONMENT=local`)

Or via `make run` / `make docker-up` from the repo root (see the
[Makefile](../../Makefile)).

## 6. Run the Streamlit frontend (optional)

```bash
cd frontend/streamlit
uv run streamlit run app.py
```

It only verifies backend connectivity in this milestone — see the
[README](../../README.md#implementation-history-and-remaining-work) for what's planned.
It is a **legacy UI without sign-in**: a backend with authentication enabled refuses its requests.
The React app (`frontend/web`) is the supported, authenticated interface (ADR 017, D-12).

## Running checks

```bash
uv run ruff check .      # lint
uv run ruff format .     # format
uv run pyright           # type check
```

## Running tests safely

The test suite never uses your development database. Before anything imports the application,
`backend/tests/isolation.py` points the test process at a separate **test database** and a
separate Redis database number, or, if none is configured, at an address where nothing listens.

| Command | What it does |
|---|---|
| `uv run pytest backend/tests/unit -q` | Unit tests. They cannot connect to PostgreSQL at all: every connection attempt fails at once (`backend/tests/unit/conftest.py`). |
| `uv run python scripts/test_db.py check` | Read-only status of the test database: which one, the server version, the `vector` extension and the migration revision. |
| `uv run python scripts/test_db.py migrate --yes` | `alembic upgrade head` on the **test** database only. Without `--yes` it only says what it would do. |
| `uv run pytest backend/tests/integration -rs` | Integration tests, against the test database only. Without one configured they skip and say why (`-rs` lists every skip). |

`uv run pytest` with no path runs everything, under the same rules.

### Rules the test database must pass

The test suite and `scripts/test_db.py` refuse a `TEST_DATABASE_URL`, before any connection, unless
it:

- contains no spaces, tabs, control characters or `#`;
- uses the `postgresql+asyncpg` driver;
- points at this machine (`localhost`, `127.0.0.1` or `::1`);
- has no query parameters (they could redirect the connection);
- writes the host and database name as plain text, with no `%` encoding (`aegis%00_test`, for
  example, is refused: it would decode to a hidden character). A password may be `%`-encoded;
- names a database of lowercase letters, digits and underscores, starting with a letter, ending
  in `_test`, and at most 63 characters (PostgreSQL would silently shorten a longer name);
- does not name the same database as `DATABASE_URL` in `.env`.

`TEST_REDIS_URL` must point at this machine and use a different Redis database number from
`REDIS_URL` in `.env`. The development number is read the way the Redis client reads it (a
`?db=` in the URL wins over the path); if it cannot be read with certainty, the test Redis is
refused rather than guessed.

Before the first integration or evaluation test that uses the database, the suite also asks the
server which database it really is and which migration it is at, and stops the whole run if
either is wrong.

The test process never uses your development settings:

- it does not read `.env` at all;
- it removes every inherited variable named after an application setting, in any spelling
  (`DEBUG`, `ENVIRONMENT`, `AUTH_*`, ...), because an editor can copy all of `.env` into a
  terminal (the VS Code Python Environments setting `python.terminal.useEnvFile` does this);
- it sets `DEBUG=false`, which child processes inherit too.

Test-control variables such as `TEST_*`, `RUN_*` and `AEGIS_*` are kept. A test that needs a
particular setting sets it itself.

**Billed Groq tests need a two-part opt-in:** `GROQ_API_KEY` in the shell *and*
`AEGIS_ALLOW_LIVE_LLM_TESTS=1`. Without the flag the key is blanked for the tests, so a key on its
own can never start a billed test. For one PowerShell run:

```powershell
$env:AEGIS_ALLOW_LIVE_LLM_TESTS = "1"
$env:GROQ_API_KEY = [System.Net.NetworkCredential]::new("", (Read-Host -AsSecureString "Groq key")).Password
uv run pytest -m llm_integration -v -rs
Remove-Item Env:AEGIS_ALLOW_LIVE_LLM_TESTS, Env:GROQ_API_KEY
```

### When the guard runs

The guard runs when pytest first imports the `tests` package (`backend/tests/__init__.py`). Every
test module and conftest is part of that package, so it runs however pytest is started: with
`--noconftest` (including through `PYTEST_ADDOPTS`), with a `--confcutdir` that skips
`backend/tests/conftest.py`, in every `--import-mode`, and from another folder.
`backend/tests/unit/test_isolation_entry_points.py` proves this by starting pytest each of those
ways. It cannot stop someone who deliberately runs test code outside pytest, or who edits the
guard.

### One-time setup of the test database

Nothing here touches your development database. In PowerShell:

1. Create the database and the `vector` extension, as the PostgreSQL superuser (`postgres`):

   ```powershell
   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -c "CREATE DATABASE aegis_test OWNER aegis;"
   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -d aegis_test -c "CREATE EXTENSION IF NOT EXISTS vector;"
   ```

   Creating the extension as the superuser means the migrations need no extra rights (migration
   `0001` then finds it already installed). Adjust the path for your PostgreSQL version.

2. Copy the template and set the password of the `aegis` role in the copy (Git ignores
   `.env.test`):

   ```powershell
   Copy-Item .env.test.example .env.test
   notepad .env.test
   ```

   Set `TEST_REDIS_URL` to your local Redis host and port, keeping a database number other than
   the one in `.env` (the template uses `15`).

3. Check, migrate, check again:

   ```powershell
   uv run python scripts/test_db.py check
   uv run python scripts/test_db.py migrate --yes
   uv run python scripts/test_db.py check     # expect "Ready"
   ```

The integration tests create and delete their own organizations, users and documents in the test
database.

The two migration round-trip tests, `backend/tests/integration/test_identity_migration.py` and
`test_ownership_migration.py`, are off unless you set `RUN_MIGRATION_ROUNDTRIP=1`. When on, each
one:

1. connects to the `postgres` maintenance database on the test database's server (the server in
   `TEST_DATABASE_URL`, which the guard has already checked);
2. creates its own database, named `aegis_identity_<random>_test` or
   `aegis_ownership_<random>_test`;
3. runs migrations up and down inside that database only;
4. drops it again with `DROP DATABASE ... WITH (FORCE)`, in a `finally` block, so also after a
   failure.

They never open `aegis` or `aegis_test`. They need a role allowed to create databases
(`CREATEDB`), and skip if it is not. If a run is killed before step 4, remove the leftover
database by hand; its name always ends in `_test`.

In CI each workflow's service database is named `aegis_test` and reached through
`TEST_DATABASE_URL`; `AEGIS_REQUIRE_SERVICES=1` turns any skip for a missing service into a
failure.

## Creating a new migration

```bash
cd backend
uv run alembic revision --autogenerate -m "describe the change"
```

Autogenerate only picks up models imported in `backend/alembic/env.py` —
remember to import new domain models there as they're added.
