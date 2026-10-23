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
| **Database-backed** | Needs PostgreSQL + pgvector. The suites exist (`backend/tests/integration/`, 119 tests, plus 4 in `backend/tests/evaluation/`) but **none has been run locally**: no disposable database was available. CI runs them against a Postgres service container; since this review an unreachable service fails those tests instead of skipping them. |
| **CI-reported** | Seen on GitHub's public run page (job outcome and duration only). Job logs, test counts and scan findings need a signed-in account and have **not** been read. |
| **Live** | Needs a running stack, a real identity provider, or an external model API. Not done. |

## Verification record

Latest local run: 2026-10-23, Windows, no Docker, no database, no network. Every backend run had
`DATABASE_URL` and `REDIS_URL` forced to an unreachable address, the Hugging Face hub offline, and the
LLM and identity-provider settings blank, so no test could reach a real service.

| Check | Result |
|---|---|
| `ruff check` / `ruff format --check` (whole repository) | clean / clean |
| `pyright` | 0 errors |
| `uv lock --check --offline` | consistent |
| Backend unit suite (`backend/tests/unit`) | **1568 passed, 1 skipped**, no warnings (82 s) (the skip is a test whose HTTP client cannot send the header it tests) |
| Streamlit UI tests | 27 passed |
| React (`vitest`, `tsc -b --noEmit`, `oxlint`, `npm run build`) | 133 passed; types clean; 3 pre-existing lint warnings; build succeeds |
| Production bundle | no preview entry point, no `[MOCK]` data, no source maps in `dist/` |
| Kubernetes manifest validator | 15 documents pass structural checks |
| Database-backed suites | collected only (123: 119 integration + 4 evaluation); **none run locally** |

CI-reported (not re-verified here): CI run #64 and security scanning run #37 completed successfully on
commit `5d30825` (2026-10-22). Neither has run on later commits. Whether CI's database tests ran or
skipped is not visible without signing in, and before this review a skip would have looked the same as
a pass (finding R-3 below).

Mocked tests are labelled as such in their docstrings. `test_indirect_access_paths.py` and
`test_scoped_repositories.py` prove structure and delegation, **not** that a database hides another
user's rows; `tests/integration/test_data_isolation.py` is the test for that and has not run locally.

## Roadmap compliance (M0 to M9)

Each milestone is tracked on four separate axes. "Implemented" means the code exists and matches the
roadmap row; it says nothing about whether it works against real infrastructure. No row is
"complete": every one still needs integration evidence that could not be produced here.

| # | Milestone | Implementation | Automated tests (offline) | Integration evidence | Remaining blockers |
|---|---|---|---|---|---|
| M0 | Foundation & Architecture | implemented: typed, validated settings; JSON logs with request ids; consistent errors (422s no longer echo input); request-size limit (no Content-Type bypass); security headers; Alembic 0001 to 0008 | pass | CI-reported green on `5d30825` only | a disposable PostgreSQL; Compose/Docker runs (not permitted locally) |
| M1 | LLM Gateway | implemented: provider-neutral gateway, Groq provider, model roles, retries with a `Retry-After` cap, total stream deadline, fixed client-facing error text | pass (scripted provider) | none | a Groq key and network; the `safety` role is unused (decision D-1) |
| M2 | Conversational AI | implemented: chat, bounded history window (now loaded with a bounded query), SSE, usage per message; message order made total (finding R-4) | pass | none; `test_chat_flow.py` not run | a disposable PostgreSQL |
| M3 | Document Intelligence | implemented: PDF/DOCX/TXT/Markdown, magic bytes, expansion limits, XXE-safe DOCX parsing (pinned by a test), duplicate-upload advisory lock | pass (real extractors) | none | a disposable PostgreSQL; the unique `(owner, checksum)` index needs an operator de-duplication first (ADR 016) |
| M4 | Embeddings | implemented: Sentence Transformers, pgvector column, dimension guard at startup, model/version stamping | pass (fake provider) | none | pgvector (not installed locally); the real model run is opt-in |
| M5 | Production RAG | implemented: scoped retrieval, filters, threshold, context assembly with marker neutralization, citation validation (retrieval, not claim support) | pass | none | a disposable PostgreSQL + pgvector; a live model |
| M6 | Agentic AI | implemented: LangGraph agent, allowlisted tools, step/tool/time budgets, malformed-argument handling, per-user memory with TTL, caps and an owner row lock | pass | none | a disposable PostgreSQL; human approval is a decision (D-2) |
| M7 | MCP + A2A Multi-Agent | implemented: in-process MCP, allowlisted A2A with size/deadline limits and validated responses, partial-failure isolation, stdio server fails closed | pass (mock transports) | none | a live multi-agent run (needs a model) |
| M8 | GenAI UI + APIs | implemented: React Copilot (four modes), Conversations, Documents, Memory, Operations, System Status; legacy Streamlit (no sign-in); development-only preview, excluded from builds | pass | none in a browser | an identity provider (OIDC) for sign-in; a browser |
| M9 | Production / MLOps / Responsible AI | partial: Dockerfiles, Kubernetes manifests (non-root, no service-account tokens), CI with service-requiring integration tests and pinned actions, reporting-only security scans, opt-in metrics, retrieval evaluation, runbooks | pass (static checks) | CI-reported only; scans' findings unreviewed | no tracing/dashboards/alerts; scans not blocking (D-9); no token budgets (D-10); no data-retention policy; manifests never applied |

