# Production readiness: evidence, limitations and remaining work

**This is not a claim that AegisAI is production-ready.** It records what has been checked, how,
what has *not* been checked, and what remains. Milestones are the ones in the
[Official Project Roadmap](../../README.md#official-project-roadmap) (M0 to M9); the table defines
scope, not completion, and nothing below changes it. Older documents (ADRs, code comments) use an
earlier working numbering, which this page does not use.

**Status (2026-11-01): not production-ready.** On `bcccb20` (`main`, 2026-11-01) CI run #103
passed and Security scanning run #77 passed, with every scan **blocking** since `3023c82` (see the
verification record). The Kubernetes smoke test last passed on `e75e7ed`, *before* `3023c82` changed
the manifests it deploys, and has not been re-run; the live RAG run last passed on `f164c04`, before
`3023c82` changed the answer path. A throwaway cluster is not a staging or production deployment,
and these are still outstanding: a real staging deployment with that environment's own secrets, a
real sign-in through an identity provider, the migrations on a disposable copy of the staging
database, a backup and restore rehearsal, a verified rollback, load and failure testing, and
operational monitoring and alerting. Existing Kubernetes cluster selected as the intended staging
target. Cluster identity, access, Kubernetes version, network plugin, ingress/TLS, secrets
management, registry access and capacity remain unverified. No staging deployment has occurred.
Cluster readiness must be assessed before deployment. `main` has no branch protection, so a failing
check does not stop a push or a merge.

## How to read "verified"

