# Production readiness: evidence, limitations and remaining work

**This is not a claim that AegisAI is production-ready.** It records what has been checked, how,
what has *not* been checked, and what remains. Milestones are the ones in the
[Official Project Roadmap](../../README.md#official-project-roadmap) (M0 to M9); the table defines
scope, not completion, and nothing below changes it. Older documents (ADRs, code comments) use an
earlier working numbering, which this page does not use.

## How to read "verified"

| Label | Meaning here |
|---|---|
| **Offline-verified** | A test that ran and passed without Docker, a database or the network (fakes, mocks, executed SQL on SQLite, rendered migration SQL). It proves logic, **not** that a live system behaves the same. |
| **Database-backed** | Needs PostgreSQL + pgvector. The suites exist (`backend/tests/integration/`, 119 tests, plus 4 in `backend/tests/evaluation/`) but **none has been run in this work**. CI runs them against a Postgres service; its first run is the real test. |
| **Live** | Needs a running stack, a real identity provider, or an external model API. Not done. |

## Verification record (offline, this work)

| Check | Result |
|---|---|
| `ruff check` / `ruff format --check` (whole repository) | clean / clean |
| `pyright` | 0 errors |
| Backend unit suite (`backend/tests/unit`) | **1194 passed, 1 skipped** (the skip is an older test that the HTTP client cannot even execute) |
| Frontend (`vitest`, `tsc --noEmit`, `oxlint`) | 71 passed; types clean; 3 pre-existing style warnings, in files not touched by M5/M6/M8 |
| Streamlit UI tests | 27 passed |
| Kubernetes manifest validator | 15 documents pass structural checks |
| Migrations 0006 to 0008 | rendered SQL checked offline: 0006/0007 only `ALTER TABLE`/`CREATE INDEX`; 0008 only `CREATE TABLE agent_memories` + one index, plus version bookkeeping. **None applied by this work** |
| Database-backed suites | **123 collected, 2 passed (no database needed), 121 skipped because Postgres was unreachable; none of the database-backed assertions ran** |

Mocked tests are labelled as such in their docstrings. `test_indirect_access_paths.py` and
`test_scoped_repositories.py` prove structure and delegation, **not** that a database hides another
user's rows; `tests/integration/test_data_isolation.py` is the test for that and has not run.

## Roadmap compliance (M0 to M9)

Status vocabulary: `implemented and verified`, `partially verified`, `blocked`, `gap remains`.
"Evidence" points at code and tests; "Not verified / gap" is what keeps a row from being fully green.

| # | Milestone | Status | Evidence | Not verified / gap |
|---|---|---|---|---|
| M0 | Foundation & Architecture | partially verified | FastAPI app, typed settings with validators (`app/config.py`), JSON logging with request ids (`app/core/logging.py`, `middleware.py`), Dockerfile + Compose, Alembic chain 0001 to 0008; unit tests across all packages | PostgreSQL and Docker were not exercised in this work (not permitted); the Compose stack was seen healthy in an earlier session only |
| M1 | LLM Gateway | partially verified | provider-neutral gateway with Groq provider, model roles (`primary`/`fast`/`safety`), retries, streaming (`app/llm/`); 24 gateway tests plus service tests with scripted gateways | no live Groq call (no key, no network) |
| M2 | Conversational AI | partially verified | chat service, prompt builder, persisted history, SSE streaming (now returns a proper 404 before streaming starts), token usage stored per message; `tests/unit/services`, `prompts`, `api` | the database-backed chat flow tests (`test_chat_flow.py`) have not run |
| M3 | Document Intelligence | partially verified | PDF/DOCX/TXT/Markdown extractors, normalization, recursive chunking, local file storage; 66 document tests run the real extractors | persistence of documents/chunks needs the database suites |
| M4 | Embeddings | partially verified | Sentence Transformers provider, pgvector column, batching, model/version fields, similarity search (scoped); unit tests with a fake provider | exact search only (no ANN index, by design in ADR 006); the real model and pgvector queries are exercised only by opt-in/database tests |
| M5 | Production RAG | partially verified | retrieval service, top-K and similarity threshold, context assembly with citations, untrusted-context prompt, no-fabrication response; metadata filters (document id, types, file name, date range) as bound parameters after the access scope; inline citations validated against retrieved source ids (streamed and non-streamed), offline citation-validity metric; ADR 015 | no live retrieval or live-model run; filter/cross-user behavior on PostgreSQL is in unrun database tests; validation proves a cited id exists, not that it supports the claim |
| M6 | Agentic AI | partially verified | LangGraph agent graph, tool registry and calling, step/time limits, streaming; per-user agent memory (`save_memory` tool, recall into the prompt, `/api/v1/memories`, TTL, bounds, savepoint failure isolation; ADR 015) tested with the real repository over SQLite | **migration 0008 not applied; PostgreSQL constraints and concurrency untested**; recall is word-overlap ranking, not semantic; memory is not in the React UI; memory-poisoning risk is mitigated, not eliminated |
| M7 | MCP + A2A Multi-Agent | partially verified | in-process MCP server/client, A2A agent cards and tasks, trusted-agent allowlist, deterministic multi-agent orchestrator; 27 + 125 + 48 tests; the caller's own token is forwarded only to allowlisted agents | no live multi-agent run; the stdio MCP script is an unauthenticated operator tool (see below) |
| M8 | GenAI UI + APIs | implemented and verified (UI level) | React app (chat, documents, operations, system status) and the legacy Streamlit UI; the Copilot streams over SSE (incremental text, loading, stop, error with partial text, explicit retry, abort on leave); 71 + 27 UI tests pass, types clean | live backend + browser sign-in not run; streaming through nginx/real browser not run; no automatic reconnect (by design); **no WebSockets** (SSE only); no control in the UI for sharing a document or for hiding admin-only pages |
| M9 | Production / MLOps / Responsible AI | gap remains | Dockerfiles and Kubernetes manifests (structurally validated, never applied); CI pipeline (`.github/workflows/ci.yml`, never run here); retrieval evaluation harness with a stored baseline; OIDC authentication, roles, ownership-based isolation, rate limits, audit events (ADRs 013 and 014); readiness documentation | **no metrics or tracing** (no Prometheus/OpenTelemetry integration); no centralized alerting; evaluation is retrieval-level (answer quality needs a live model); no dependency-vulnerability, secret or image scanning in CI; no model-use or data-retention policy document; manifests need a cluster to be proven |

## Security model: what is enforced, and where it is not

Enforced in code and covered by offline tests:

- **Authentication.** Every `/api/v1` route requires a valid bearer token (RS256 allowlist, exact
  issuer, audience, required claims, small leeway) mapped to an *active* user in an *active*
  organization. Role and organization come from the database row, never from token claims. Missing
  configuration, an unreachable key set or a database error all fail closed (401/403/503). The
  token is not logged.
- **Roles.** `member` and `admin`. `/system/status` is admin-only. Administrators may delete or
  re-share any document in their organization but cannot read a private one and have no special
  access to conversations.
- **Isolation.** Conversations are private to their owner; documents are private by default and can be
  shared with the owner's organization. Enforced in SQL by repositories that require a scope, for
  REST, streaming, RAG retrieval, embeddings, agent tools, MCP adapters and A2A tasks. Foreign or
  guessed ids return 404. See ADR 013.
- **Abuse limits and audit.** Per-user rate limits on model requests, uploads and embedding jobs, and
  audit lines for sensitive actions. See ADR 014.

Known limitations, none of which is fixed:

1. **Database isolation is unproven live.** Everything above about isolation rests on offline tests
   until `test_data_isolation.py` runs against Postgres.
2. **`backend/scripts/mcp_stdio_server.py`** runs with an explicit unrestricted scope and no
   authentication. It is an operator tool and is not reachable through the API, but anyone who can
   run it on the database host sees every document.
3. **Rate limits are per process.** With several workers or replicas the effective limit multiplies,
   and a restart clears counts. No shared (Redis) limiter exists.
4. **Audit lines are ordinary logs**, not tamper-evident, and nothing alerts on them.
5. **No user-management API.** Accounts and roles are created by an operator command that writes to
   the database directly.
6. **Administrators see organization-wide document counts** in the operations summary (numbers only).
7. **The UI does not hide admin-only pages from members**; the API refuses them (403) and the UI
   shows "You do not have permission to do that".
8. **Legacy data is invisible until assigned.** After migration 0006 and before the backfill,
   pre-existing conversations and documents match no user's scope.
9. **Not reviewed:** CORS and cookie/session choices for a real deployment, TLS termination,
   secrets management, backup and restore procedures, data retention, and the identity provider's
   own configuration (the development realm file is for local use only).

## Migration readiness

*Fresh install.* `alembic upgrade head` runs 0001 to 0008 straight through (0007 passes because no row
is unowned). Then provision the first user (`scripts/provision_identity.py`).

*Existing database* (this project's own database was last seen at 0004 with one conversation and two
messages; nothing has been migrated or assigned by this work):

1. Back up (`pg_dump -Fc`), and verify the dump.
2. `alembic upgrade 0005` (adds organizations, users, identities; additive).
3. Provision the user who should own the existing data (`provision_identity.py`, with `--dry-run` first).
4. `alembic upgrade 0006` (adds nullable owner columns, visibility, constraints; changes no row).
5. `scripts/assign_legacy_data.py --email <user> --organization "<name>" --dry-run`, check the counts,
   then `--yes`. It requires both names, validates both, and only fills in missing owners.
6. `alembic upgrade head` (0007 makes the owner required, refusing while any row is unowned; 0008 then creates the `agent_memories` table, additive, no existing row touched; its downgrade drops that table and the memories in it).

What the SQL previews establish: the migrations only add structure, name their objects consistently
with the models, the downgrade drops only what 0006 added, and 0007 refuses while rows are unowned.
What they cannot establish: that the SQL executes on PostgreSQL, that the composite foreign key and
check constraints behave as intended on real data, and that the throwaway-database round trip works.
`tests/integration/test_ownership_migration.py` (opt-in via `RUN_MIGRATION_ROUNDTRIP=1`, enabled in CI)
is the test for those, and it has not run.

`make docker-migrate` and the Kubernetes migration job run `alembic upgrade head`; on a database with
unassigned rows they stop safely at 0006 with a message. Use steps 2 to 6 above instead.

## Blocked checks (need infrastructure that was not available or not permitted)

- Database-backed suites: data isolation, ownership migration round trip, repository, chat, RAG,
  embedding, ingestion and agent flows (115 tests).
- Live OIDC: a real sign-in, token issuance by Keycloak, the audience mapper, silent renewal, and
  `iss` stability when the backend reaches the identity provider by another host name.
- Docker images (build, migrate, health checks), Compose and Kubernetes deployment.
- Live model calls (Groq) and the answer-quality evaluation metrics.
- Concurrency behavior of the rate limiter under real load; multi-replica behavior.

## Remaining work, in priority order

1. Run the database-backed suites (locally with Docker, or by letting CI run them) and fix what they find.
2. Build the images; apply the migrations to a *copy* of the database following the sequence above; then to the real one.
3. Real browser sign-in with Keycloak; provision the first administrator; confirm `/system/status` is
   403 for a member and 200 for an administrator.
4. Decide and implement shared rate limiting if more than one process will serve traffic.
5. Add metrics and tracing (a dependency and deployment decision), and alerting on `limited` and
   repeated `not_found` audit outcomes.
6. Add dependency, secret and image scanning to CI.
7. Ship audit logs to storage the application cannot alter; define retention.
8. A user-management API and UI (create/disable users, change roles) with its own audit events.
9. UI: hide admin-only pages from members; a sharing control for documents.
10. Review CORS, TLS, secrets handling, backup/restore and data retention for the target environment.
11. A React UI for viewing/deleting agent memory, semantic memory recall if wanted, and any further M9 governance documents the project wants
    (model-use policy, responsible-AI review).

## Troubleshooting

| You see | Meaning | Where to look |
|---|---|---|
| `401` | no, expired or invalid token | `auth.denied` log lines (reason, request id) |
| `403` on most routes | valid token but the identity is not linked to a user, or the user/organization is disabled | `auth.denied`; run `provision_identity.py` |
| `403` on `/system/status` | the caller is a `member`; the page is for administrators | by design |
| `404` on a resource you believe exists | it exists but is not yours (or is private to someone else); the API does not say which | the `audit` line with outcome `not_found` |
| `429` with `Retry-After` | a rate limit; wait or raise the `RATE_LIMIT_*` setting | `audit` line `rate_limit.exceeded` (warning) |
| `503` on a protected route | authentication is not configured, the key set is unreachable, the database failed, or the rate limiter could not enforce | `auth.unavailable` / `rate_limit.unavailable` error lines |
| old conversations/documents "missing" after upgrading | unowned legacy rows are invisible until the backfill | `assign_legacy_data.py --dry-run` reports the counts |

Find audit events with the JSON field `audit_action` (for example `document.deleted`).