## Security and reliability review (2026-10-23)

A full M0 to M9 review. Each finding was reproduced (or confirmed by reading the code) before it was
fixed. R-1 through R-12 each have a regression test; where the table says so (R-1, R-4), the tests
were also confirmed to fail with the fix reverted. R-13 (the Alembic `path_separator` setting) has no
regression test: it is verified only by the deprecation warning no longer appearing in test runs.
Nothing here was verified against a live system.

| ID | Severity | Where | Finding | Fix | Regression test |
|---|---|---|---|---|---|
| R-1 | Medium | `app/core/middleware.py` | The request-size limit skipped any request labelled `multipart/…`, so a 200 KB body reached a JSON route past a 2 KB limit (reproduced); the upload route had no overall cap, so a huge upload was spooled to disk before its size check | the limit is chosen by path, never by Content-Type; the upload route gets `DOCUMENT_MAX_UPLOAD_SIZE_BYTES` + 1 MiB | `tests/unit/test_body_size_limit.py` (5 fail without the fix) |
| R-2 | Medium | `app/core/exceptions.py` | 422 responses were `str(exc.errors())`: they echoed the rejected input in full (a 40,000-character message produced a 40,175-character error) and parser internals | a readable `loc: msg` summary plus `details` with `loc`/`msg`/`type` only, capped | `tests/unit/api/test_validation_errors.py` |
| R-3 | Medium | `.github/workflows/ci.yml`, `backend/tests/integration/` | every database, Redis and migration integration test skipped when its service was unreachable, so CI could be green without running the isolation tests | `AEGIS_REQUIRE_SERVICES=1` in the CI test job turns those skips into failures; `pytest -rs` lists every skip | `tests/unit/test_integration_requirements.py`; shown with an unreachable service: 2 skipped locally, 2 failed with the flag |
| R-4 | Medium | `app/db/repositories/message_repository.py`, `app/domain/models/` | messages were sorted by `created_at` only, whose default is PostgreSQL's `now()` (transaction start); a turn's question and answer share one transaction, so their order in the model's history and in the conversation view was up to the database | explicit, strictly increasing timestamps for new messages; a total order (`created_at`, question before answer, `id`) that also fixes rows already stored | `tests/unit/test_message_ordering.py` (real SQL on SQLite; 3 fail without the fix) |
| R-5 | Low | chat, RAG and agent services | every turn loaded the whole conversation, then kept at most `CHAT_HISTORY_MAX_MESSAGES` | `list_recent(limit=window)` | `tests/unit/services/test_history_loading.py` |
| R-6 | Low | `.github/workflows/ci.yml` | default token permissions; actions pinned by movable tags | `permissions: contents: read`; the same commit SHAs `security.yml` reviewed | `tests/unit/test_ci_workflow.py` |
| R-7 | Low | `frontend/web/nginx.conf.template` | no browser security headers; nginx version advertised | `nosniff`, `X-Frame-Options: SAMEORIGIN`, `Referrer-Policy`, a CSP limited to `frame-ancestors`/`object-src`/`base-uri` (no script or connect restriction, so sign-in cannot break); `server_tokens off`; repeated in `/config.js` | `tests/unit/test_frontend_proxy_config.py` (static; nginx not run) |
| R-8 | Low | `app/core/middleware.py`, `exceptions.py` | API responses (with user data) had no `nosniff` or `Cache-Control: no-store` | both on every response, including 413/422/500 | `tests/unit/test_security_headers.py` |
| R-9 | Low | `app/agents/tools/calculator.py` | `(-8) ** 0.5` was reported as a successful result with a complex number | non-real results are a calculator error | `tests/unit/agents/test_calculator.py` |
| R-10 | Low | `infra/kubernetes/*` | every pod mounted a service-account token it does not need | `automountServiceAccountToken: false` | `tests/unit/test_k8s_pod_security.py` |
| R-11 | Low | `app/config.py` | `CORS_ORIGINS=["*"]` with credentials allowed would accept any site | refused outside local development (local unchanged) | `tests/unit/test_settings.py` |
| R-12 | Low | `app/main.py` | the startup warm-up task was not referenced (the event loop holds tasks weakly) and never cancelled | kept on `app.state`, cancelled at shutdown if unfinished | `tests/unit/test_lifespan.py` |
| R-13 | Info | `backend/alembic.ini` | 15 Alembic deprecation warnings per test run | `path_separator = os` | warnings gone |