| Label | Meaning here |
|---|---|
| **Offline-verified** | A test that ran and passed without Docker, a database or the network (fakes, mocks, executed SQL on SQLite, rendered migration SQL). It proves logic, **not** that a live system behaves the same. |
| **Database-backed** | Needs PostgreSQL + pgvector (and Redis for a few). 128 integration tests are collected: 110 need only the test database and Redis, 18 are opt-in (live model, real embedding model, MCP stdio, A2A and multi-agent over HTTP, migration round trips); 4 evaluation tests (2 opt-in). Since 2026-11-01 they also run **locally**, against an isolated `aegis_test` database that the test harness enforces (`backend/tests/isolation.py`: the name must end in `_test`, and the server is asked which database it is). CI runs them against its own service containers, where an unreachable service fails them instead of skipping them. None has run against a deployed database. |
| **CI-reported** | Seen through GitHub's public run list and API (job outcome only). Job logs and test counts need a signed-in account and have **not** been read. Scan reports were read only where the baseline log in [security-scanning.md](security-scanning.md) says so. |
| **Live** | Needs a running stack, a real identity provider, or an external model API. Two things have run against a live model: the two Groq tests (locally, reported by the maintainer) and the live RAG end-to-end workflow (in CI, run #3). The whole stack has run once, in a disposable kind cluster in CI (Kubernetes smoke test run #2, on `e75e7ed`), with placeholder identity-provider settings and no model call. No identity provider, staging or production deployment has been exercised. |

## Verification record

Latest local run: 2026-11-01, Windows, no Docker, on the tree committed as `bcccb20`. The test
harness (`backend/tests/isolation.py`) ignores `.env`, removes inherited application settings, forces
`DEBUG=false`, blanks `GROQ_API_KEY` and points the tests at an isolated test database and Redis
database; no live-model, billed or migration round-trip test was enabled. The local test PostgreSQL
(`aegis_test`, at `0008`) was reachable; the local test Redis was **not**, so its tests skipped.

| Check | Result |
|---|---|
| `ruff check` / `ruff format --check` (whole repository) | clean / clean |
| `pyright` | 0 errors |
| `uv lock --check` | consistent (140 packages) |
| Backend, whole suite in one process (`uv run pytest -rs`, as CI runs it) | **2333 passed, 28 skipped, 0 failed**. An earlier run on the same tree had 1 failure, `test_isolated_extraction.py::test_a_parser_that_never_finishes_is_stopped_at_the_deadline` (a timing-sensitive process-deadline test), under heavy machine load; it passed 3 of 3 times alone and in the full rerun |
| Skipped, by reason | 20 opt-in (live, billed, migration round trip, 2 evaluation); 7 need Redis (unreachable locally: the shared rate-limiter tests, readiness, Redis connectivity); 1 test whose HTTP client cannot send the header it tests |
| Streamlit UI tests | 36 passed |
| React (`vitest`, `tsc -b`, `oxlint`) | 144 passed; types clean; 3 pre-existing lint warnings (run on `9ac72f0`; `bcccb20` changes no frontend file). `vite build` last succeeded on 2026-10-31, after the last frontend change |
| Production bundle | no preview entry point, no `[MOCK]` data, no source maps (`src/preview/previewSecurity.test.ts`) |
| Kubernetes manifest validator | 19 documents across 17 files pass structural checks |
| `pip-audit` (the workflow's pinned 2.10.1, its two exports and `scripts/security_scan_policy.py`) | PASS; `torch` (the `+cpu` build is not on PyPI) not audited. The same check on the previous lock reports the advisories that failed Security scanning runs #75 and #76 |
| `npm audit` (the workflow's two passes and the policy script) | PASS |
| Docker image builds, Trivy, gitleaks | **not run locally** (Docker not permitted here; the scanners are not installed). See CI below |

CI-reported (job outcomes and annotations from GitHub's public API, checked 2026-11-01; logs and
artifacts need a signed-in account with admin rights and have **not** been read):

- **CI run #103** on `bcccb20` (`main`, 2026-11-01): all 7 jobs succeeded (`lint`, `typecheck`,
  `test`, `frontend-react-test`, `frontend-streamlit-test`, `docker-build`, `k8s-manifests`). The
  `test` job runs with `AEGIS_REQUIRE_SERVICES=1` and `RUN_MIGRATION_ROUNDTRIP=1`; which tests ran
  is in its skip list, not read. Non-blocking annotations: actions still targeting Node.js 20, the
  3 React lint warnings, Docker's `JSONArgsRecommended` warning on the shell-form `CMD` (used on
  purpose, with `exec`), and GitHub cache-service errors that did not affect the result. Run #101 on
  `3023c82` had failed in `test` (a unit test reused a database connection an integration test had
  left in the pool); `9ac72f0` fixed it and run #102 passed.
- **Security scanning run #77** on `bcccb20`: all four jobs succeeded, and since `3023c82` each one
  ends with a **blocking** policy step (`scripts/security_scan_policy.py`; exceptions file
  `.github/security-scan-exceptions.json`, empty). What that does and does not show:
  - pip-audit: no known vulnerability with a released fix in the runtime or the all-groups set;
    one package per set (`torch`, CPU build) was skipped and **not audited** (run annotation);
  - npm audit: no high or critical advisory (moderate and low do not block);
  - gitleaks: no potential secret matched in the full history (not proof that none exists);
  - Trivy: no fixable CRITICAL or HIGH finding in the three images. Medium and low findings do not
    block and unfixed vulnerabilities are not reported by design (`ignore-unfixed`), so a green job
    is **not** a report of zero findings; the reports themselves have not been read.
  Runs #75 (`3023c82`) and #76 (`9ac72f0`) failed in the pip-audit and Trivy policy steps with
  blocking findings (exit code 1). The Python findings were reproduced locally from the public OSV
  database: 11 advisories, published 2026-10-28 to 2026-10-30, in `pypdf` 6.21.2, `pyasn1` 0.6.4,
  `langgraph` 1.2.12 and `langgraph-sdk` 0.4.5. `bcccb20` upgraded them to 6.21.4, 0.6.5, 1.2.14 and
  0.4.6 (`pyasn1` and `langgraph-sdk` through `[tool.uv] constraint-dependencies`). The Trivy findings
  of runs #75 and #76 were not read; the job passed in run #77.

Earlier (checked 2026-10-28):

- **CI run #88** on `e75e7ed` (`main` as of 2026-10-27): all 7 jobs succeeded (so did
  run #85 on `f164c04` and run #78 on `4f151d2` before it). The `test` job runs the
  database-backed suites against its own PostgreSQL and Redis service containers, with
  `AEGIS_REQUIRE_SERVICES=1` (an unreachable service fails the tests instead of skipping them) and
  `RUN_MIGRATION_ROUNDTRIP=1`. The opt-in live suites are not enabled there and skip. Exactly
  which tests ran is in the job's skip list, which needs a signed-in account.
- **RAG integration run #1** (manual, no secrets) on `8a64718`: succeeded. Its last step fails
  unless exactly 4 tests ran and passed with none skipped, so it shows the real embedding model and
  pgvector retrieval working on a GitHub-hosted runner.
- **Live RAG end-to-end run #3** (`rag-e2e-live.yml`, manual and approval-gated) on `f164c04`
  (2026-10-27): succeeded. It exercised real embeddings, PostgreSQL + pgvector retrieval and one
  live Groq answer, checked for grounding and for citations against the retrieved source ids. Its
  last step fails unless exactly 2 tests ran and passed with none skipped; the maintainer reports
  the summary as `2 passed, 0 skipped, 0 failures, 0 errors`. The earlier runs #1 (`cc1a399`) and
  #2 (`9d5a78d`) failed on citation forms the parser did not yet accept (`【S1】`, then
  `【SOURCE 1】`), fixed in `9d5a78d` and `f164c04`. The job runs in the `groq-live` environment:
  one required reviewer and deployments from `main` only (repository admins can bypass the
  approval, GitHub's default). It covers one synthetic question: a smoke test of the live path, not
  an answer-quality evaluation.
- **Kubernetes smoke test run #2** (`k8s-smoke.yml`, manual) on `e75e7ed` (2026-10-27, 4m 32s):
  succeeded. On a GitHub-hosted runner it built the backend and React images (never pushed),
  loaded them into a disposable single-node kind cluster, and applied the committed manifests.
  Test-only substitutions were made at run time: the image tag, and identity-provider placeholders
  on the reserved `.invalid` domain, which are never contacted. The Secrets were generated for the
  run. Each step fails unless its check passes:
  - PostgreSQL with pgvector and Redis ready (`pg_isready`, `PONG`);
  - the migration Job complete (the `vector` extension present, Alembic at `0008`);
  - the backend's `/health/ready` reporting ready;
  - the frontend's `/` and its proxied `/health` answering;
  - `/api/v1/auth/me` returning 401 without credentials.

  The cluster was deleted afterwards. Run #1 (`c480369`) failed: Redis crash-looped (`setpriv:
  setresuid failed: Operation not permitted`) because it started as root with every capability
  dropped. `e75e7ed` runs it as the image's own `redis` user (999:1000), and in run #2 it started.
  `c480369` had already given the backend image a fixed numeric user (10001), which Kubernetes needs
  in order to check `runAsNonRoot`. **This shows the manifests deploy and start; it is not a
  staging or production deployment.** It used one node, no ingress or TLS, no real sign-in and no
  model call, the bundled in-cluster PostgreSQL and Redis instead of managed services, and nothing
  persisted after the run. **`3023c82` changed what this test deploys** (Redis now requires a
  password from the `aegisai-redis-secret` Secret; a data-tier NetworkPolicy; the workflow creates
  that Secret and checks that unauthenticated Redis access is refused). It has not been re-run
  since, so the current manifests are validated structurally only. Both runs carry GitHub's warning that the pinned `actions/checkout`
  (v4.4.0) targets the deprecated Node.js 20 and is being run on Node.js 24 instead (see remaining
  work).
- **Security scanning run #62** on `e75e7ed`: all four jobs completed (so did run #59 on `f164c04`
  before it). The scans were reporting-only then, so that was not a clean result; the reports of
  runs #59 and #62 have not been reviewed.
  What has been reviewed is in [security-scanning.md](security-scanning.md).

Reported by the maintainer, not re-run here: the two opt-in live Groq tests
(`backend/tests/integration/test_groq_live.py`: one completion, and one stream whose final chunk
must carry token usage) passed locally on 2026-10-25 (`2 passed`).

Mocked tests are labelled as such in their docstrings. `test_indirect_access_paths.py` and
`test_scoped_repositories.py` prove structure and delegation, **not** that a database hides another
user's rows. `tests/integration/test_data_isolation.py` is the test for that. It passed locally on
2026-11-01 against the isolated test database. It is included in CI's `test` job, and that job
succeeded in run #103, but whether this test ran there or was skipped is unknown (the log and its
skip list have not been inspected).

## Roadmap compliance (M0 to M9)

Each milestone is tracked on four separate axes. "Implemented" means the code exists and matches the
roadmap row; it says nothing about whether it works against real infrastructure. No row is
"complete": every one still needs integration evidence that could not be produced here.

| # | Milestone | Implementation | Automated tests (offline) | Integration evidence | Remaining blockers |
|---|---|---|---|---|---|
| M0 | Foundation & Architecture | implemented: typed, validated settings; JSON logs with request ids; consistent errors (422s no longer echo input); request-size limit (no Content-Type bypass); security headers; Alembic 0001 to 0008; SQL bound values hidden from errors and logs; an isolated test environment | pass | CI-reported green on `bcccb20` (run #103); the database-backed suites passed locally against `aegis_test` | Compose/Docker runs (not permitted locally) |
| M1 | LLM Gateway | implemented: provider-neutral gateway, Groq provider, model roles, retries with a `Retry-After` cap, total stream deadline, fixed client-facing error text (a reply cut off before any text has its own code, `llm_output_truncated`) | pass (scripted provider) | a live completion and a live stream with token usage passed locally (maintainer-reported, 2026-10-25), and a live completion through the gateway passed in CI (live RAG run #3); retries, `Retry-After` and the stream deadline not exercised live | the `safety` role is unused (decision D-1) |
| M2 | Conversational AI | implemented: chat, bounded history window (now loaded with a bounded query), SSE, usage per message; message order made total (finding R-4) | pass | `test_chat_flow.py` is included in the CI `test` job, which succeeded in runs #78 and #103; whether it ran there is unknown (log and skip list not inspected); its individual local result on 2026-11-01 was not recorded | CI's skip list unread; no deployed-stack run |
| M3 | Document Intelligence | implemented: PDF/DOCX/TXT/Markdown, magic bytes, expansion limits, XXE-safe DOCX parsing (pinned by a test), duplicate-upload advisory lock; text extraction in a separate, killable process with a deadline and a scrubbed environment (AIGSEC-003); `pypdf` 6.21.4 | pass (real extractors, real child processes) | `test_document_ingestion_flow.py` passed locally; it is included in the CI `test` job (succeeded in run #103), but whether it ran there is unknown (log and skip list not inspected) | the unique `(owner, checksum)` index needs an operator de-duplication first (ADR 016) |
| M4 | Embeddings | implemented: Sentence Transformers, pgvector column, dimension guard at startup, model/version stamping | pass (fake provider) | the real model with pgvector: RAG integration run #1 passed (4 tests, none skipped) | the model revision is not pinned (decision D-8); not run locally (no pgvector) |
| M5 | Production RAG | implemented: scoped retrieval, filters, threshold, context assembly with marker neutralization, citation validation (retrieval, not claim support), output guard on answers (pattern-based) | pass | real retrieval: RAG integration run #1 passed; a live-model answer, grounded and with validated citations, passed in live RAG run #3 on `f164c04` | one synthetic question only, and no answer-quality evaluation yet; citations prove retrieval, not support (D-5) |
| M6 | Agentic AI | implemented: LangGraph agent (`langgraph` 1.2.14), allowlisted tools, step/tool/time budgets, malformed-argument handling, per-user memory with TTL, caps and an owner row lock; memory written only on the user's explicit request and grounded in their words, recalled notes passed as data, never as a system message (AIGSEC-006); tool results redacted before the model sees them | pass | the database-backed agent and memory tests are included in the CI `test` job (succeeded in run #103); whether they ran there is unknown (log and skip list not inspected); no live-model agent run | a live agent run (needs a model); human approval is a decision (D-2) |
| M7 | MCP + A2A Multi-Agent | implemented: in-process MCP (any other transport fails closed; reported server identity checked), allowlisted A2A with size/deadline limits and validated responses, Agent Card URLs from configuration rather than the Host header, partial-failure isolation, stdio server fails closed | pass (mock transports) | none | a live multi-agent run (needs a model) |
| M8 | GenAI UI + APIs | implemented: React Copilot (four modes), Conversations, Documents, Memory, Operations, System Status (listed for administrators only); a Content-Security-Policy computed from the configured origins; legacy Streamlit (no sign-in; Markdown images neutralized); development-only preview, excluded from builds | pass | none in a browser | an identity provider (OIDC) for sign-in; a browser |
| M9 | Production / MLOps / Responsible AI | partial: Dockerfiles; Kubernetes manifests (non-root, no service-account tokens, a data-tier NetworkPolicy, Redis password from a Secret); CI with service-requiring integration tests and pinned actions; **blocking** security scans with narrow, expiring exceptions (D-9 decided); a shared Redis rate limiter (opt-in; Compose and Kubernetes select it); a per-call LLM input budget; an output guard; opt-in metrics; retrieval evaluation; runbooks | pass (static checks; the Redis limiter's real-Redis test was skipped locally because the local Redis was unavailable, and whether it ran in CI is unknown) | CI #103 and Security scanning #77 green on `bcccb20`; the manifests deployed and started once in a disposable kind cluster (smoke run #2 on `e75e7ed`), **before** `3023c82` changed them | no tracing/dashboards/alerts; no token budgets (D-10); no data-retention or other governance documents; the `safety` role unused (D-1); no branch protection on `main`; smoke test not re-run on the current manifests; manifests never applied to a staging or production cluster |

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

### Since the review (2026-10-27)

Each item has a regression test. During development, each test was also confirmed to fail when its
change is undone; those mutation checks were run separately and are not part of the committed test
suite. Only the live RAG test has also run against a live system (run #3, above). The Kubernetes
items have run in the disposable smoke-test cluster (run #2, above), which is not a live system.
None of the rest has run outside the offline tests.

| Change | Where | Regression test |
|---|---|---|
| No checkout leaves the job's token in `.git/config` (`persist-credentials: false`) | every workflow | `tests/unit/test_ci_workflow.py` |
| CI installs exactly the locked Python dependencies (`uv sync --locked`), as the images (`--frozen`) and the scans do | `.github/workflows/ci.yml` | `tests/unit/test_ci_workflow.py` |
| A live RAG end-to-end test (real embeddings, pgvector, one real Groq answer checked for grounding and citations) and a manual workflow that needs an approval and exposes the key to one step only | `tests/integration/test_rag_end_to_end_live.py`, `rag-e2e-live.yml` | `tests/unit/test_rag_e2e_live_workflow.py` (static); the live test passed in run #3 |
| A reply cut off before any text returns 502 `llm_output_truncated` with a fixed message, not the generic provider error | `app/core/exceptions.py` | `tests/unit/api/test_chat_endpoint.py`, `test_rag_endpoint.py` |
| System Status is listed for administrators only, and `/system` shows members a notice without calling the API | `frontend/web/src/` | `App.test.tsx`, `AuthGate.test.tsx` |
| A manual smoke test deploys the committed manifests to a disposable kind cluster, checks each layer and always deletes the cluster | `.github/workflows/k8s-smoke.yml` | `tests/unit/test_k8s_smoke_workflow.py` (static); the workflow passed in run #2 |
| The backend image runs as the fixed numeric user 10001:10001, so Kubernetes can verify `runAsNonRoot` (a user name cannot be checked, so the pods were refused); the uploads volume is given to group 10001 (`fsGroup`) | `Dockerfile`, `infra/kubernetes/backend-deployment.yaml` | `tests/unit/test_k8s_pod_security.py` |
| Redis runs as its image's own `redis` user (999:1000, non-root, `RuntimeDefault` seccomp, all capabilities still dropped); before, it crash-looped in smoke run #1 | `infra/kubernetes/redis-deployment.yaml` | `tests/unit/test_k8s_pod_security.py`; Redis started in run #2 |

### Security remediation (2026-11-01: `3023c82`, `9ac72f0`, `bcccb20`)

Each item has regression tests in the repository. What is known about running them:

- **Passed locally (2026-11-01):** the offline tests, and the database-backed tests against the
  local test services, except where a row says otherwise. The full backend run was 2333 passed and
  28 skipped; the skipped tests were not listed individually.
- **Included in CI:** every test below is under `backend/tests`, which CI's `test` job collects
  (`uv run pytest -v -rs`, with `AEGIS_REQUIRE_SERVICES=1`, so an unreachable PostgreSQL or Redis
  fails the job instead of skipping). The job succeeded in run #103.
- **Ran in CI: unknown.** The run #103 log and its skip list have not been inspected, so it is not
  confirmed that any particular regression test ran there rather than being skipped (other skip
  conditions, such as opt-in flags, still apply). A green job shows only that nothing failed.
- **Execution confirmed** only for the scan policy itself (AIGSEC-007): its blocking step ran in
  Security scanning runs #75 to #77 (#75 and #76 failed in it with exit code 1). That confirms the
  policy script ran in CI, not that its unit tests did.

None has run against a staging or production system. The CSP described in R-7 above is superseded
by AIGSEC-011.

| ID | Change | Where | Regression tests |
|---|---|---|---|
| AIGSEC-001 | Only a document's owner can share it with the organization; an administrator may still delete it or make it private (403 and an audit record otherwise) | `app/db/repositories/document_repository.py`, `app/api/v1/documents.py` | `tests/unit/auth/test_document_visibility_authorization.py`, `tests/integration/test_data_isolation.py` |
| AIGSEC-002 | Compose publishes PostgreSQL and Redis on `127.0.0.1` only; Redis requires a password | `docker-compose.yml` | `tests/unit/test_compose_security.py` (static; Compose not run) |
| AIGSEC-003 | Untrusted files parsed in a separate, killable process with a deadline | `app/documents/isolated_extraction.py` | `tests/unit/documents/test_isolated_extraction.py` (real child processes) |
| AIGSEC-004 | SQL bound values hidden from errors and logs | `app/db/session.py`, `alembic/env.py` | `tests/unit/test_sql_parameter_hiding.py` |
| AIGSEC-005 | Data-tier NetworkPolicy; Redis password from a Secret | `infra/kubernetes/` | `tests/unit/test_k8s_network_policy.py` (static; enforcement not verified on any cluster) |
| AIGSEC-006 | Memory provenance and consent; notes never a system message | `app/agents/`, `app/memory/` | `tests/unit/memory/test_memory_provenance.py` |
| AIGSEC-007 | Blocking security scans with expiring exceptions | `.github/workflows/security.yml`, `scripts/security_scan_policy.py` | `tests/unit/test_security_scan_policy.py`, `test_security_workflow.py`; runs #75 to #77 |
| AIGSEC-008 | Shared Redis rate limiter (atomic, keys hashed, fails closed) | `app/core/rate_limit.py` | `tests/unit/test_rate_limit_redis.py`; `tests/integration/test_rate_limit_redis.py` (real Redis): **skipped locally** on 2026-11-01 because the local Redis was unavailable, so it has not passed locally; included in CI's `test` job, but whether it ran in run #103 is unknown (log and skip list not inspected) |
| AIGSEC-009 | Per-call LLM input budget; analyst evidence cap; retries bounded | `app/llm/gateway.py`, `app/api/v1/analyst_agent.py`, `app/config.py` | `tests/unit/llm/test_input_budget.py` |
| AIGSEC-010 | Agent Card URLs from configuration; optional `ALLOWED_HOSTS` | `app/a2a/agent_card.py`, `app/main.py` | `tests/unit/a2a/test_agent_card_host_header.py` |
| AIGSEC-011 | Strict CSP from the configured origins; HSTS opt-in | `frontend/web/docker-entrypoint.sh`, `nginx.conf.template` | `tests/unit/test_frontend_entrypoint.py`, `test_frontend_proxy_config.py` (nginx not run) |
| AIGSEC-012 | Streamlit: Markdown images neutralized; legacy status stated | `frontend/streamlit/` | `frontend/streamlit/tests/test_safe_markdown.py` |
| AIGSEC-013 | MCP limited to the in-process transport; reported identity checked | `app/mcp/client.py` | `tests/unit/mcp/test_mcp_trust_boundary.py` |
| AIGSEC-014 | Malformed calculator, analyst, Agent Card and token-usage input fails one item | `app/agents/tools/calculator.py`, `app/a2a/`, `app/multi_agent/adapters.py` | `tests/unit/agents/test_tool_robustness.py` |
| AIGSEC-015 | Output guard: credential-like values and card/SSN-shaped numbers redacted from answers and tool results, streamed and stored alike | `app/safety/output_guard.py` | `tests/unit/safety/` |
| AIGSEC-016 | Runtime uploads and Redis snapshots ignored by Git | `.gitignore` | `tests/unit/test_gitignore_hygiene.py` |
| Test isolation | Tests never read `.env`, never reach the development database, and unit tests never reuse a pooled connection | `backend/tests/isolation.py`, `backend/tests/unit/conftest.py` | `tests/unit/test_isolation_guard.py` and others; `9ac72f0` fixed the CI failure of run #101 |
| Dependencies | `pypdf` 6.21.4, `pyasn1` 0.6.5, `langgraph` 1.2.14, `langgraph-sdk` 0.4.6 | `pyproject.toml`, `uv.lock` (`bcccb20`) | Security scanning run #77 (scans confirmed run); the backend suite locally (2333 passed, 28 skipped) |

## Security model: what is enforced, and where it is not

Known limitations:

1. **Database isolation is verified only in a local test database.** `test_data_isolation.py`
   passed locally against the isolated `aegis_test` database. It is included in CI's `test` job
   (service PostgreSQL), which succeeded in run #103, but whether it ran there is unknown (log and
   skip list not inspected). It has not run against a deployed database.
2. **`backend/scripts/mcp_stdio_server.py`** has no authentication. It now refuses to start unless
   `MCP_STDIO_USER_ID` + `MCP_STDIO_ORGANIZATION_ID` (one user's data) or
   `MCP_STDIO_ALLOW_UNRESTRICTED=true` (every organization's data) is set, but whoever can run it
   on the database host chooses the scope. It is not reachable through the API.
3. **Rate limits are per process unless the Redis limiter is selected.** The default
   (`RATE_LIMIT_BACKEND=memory`) counts per process: with several workers or replicas the effective
   limit multiplies, and a restart clears counts. A shared limiter exists (`RATE_LIMIT_BACKEND=redis`:
   one atomic script per check, hashed keys, refuses with 503 when Redis is unavailable); Compose and
   the Kubernetes ConfigMap select it. Its atomicity and cross-instance behaviour are tested against a
   real Redis, but several replicas under real load have not been tested. A `.env` copied from
   `.env.example` sets `memory`, which overrides Compose's default.
4. **Audit lines are ordinary logs**, not tamper-evident, and nothing alerts on them.
5. **No user-management API.** Accounts and roles are created by an operator command that writes to
   the database directly.
6. **Administrators see organization-wide document counts** in the operations summary (numbers only).
7. **Hiding admin-only pages is display only.** The web UI lists System Status for administrators
   only (the role comes from `/api/v1/auth/me` at sign-in), and a member who opens `/system` sees a
   notice. The API's 403 is what protects it. A role change reaches the UI at the next sign-in or
   page reload.
8. **Legacy data is invisible until assigned.** After migration 0006 and before the backfill,
   pre-existing conversations and documents match no user's scope.
9. **Not reviewed for a real deployment:** TLS termination, secrets management, data retention,
   and the identity provider's own configuration (the development realm file is for local use only).
   CORS now refuses `*` outside local development. Backup, restore and rollback are documented in
   [backup-restore-and-rollback.md](backup-restore-and-rollback.md); its referenced files exist, but
   the procedure itself has not been rehearsed.
10. **The legacy Streamlit UI has no sign-in**, so a backend with authentication refuses every request
   it makes; its main page says so. Untrusted text is rendered with Markdown images neutralized and
   raw HTML off (AIGSEC-012). The React app is the supported, authenticated interface. Whether to keep
   Streamlit is decision D-12.
11. **The bundled PostgreSQL manifest** runs with its image's default security context (its
   entrypoint starts as root to drop to `postgres`). The bundled Redis manifest now sets an explicit
   non-root pod security context (999:1000, `RuntimeDefault` seccomp, all capabilities dropped).
   Both are development/staging only (decision D-11).
12. **Cost controls are request counts, not tokens** (decision D-10). A per-call input cap
   (`LLM_MAX_INPUT_CHARS`) and the analyst evidence cap bound a single request, not a user's total.
13. **No branch protection on `main`** (GitHub API, 2026-11-01: `protected: false`, no rulesets). The
   blocking scans fail the run but cannot stop a push or a merge: runs #75 and #76 failed on commits
   that were already on `main`.
14. **Deployment settings with permissive defaults.** `ALLOWED_HOSTS` defaults to `["*"]` and is set in
   neither Compose nor Kubernetes (Kubernetes HTTP probes send the pod IP as the Host header, so
   restricting it also needs probe `httpHeaders`); `validate_for_serving` does not require
   `REDIS_PASSWORD` outside local development (the bundled Compose and Kubernetes Redis require one);
   `A2A_PUBLIC_BASE_URL` is unset in Kubernetes, so Agent Cards advertise `http://localhost:8000`.
15. **The output guard is pattern-based**, not complete secret or personal-data detection; e-mail and
   phone redaction is opt-in, and the `safety` model role is unused (decision D-1). Prompt injection
   is mitigated, not eliminated, and has not been red-teamed against a live model.
16. **NetworkPolicy enforcement depends on the cluster's network plugin** and has not been verified on
   any cluster.

## Migration readiness

*Fresh install.* `alembic upgrade head` runs 0001 to 0008 straight through (0007 passes because no row
is unowned). Then provision the first user (`scripts/provision_identity.py`).

*Existing database* (this project's own development database was last seen at 0004 with one
conversation and two messages, and has not been re-checked since; nothing has been migrated or
assigned by this work. The separate, isolated test database `aegis_test` is at 0008):

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
is the test for those. It is included in CI's `test` job with `RUN_MIGRATION_ROUNDTRIP=1`, and that
job succeeded in run #103, but whether this test ran there is unknown (log and skip list not
inspected); it has not run locally.

`make docker-migrate` and the Kubernetes migration job run `alembic upgrade head`; on a database with
unassigned rows they stop safely at 0006 with a message. Use steps 2 to 6 above instead.

## Blocked checks (need infrastructure that was not available or not permitted)

- Database-backed suites against a deployed database. They run locally against the isolated test
  database (since 2026-11-01). They are included in CI's `test` job, but which ones ran there is
  unknown (its skip list has not been inspected). The migration round trips are enabled only in CI,
  and whether they ran there is likewise unknown.
- Live OIDC: a real sign-in, token issuance by Keycloak, the audience mapper, silent renewal, and
  `iss` stability when the backend reaches the identity provider by another host name.
- Locally: Docker images, Compose, Kubernetes, Trivy and gitleaks (Docker is not permitted here). In
  CI the images are built and scanned (run #77), and Kubernetes smoke test run #2 deployed them to a
  disposable kind cluster, before `3023c82`.
- CI logs and scan artifacts: they need a signed-in account with admin rights.
- A staging environment: a real cluster with its own secrets, a disposable copy of its database, an
  identity provider, and rehearsals of backup, restore and rollback. Existing Kubernetes cluster
  selected as the intended staging target. Cluster identity, access, Kubernetes version, network
  plugin, ingress/TLS, secrets management, registry access and capacity remain unverified. No
  staging deployment has occurred. Cluster readiness must be assessed before deployment.
- Live model calls beyond the two local Groq tests and live RAG run #3: live agent and multi-agent
  runs, and the answer-quality evaluation metrics.
- The shared Redis rate limiter under real load with several replicas. A test of its atomicity
  against a single real Redis exists; it was skipped locally (local Redis unavailable), and whether
  it ran in CI run #103 is unknown.

## Remaining work, in priority order

1. Enable branch protection on `main` (repository admin): require the CI and Security scanning
   checks and pull requests, so a failing check blocks a merge.
2. Re-run `k8s-smoke.yml` on the current manifests (Redis password from a Secret, data-tier
   NetworkPolicy): last passed on `e75e7ed`, before `3023c82`.
3. Read CI's `test` job skip list once (it needs a signed-in account) to confirm which
   database-backed tests ran in run #103.
4. Deploy to a real staging environment with that environment's own secrets (the smoke test's
   disposable cluster and generated Secrets do not count). There, apply the migrations to a
   disposable *copy* of the staging database following the sequence above, then to the real one.
   Existing Kubernetes cluster selected as the intended staging target. Cluster identity, access,
   Kubernetes version, network plugin, ingress/TLS, secrets management, registry access and capacity
   remain unverified. No staging deployment has occurred. Cluster readiness must be assessed before
   deployment.