Checked and found sound (no change): token verification (algorithm allowlist before key lookup,
exact issuer, audience, required claims, size cap, fail-closed key fetching with a circuit breaker);
identity by `(issuer, subject)` with role and organization from the database; per-user rate limits
with bounded memory on every model route; storage path confinement (`is_relative_to`, server-generated
keys); no `eval`, shell execution, unsafe deserialization or string-built SQL in application code (Ruff
`S` rules; its `assert` hits only narrow types after explicit checks); DOCX parsing does not resolve
XML external entities (`tests/unit/documents/test_docx_xxe.py`, with a control proving the payload is
real); LLM errors reach clients as fixed text; logs carry no message content, prompts, emails or
tokens; the React app renders no HTML from data; application pods run non-root with all capabilities
dropped; the development Keycloak realm file holds no users or secrets; production builds contain no
preview code.

## Security model: what is enforced, and where it is not

Known limitations, none of which is fixed:

1. **Database isolation is unproven live.** Everything above about isolation rests on offline tests
   until `test_data_isolation.py` runs against Postgres.
2. **`backend/scripts/mcp_stdio_server.py`** has no authentication. It now refuses to start unless
   `MCP_STDIO_USER_ID` + `MCP_STDIO_ORGANIZATION_ID` (one user's data) or
   `MCP_STDIO_ALLOW_UNRESTRICTED=true` (every organization's data) is set, but whoever can run it
   on the database host chooses the scope. It is not reachable through the API.
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
9. **Not reviewed for a real deployment:** TLS termination, secrets management, data retention,
   and the identity provider's own configuration (the development realm file is for local use only).
   CORS now refuses `*` outside local development. Backup, restore and rollback are documented in
   [backup-restore-and-rollback.md](backup-restore-and-rollback.md); its referenced files exist, but
   the procedure itself has not been rehearsed.
10. **The legacy Streamlit UI has no sign-in** and renders model answers as Markdown (so an injected
   image link would be fetched if it were ever used against an authentication-enabled backend);
   whether to keep it is decision D-12.
11. **The bundled PostgreSQL and Redis manifests** run with their images' default security context
   (development/staging only; decision D-11).
12. **Cost controls are request counts, not tokens** (decision D-10).

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
5. Scrape the opt-in `/metrics` endpoint in a real environment, add tracing, dashboards, and
   alerting on 5xx rates, rate-limit refusals, limiter failures and LLM errors (the metrics exist;
   see `observability.md`), and on repeated `not_found` audit outcomes.
6. Review the reporting-only security scans' first results (they have run; the findings are in
   signed-in-only artifacts), record the baseline in `security-scanning.md`, then decide a blocking
   rule (D-9).
7. Ship audit logs to storage the application cannot alter; define retention.
8. A user-management API and UI (create/disable users, change roles) with its own audit events.
9. UI: hide admin-only pages from members; a sharing control for documents.
10. Review CORS, TLS, secrets handling, backup/restore and data retention for the target environment.
11. Semantic memory recall if wanted, and any further M9 governance documents the project wants
    (model-use policy, data-retention policy, responsible-AI review). The React Memory page now lists,
    adds, edits and deletes notes.
12. Push the current commits so CI runs the database-backed suites with `AEGIS_REQUIRE_SERVICES=1`,
    and read the `test` job's skip list.

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