5. Real browser sign-in with Keycloak; provision the first administrator; confirm `/system/status` is
   403 for a member and 200 for an administrator, and that only the administrator's sidebar lists
   System Status.
6. In staging, rehearse a backup and restore and verify a rollback, following
   [backup-restore-and-rollback.md](backup-restore-and-rollback.md) (documented, never rehearsed).
7. Load and failure testing: behavior under realistic traffic, with several replicas (including the
   shared Redis rate limiter, implemented in `3023c82`), and when the database, Redis or the model
   provider is unavailable.
8. Scrape the opt-in `/metrics` endpoint in a real environment, add tracing, dashboards, and
   alerting on 5xx rates, rate-limit refusals, limiter failures and LLM errors (the metrics exist;
   see `observability.md`), and on repeated `not_found` audit outcomes. No tracing or error tracking
   exists in the code.
9. Deployment configuration: set `ALLOWED_HOSTS` (with probe `httpHeaders`) and
   `A2A_PUBLIC_BASE_URL` for the target environment, and require `REDIS_PASSWORD` outside local
   development.
10. Security-scan baseline: the scans block since `3023c82` (D-9 decided) and pass on `bcccb20`
    (run #77). Review the run #77 reports (artifacts need a signed-in account) for the non-blocking
    findings and for the gitleaks report, record them in `security-scanning.md`, and keep the
    exceptions file empty unless a finding has no fix.
11. Per-user token or cost budgets (D-10).
12. Ship audit logs to storage the application cannot alter; define retention.
13. A user-management API and UI (create/disable users, change roles) with its own audit events
    (`app/api/v1/admin.py` is a placeholder, not wired in).
14. UI: a sharing control for documents (the API supports it).
15. Review CORS, TLS, secrets handling and data retention for the target environment.
16. Responsible AI and governance: decide the `safety` role (D-1); a model-use policy, a
    data-retention policy, a review of the model provider's data handling and a responsible-AI
    review; an answer-quality evaluation set and prompt-injection red-team cases (live-model runs);
    semantic memory recall if wanted. The React Memory page lists, adds, edits and deletes notes.
17. Re-run `rag-e2e-live.yml`: its last pass (`f164c04`) predates `3023c82`, which added the output
    guard to the answer path, and `bcccb20`, which upgraded `pypdf` and `langgraph`. It checks one
    synthetic question, so answer quality still needs its own evaluation. Likewise, re-run
    `k8s-smoke.yml` after any change to the Dockerfiles, the manifests or the backend's start-up.
18. Move the pinned actions (`actions/checkout` v4.4.0 and others) to reviewed releases that target
    Node.js 24 (GitHub runs them on Node.js 24 with a deprecation warning), and the CodeQL
    `upload-sarif` action from v3, deprecated in December 2026, to v4. Dependabot pull requests
    exist for several of them.
19. Rename the scan steps in `security.yml` that still say "(reporting only)": they now block.
20. Give the timing-sensitive extraction-deadline test more headroom; it failed once under heavy
    load.

## Troubleshooting

| You see | Meaning | Where to look |
|---|---|---|
| `401` | no, expired or invalid token | `auth.denied` log lines (reason, request id) |
| `403` on most routes | valid token but the identity is not linked to a user, or the user/organization is disabled | `auth.denied` (reason); an unlinked identity is linked with `scripts/provision_identity.py` (try `--dry-run` first); that script refuses to change a disabled user or organization, and no API re-enables one yet (see remaining work #13) |
| `403` on `/system/status` | the caller is a `member`; the page is for administrators (the web UI does not list it for members) | by design |
| `502` with code `llm_output_truncated` | the model used its whole output budget (often on hidden reasoning) before writing any text; the same request stops at the same limit, so it is not retried | `llm_output_truncated` warning lines; try a shorter question, and review `PRIMARY_LLM_MODEL` / `FAST_LLM_MODEL` if it recurs |
| `403` on `PATCH /documents/{id}/visibility` | an administrator tried to share a member's document; only its owner can (AIGSEC-001) | the `audit` line with outcome `forbidden` |
| `413` with code `llm_input_too_large` | the prompt is over `LLM_MAX_INPUT_CHARS`; refused before any provider call | `llm_input_too_large` warning lines |
| `400` "Invalid host header" | the request's Host is not in `ALLOWED_HOSTS` | `ALLOWED_HOSTS`; probe `httpHeaders` in Kubernetes |
| `404` on a resource you believe exists | it exists but is not yours (or is private to someone else); the API does not say which | the `audit` line with outcome `not_found` |
| `429` with `Retry-After` | a rate limit; wait or raise the `RATE_LIMIT_*` setting | `audit` line `rate_limit.exceeded` (warning) |
| `503` on a protected route | authentication is not configured, the key set is unreachable, the database failed, or the rate limiter could not enforce (with `RATE_LIMIT_BACKEND=redis`, Redis is unreachable or slow) | `auth.unavailable` / `rate_limit.unavailable` error lines |
| old conversations/documents "missing" after upgrading | unowned legacy rows are invisible until the backfill | `scripts/assign_legacy_data.py --email <user> --organization "<name>" --dry-run` reports the counts (both options are required); see the migration steps above |

Find audit events with the JSON field `audit_action` (for example `document.deleted`).
