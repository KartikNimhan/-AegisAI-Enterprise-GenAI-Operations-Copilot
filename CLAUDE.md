# AegisAI – Enterprise GenAI Operations Copilot: project context

This file is the **single source of project context and progress**. Update it after every
meaningful task with verified changes and actual test results. Do **not** create `UPDATE.md`,
`CHANGES.md` or any other progress-tracking file.

Last updated: 2026-11-05 (PR #37 Trivy blocker: `libexpat>=2.10.0-r0` floor added to the React
frontend image; local, uncommitted, CI not yet re-run). Earlier: 2026-11-04 (M10 acceptance-review
remediation of findings M1, M2, M3, L1, L7, L8 and L10; local, uncommitted). Earlier: 2026-11-04
(M10.2 shell and Overview; M10.6 scoped original-file download and document viewer; M10.8 page fixes
and lint ratchet 1; M10.7 offline evidence evaluation; M10.9 section metadata; final verification;
local). Earlier: 2026-11-03 (full M10 mission started under owner authorization; M10.4 T4–T8 backend
implemented locally: citation saving, `message_id`, citations on reopened conversations, the
citation passage endpoint, isolation tests (written, not run), ADR 018).
Earlier updates: 2026-11-03 (M10.4 T3 implemented locally: `MessageCitation` model and additive
migration `0009`, written and checked offline only, not applied to any database); 2026-11-03 (M10.4
T3 read-only review; similarity-range stop and owner decision, Option A); 2026-11-03 (M10.4 T2
formally accepted; post-review notes recorded); 2026-11-03 (M10.4 T2 implemented locally: additive
RAG source fields and `invalid_citations` on the final stream event; `message_id` deferred to T4;
awaiting owner review); 2026-11-03 (M10.4 read-only assessment of `message_id` timing: deferred to
T4); 2026-11-03 (M10.4 T1 formally approved; final T1 test results and the adversarial
reconstruction test improvement recorded); 2026-11-03 (M10.4 approved decisions and database
restrictions recorded; T1 awaiting owner review); 2026-11-03 (M10.4 T1: per-source passage metadata
in the context assembler, on branch `feature/m10-citation-passage-metadata`; local only, nothing
committed); 2026-11-02 (M10.4 read-only architecture assessment); 2026-11-02 (M10.0 corrective pass
after the independent review); 2026-11-02 (M10.0 testing and quality foundations implemented
locally); 2026-11-02 (M10 design decisions recorded; M9 paused); 2026-11-02 (M10 plan recorded:
approved, not implemented); 2026-11-02 (M9, Step 1: repository synchronization and fresh baseline).

## Working rules

- Record only verified facts. Never state that a test passed unless it was run and passed; mark
  anything that could not be checked as **UNKNOWN** or **not tested**.
- A milestone is **Completed** only when its acceptance criteria have been verified with evidence.
  Status values: Not Started, In Progress, Blocked, Completed.
- Do not start a later phase while its predecessor has unresolved blockers, unless the owner
  explicitly approves it.
- Keep the official M0–M9 roadmap below intact; M9.1–M9.7 are sub-milestones of M9, not
  replacements.
- M10 (premium frontend and citation experience) is a separate initiative that the owner approved
  to run alongside M9 (2026-11-02). Keep M9 and M10 milestones, branches, acceptance criteria and
  status separate. M10 progress never completes M9 or implies production readiness.
- **M9 and the Oracle Cloud deployment are PAUSED (not cancelled)** as of 2026-11-02, while M10
  frontend work is prioritized. Do not start Oracle deployment or other M9 tasks without the
  owner's approval. M9 statuses, open items and history stay as recorded.
- Design reviews may use the Apple Design Skill only as described in M10 decision 3. WCAG 2.2 AA
  and the project's tests are binding. The skill is never a citation or evidence check.
- The owner handles Git: do not stage, commit, push, reset or rebase unless explicitly asked.
- Never read or print `.env`, `.env.test` or `.env.local`, and never expose keys, passwords or
  tokens. Do not make live or billed LLM calls unless explicitly approved.
- Docker is not run on the development machine (Windows, no Docker or WSL).
- Demos and ad-hoc scripts must not run application startup paths that trigger network access
  (the app lifespan warms up the embedding model, which can contact the Hugging Face Hub) unless
  explicitly approved (added 2026-11-03; see the M10.4 T2 post-review notes).

### Protected files

| Path | Rule |
|---|---|
| `docs/operations/production-readiness.md` | Modify only with explicit owner approval |
| `docs/operations/backup-restore-and-rollback.md` | Keep unchanged; SHA-256 `f17913bff06a80980fead8ba03460a95f4442668e05bb86a71a72ea61ab6dfad` |
| `docs/technical-handover/` (18 files) | Untracked; never stage, move, delete or overwrite |

## Project summary

FastAPI modular monolith (`backend/app`): SQLAlchemy async + asyncpg, PostgreSQL 16 with pgvector,
Alembic migrations 0001–0008 (plus `0009`, written locally in M10.4 T3 on 2026-11-03 and not yet
applied to any database), Redis (optional shared rate limiter), OIDC/JWT authentication
(Keycloak-compatible), tenant isolation through `AccessScope`, a provider-neutral LLM gateway (Groq),
Sentence Transformers embeddings (`all-MiniLM-L6-v2`, CPU), RAG with citations, LangGraph agents
with per-user memory, MCP (in-process) and A2A multi-agent workflows. UIs: React + Vite
(`frontend/web`, the default) and legacy Streamlit (`frontend/streamlit`). Packaging: uv
(`pyproject.toml`, `uv.lock`), npm (`frontend/web/package-lock.json`). Deployment artifacts:
Dockerfiles, `docker-compose.yml`, Kubernetes manifests in `infra/kubernetes/`.

Key references: `README.md` (roadmap), `docs/architecture/system-design.md`, ADRs 001–019 in
`docs/architecture/decisions/` (open decisions D-1 to D-12 in ADR 017; ADR 018 citation
persistence; ADR 019 claim-level evidence evaluation, **Proposed**), and the runbooks in
`docs/operations/`: production readiness, backup/restore/rollback, observability, security scanning.

## Official roadmap (M0–M9, from `README.md`)

| Milestone | Name | Scope |
|---|---|---|
| **M0** | Foundation & Architecture | FastAPI, PostgreSQL, Docker, config, logging, testing |
| **M1** | LLM Gateway | Groq, multiple models, streaming, retries, provider abstraction |
| **M2** | Conversational AI | Chat, prompt engineering, history, SSE streaming, token tracking |
| **M3** | Document Intelligence | PDF/DOCX/TXT, extraction, normalization, chunking, storage |
| **M4** | Embeddings | Sentence Transformers, vectors, pgvector, similarity, batching, versioning |
| **M5** | Production RAG | Retrieval, metadata filtering, top-K, context assembly, citations |
| **M6** | Agentic AI | LangGraph, tool calling, workflows, state, memory |
| **M7** | MCP + A2A Multi-Agent | MCP servers/tools, A2A communication, multi-agent orchestration |
| **M8** | GenAI UI + APIs | Streamlit/React, WebSockets/SSE, chat UI, document UI, dashboards |
| **M9** | Production / MLOps / Responsible AI | Docker, Kubernetes, CI/CD, monitoring, evaluation, security, governance |

M0–M8 are implemented and pass their offline test suites. None is verified against a deployed
environment; see the per-milestone evidence in `docs/operations/production-readiness.md`.

## Current repository state (verified 2026-11-02; updated 2026-11-03)

- **Current state (verified 2026-11-05):**
  - the owner committed the M10 work as **`8d242dc`** ("feat(m10): deliver enterprise copilot UI
    and citation persistence") on `feature/m10-citation-passage-metadata`, on top of `bad9fec`;
    **PR #37** is open (owner);
  - working tree: **2 modified** (`frontend/web/Dockerfile`,
    `backend/tests/unit/test_frontend_proxy_config.py`; the libexpat fix below) plus this file,
    and **1 untracked** path (`docs/technical-handover/`); nothing staged;
  - local `aegis_test` still at `0009`.
- **State 2026-11-04, after the pre-PR cleanup (superseded by the commit above):**
  - branch `feature/m10-citation-passage-metadata` at `bad9fec`;
  - **73 modified and 44 untracked paths** (including `CLAUDE.md` and `docs/technical-handover/`);
  - **nothing staged, committed or pushed**;
  - local `aegis_test` at **`0009`**;
  - backend integration **123 passed, 25 skipped**; backend unit **2,463 passed, 1 skipped**
    (2,461 before the L3 tests);
  - both isolation suites (`test_citation_isolation.py`, `test_document_file_isolation.py`)
    passed;
  - **the migration round trip is pending in CI**.
- **Update 2026-11-04 (owner-authorized migration):** the local **`aegis_test` is now at `0009`**
  (it was `0008`), migrated through `scripts/test_db.py migrate --yes`. No other database was
  touched. Production migration is **not** authorized. See the "M10 database verification
  record".
- **Update 2026-11-04 (after the review remediation; superseded by the current state above):**
  at that time 71 modified and 43 untracked paths, with `aegis_test` still at `0008`.
- **Update 2026-11-03:**
  - The M10.0 changes were committed by the owner (`417943f`) and merged into `main` through PR
    #36 (`bad9fec`). On 2026-11-03, local `main` and `origin/main` were both at `bad9fec`.
  - The result of PR #36's CI run has **not** been checked in this project document (UNKNOWN).
  - Branch `feature/m10-citation-passage-metadata` was created from `bad9fec` for M10.4 T1. It
    holds two uncommitted modified files (see the M10.4 T1 record). Untracked: `CLAUDE.md` and
    `docs/technical-handover/`. Nothing is staged or committed.
  - Later on 2026-11-03, M10.4 T2 was implemented on the same branch. It holds **10** uncommitted
    modified files: the 2 T1 files plus 8 T2 files (see the M10.4 T2 record). Still nothing staged
    or committed; still at `bad9fec`.
  - Later on 2026-11-03, M10.4 T3 was implemented on the same branch: **15** modified files (the
    10 T1/T2 files plus 5 T3 files) and **3** new untracked T3 files (see the M10.4 T3 record).
    Still nothing staged or committed; still at `bad9fec`.
  - **The local `aegis_test` database is still at `0008`** (no migration was applied). The code's
    newest migration is now `0009`, so the local database-backed integration tests will refuse to
    run until `aegis_test` is migrated, which needs separate owner approval.
- The items below are the 2026-11-02 record, kept for history.
- Branch `main`, HEAD `d55421d` (`Merge pull request #21 ... pydantic-2.14.1`), equal to
  `origin/main`.
- **Working tree (updated 2026-11-02, after the M10.0 corrective pass; superseded by the
  2026-11-03 update above):** NOT clean. It holds the uncommitted M10.0 changes on local `main`.
  - Modified: `.github/workflows/ci.yml`; in `frontend/web/`: `.dockerignore`, `.gitignore`,
    `.oxlintrc.json`, `package.json`, `package-lock.json`, `tsconfig.json`, `vite.config.ts`.
  - Untracked: `CLAUDE.md`; in `frontend/web/`: `e2e/`, `playwright.config.ts`,
    `tsconfig.e2e.json`, `src/styles/tokens.contrast.test.ts`, `src/test/axe.ts`,
    `src/test/jest-axe.d.ts`, `src/test/a11y.pages.test.tsx`, `src/test/a11y.components.test.tsx`;
    plus the 18 handover files in `docs/technical-handover/`.
  - Nothing is staged or committed.
- When synchronized (before M10.0), the working tree was clean apart from
  `docs/technical-handover/`.
- Synchronization: `git fetch origin`, then `git merge --ff-only origin/main` fast-forwarded
  `f131aa6` to `d55421d` (35 commits; 8 tracked files: the 4 workflows, `pyproject.toml`, `uv.lock`,
  `frontend/web/package.json`, `package-lock.json`). Before the merge: 0 commits ahead, no upstream
  path under `docs/technical-handover/` or named `CLAUDE.md`, and both protected docs unchanged
  upstream. The SHA-256 of all 18 handover files and both protected docs matched before and after.
- The merged Dependabot pull requests (#21–#27, #29–#35, 2026-11-01 to 11-02):
  - Python: fastapi 0.162.0, pydantic 2.14.2 (pydantic-core 2.50.2), asyncpg 0.32.0,
    a2a-sdk 1.3.0, ruff 0.17.1.
  - Frontend: react-dom 19.3.1, vite 8.3.5, vitest 5.0.5, oxlint 1.90.0.
  - Actions: setup-uv v10.3.3, setup-node v7.1.0, setup-buildx v4.4.1, build-push v7.4.0,
    upload-sarif v4.39.1.
- Local environments synced to the committed lock files (owner-approved, 2026-11-02):
  `uv sync --locked --all-groups` (6 packages updated) and `npm ci` in `frontend/web`
  (`found 0 vulnerabilities`). No tracked file changed.
- Earlier work on `main`: AIGSEC-001 to 016 security remediation (`3023c82`), unit-test
  connection isolation (`9ac72f0`), Python advisory fixes for pypdf, pyasn1, langgraph and
  langgraph-sdk (`bcccb20`), production-readiness doc reconciliation (`f131aa6`).

## Baseline test results (2026-11-02, on `d55421d`, Windows, Python 3.12, Node 24.14.0)

| Command | Result |
|---|---|
| `uv run ruff check .` | pass: "All checks passed!" |
| `uv run ruff format --check .` | pass: 513 files already formatted |
| `uv run pyright` | pass: 0 errors, 0 warnings, 0 informations |
| `uv run pytest -q -rs -p no:cacheprovider` (backend) | **2333 passed, 28 skipped, 0 failed** (330 s, exit 0) |
| `uv run --group frontend pytest frontend/streamlit/tests -q -rs -p no:cacheprovider` | 36 passed (exit 0) |
| `npm run lint` (oxlint, `frontend/web`) | pass with 3 warnings: `only-export-components` in `StatusBadge.tsx:12`; `set-state-in-effect` in `SystemStatusPage.tsx:27` and `DocumentsPage.tsx:30` |
| `npm run build` (`tsc -b && vite build`) | pass (TypeScript type check included) |
| `npm run test` (vitest) | 18 files, 144 tests passed |

The backend's 28 skipped tests (all by design or environment; none failed):
- **Opt-in live or real-model flags not set (18):**
  - `RUN_EMBEDDING_INTEGRATION` (5): `test_evaluate_runner`, `test_recall_at_k`,
    `test_embedding_model_live`, `test_rag_pipeline_live`, `test_mcp_stdio_live`;
  - `GROQ_API_KEY` empty (6): `test_groq_live` ×2, `test_agent_live` ×2, `test_a2a_live`,
    `test_multi_agent_live`;
  - `RUN_A2A_LIVE_INTEGRATION` (2), `RUN_MCP_STDIO_INTEGRATION` (2),
    `RUN_MULTI_AGENT_LIVE_INTEGRATION` (1), `RUN_RAG_E2E_LIVE` (2).
- **`RUN_MIGRATION_ROUNDTRIP` not set (2):** `test_identity_migration`, `test_ownership_migration`.
- **Redis not running locally (7):** `test_rate_limit_redis` ×5, plus 2 tests gated by
  `tests/integration/requirements.py`. Local PostgreSQL (the isolated `aegis_test` database) was
  reachable, so the database-backed tests ran.
- **1 by design:** `test_docs_gating_and_request_id.py:55` (the HTTP client cannot send that
  header value).

**Not tested locally:** the real-Redis rate limiter, the migration round trips, live LLM, embedding,
A2A and MCP paths, Docker images, Compose, Kubernetes, Trivy and gitleaks.

**Flaky test:** the timing-sensitive extraction-deadline test (AIGSEC-003) failed once under heavy
load in an earlier session; it passed in this run. It is still flaky.

## CI, security and branch protection (verified through the public GitHub API, 2026-11-02)

- The `CI` workflow has 7 jobs: `lint`, `typecheck`, `test`, `frontend-react-test`,
  `frontend-streamlit-test`, `docker-build`, `k8s-manifests`.
- The `Security scanning` workflow has 4 blocking jobs: `Python dependency audit (pip-audit)`,
  `npm dependency audit`, `Secret scan (gitleaks, redacted)`, `Container image scan (Trivy)`.
- Both run on `push` and `pull_request` to `main`; Security scanning also runs weekly and on
  manual dispatch. No job is conditional or depends on another job.
- Ruleset `main-branch-protection` (active since 2026-11-01 15:40):
  - blocks deletion and non-fast-forward pushes;
  - requires a pull request (0 approvals, conversation resolution required);
  - requires all 11 checks from the GitHub Actions app, with branches up to date.
  - Its bypass list is **UNKNOWN** (it needs an admin account to read).
- On `d55421d`: CI #151 and Security scanning #125 succeeded, and every push and pull-request run
  since `bcccb20` succeeded. The run logs, skip lists and scan reports have **not** been read
  (they need a signed-in account).
- The Kubernetes smoke test last passed in run #2 on `e75e7ed`, and the live RAG test in run #3 on
  `f164c04`. Neither has been re-run since `3023c82` or the dependency merges.
- `actions/checkout` is still v4.4.0, which targets Node 20.
- GitHub's Dependabot, code-scanning and secret-scanning alert pages have **not** been reviewed.

## Security findings status

- AIGSEC-001 to 016: remediated in `3023c82`, with regression tests (see the security remediation
  table in `docs/operations/production-readiness.md`). None verified on a deployed system.
- Python advisories (11, in pypdf, pyasn1, langgraph and langgraph-sdk): fixed in `bcccb20`.
  Security scanning has passed since run #77.
- Open: the scan reports (Trivy medium and low findings, unfixed CVEs hidden by `ignore-unfixed`)
  have not been read. pip-audit cannot audit `torch` (`+cpu` build, not on PyPI).

## M9 – Production Readiness, MLOps and Responsible AI

> **PAUSED (not cancelled), 2026-11-02:** M9 and the Oracle Cloud deployment are on hold while M10
> frontend work is prioritized. Nothing below is cancelled or completed by the pause. Resume only
> with the owner's approval.

### M9 status table

| Sub-milestone | Status | Notes |
|---|---|---|
| M9.1 CI and Security Baseline | In Progress (substantially verified) | Open: GitHub alert review, scan-report review, ruleset bypass list, `actions/checkout` Node 20 |
| M9.2 Production Configuration and Deployment Preparation | Not Started | Step 1 (sync and baseline) done as its prerequisite |
| M9.3 Staging Deployment | Not Started | Depends on M9.2 |
| M9.4 Observability and LLMOps | Not Started | Depends on M9.3 for live evidence |
| M9.5 Responsible AI and Enterprise Safeguards | Not Started | |
| M9.6 Advanced GenAI Capabilities | Not Started | |
| M9.7 Production Release and Operations | Not Started | Depends on M9.3 and M9.4 |

### M9.1 – CI and Security Baseline

Status: **In Progress (substantially verified)**.

Scope: dependency updates and vulnerability remediation; GitHub branch protection and required
checks; CI workflows and automated testing; Python and npm dependency audits; container
vulnerability scanning; secret scanning; GitHub Dependabot, Code Scanning and Secret Scanning alerts.

Tasks:
- [x] Remediate the Python advisories (`bcccb20`); Security scanning #77 and later green.
- [x] Merge pending Dependabot updates (#21–#27, #29–#35); CI #151 and Security #125 green on `d55421d`.
- [x] Make the scans blocking with expiring exceptions (AIGSEC-007, D-9).
- [x] Activate branch protection requiring all 11 checks (ruleset `main-branch-protection`).
- [x] Fresh local baseline on `d55421d` (see Baseline test results).
- [ ] Review the GitHub Dependabot, Code Scanning and Secret Scanning alert pages (needs a signed-in account).
- [ ] Read the latest scan reports (Trivy, pip-audit, npm, gitleaks) and record non-blocking findings in `docs/operations/security-scanning.md`.
- [ ] Confirm the ruleset's bypass list.
- [ ] Read one CI `test` job skip list to confirm which database-backed tests ran.
- [ ] Move `actions/checkout` to a reviewed Node 24 release; rename the scan steps that still say "(reporting only)".

Acceptance criteria:
- All 11 required checks pass on `main` and block a failing pull request (checks pass; blocking verified by the ruleset configuration).
- 0 open Critical or High Dependabot, code-scanning or secret-scanning alerts, or each one documented with an expiring exception.
- The scan reports have been reviewed and their findings recorded.
- No bypass actor, or each one documented.

### M9.2 – Production Configuration and Deployment Preparation

Status: **Not Started**.

Scope: environment-variable and configuration validation; secrets management; Docker image hardening
and multi-architecture builds; database migration verification; PostgreSQL and pgvector readiness;
Redis configuration and authentication; ARM64 compatibility and resource validation for OCI; image
registry and release pipeline.

Already verified (2026-11-02, by reading files and public registries; nothing built):
- All 139 locked packages have Linux ARM64 or pure-Python wheels (`torch 2.14.1+cpu` has a
  `manylinux_2_28_aarch64` wheel).
- The base images `python:3.12-slim`, `node:22-slim`, `pgvector/pgvector:pg16`, `redis:7-alpine`
  and the digest-pinned `nginxinc/nginx-unprivileged:1.30.6-alpine` all publish `arm64`.
- CI builds amd64 images only and pushes nothing; the manifests use `REPLACE_WITH_TAG`
  placeholders.

Tasks:
- [ ] Choose an image registry (OCIR or GHCR) and a tagging scheme (commit SHA, image digest in the manifests).
- [ ] Release workflow: build linux/amd64 and linux/arm64 (native ARM runner preferred), push, and Trivy-scan both architectures.
- [ ] Decide whether to bake the embedding model into the image, or pin its revision and cache it (D-8).
- [ ] Pin the remaining base images by digest.
- [ ] Validate the production configuration: `validate_for_serving`, `ALLOWED_HOSTS`, `A2A_PUBLIC_BASE_URL`, a required `REDIS_PASSWORD`, `ENVIRONMENT`.
- [ ] Secrets management design (for example OCI Vault plus a sync mechanism, or a documented manual process); no secrets in Git.
- [ ] Run the migration round trips (`RUN_MIGRATION_ROUNDTRIP=1`) against a disposable PostgreSQL with pgvector.
- [ ] Measure resources on ARM64: backend memory after model warm-up and during ingestion (current limit 1 Gi), PostgreSQL and Redis.
- [ ] Add resource limits to the migration Job; consider a startup probe for the backend.

Acceptance criteria:
- Multi-architecture images (amd64 + arm64) are published by digest, and both architectures pass the blocking Trivy policy.
- The ARM64 backend image starts, `/health` returns 200, and the model warm-up completes within the measured memory limit.
- The migration round trips pass, with the result recorded.
- A documented secrets procedure exists, and no example secret is used outside local development.

### M9.3 – Staging Deployment

Status: **Not Started**.

Target: Oracle Cloud Infrastructure Always Free, subject to verified resource and service
availability. Do not assume Kubernetes is required for the initial Always Free deployment; evaluate
it against the actual resource limits (Docker Compose on a single Ampere A1 VM may be appropriate first).

Scope: prepare the deployment environment; deploy (Docker Compose initially if appropriate for the
selected VM); validate application start-up and health endpoints; verify authentication and OIDC;
verify document ingestion and RAG; verify agent and multi-agent workflows; verify API functionality
and database connectivity; validate Redis, networking, TLS and secrets.

Ampere A1 limits (Always Free tenancy): 2 OCPUs and 12 GB RAM in total (source: Oracle's official
Always Free resources page, checked 2026-11-02).

Facts to confirm (from general knowledge of OCI's terms, not yet verified):
- 200 GB of block storage including boot volumes.
- Block volumes have a minimum size of about 50 GB.
- One free flexible load balancer at 10 Mbps.
- Idle Always Free instances may be reclaimed.
- ARM capacity can be unavailable in a region.

Tasks:
- [ ] Verify OCI account limits, region capacity, storage and networking (record what was observed).
- [ ] Decide between Compose and Kubernetes against the measured resources (M9.2).
- [ ] Provision the VM or cluster, firewall/security lists, DNS and TLS.
- [ ] Deploy the secrets, PostgreSQL with pgvector, Redis with a password, the backend and the frontend; run the migrations.
- [ ] Deploy or connect an OIDC provider; provision the first administrator (`scripts/provision_identity.py`).
- [ ] Verify end to end: health endpoints, sign-in, upload and ingestion, a RAG answer with citations, an agent run, a multi-agent run, `/system/status` access control.

Acceptance criteria:
- The staging URL is served over TLS with valid certificates.
- `/health` and `/health/ready` return 200.
- A real OIDC sign-in works; a member gets 403 and an administrator 200 on `/system/status`.
- Document upload leads to a cited RAG answer; one agent and one multi-agent workflow succeed (live-model calls approved by the owner).
- Redis requires authentication, the database is not reachable from the internet, and no secret is in Git.

### M9.4 – Observability and LLMOps

Status: **Not Started**.

Scope: structured application logging; distributed tracing and error tracking; metrics,
dashboards and alerts; per-user and per-tenant token/cost tracking; usage budgets and rate
controls; prompt and model versioning; LLM answer-quality evaluation; provider fallback and failure
handling; live RAG and agent evaluation.

Existing: structured JSON logs with request ids, opt-in Prometheus `/metrics`, request-count rate
limits, retrieval evaluation (Recall@K). Missing: tracing, error tracking, dashboards, alerts,
token/cost budgets (D-10), prompt versioning, answer-quality evaluation.

Tasks:
- [ ] Scrape `/metrics` in staging; add dashboards and alerts (5xx, limiter failures, rate-limit refusals, LLM errors).
- [ ] Add tracing and error tracking (choose tools that fit Always Free).
- [ ] Per-user and per-tenant token and cost accounting with budgets (decide D-10).
- [ ] Version prompts and models; record them with each answer.
- [ ] An answer-quality evaluation set; live RAG and agent evaluation runs (owner-approved, billed).
- [ ] Provider fallback and failure handling (timeouts, 429/5xx) with tests.

Acceptance criteria:
- An induced failure triggers its alert in staging.
- A trace spans an API request through retrieval and the LLM call.
- A budget overrun is refused, with a test and an audit record.
- An evaluation report with a baseline is recorded, and live RAG passes on the current `main`.

### M9.5 – Responsible AI and Enterprise Safeguards

Status: **Not Started**.

Scope: prompt-injection testing; tenant isolation and authorization testing; data-retention and
deletion policies; access-control verification; auditability and audit-log review; Responsible AI
policies and red-team test cases; safe handling of retrieved documents and tool outputs.

Existing: offline tenant-isolation tests (`test_data_isolation.py`, passed locally), output guard,
context-marker neutralization, memory provenance (AIGSEC-006), audit events.

Tasks:
- [ ] A prompt-injection and red-team test set (documents, tool outputs, memory), run against a live model.
- [ ] Tenant-isolation and authorization tests against the staging database.
- [ ] Data-retention and deletion policies, with implementation (conversations, documents, memories, audit logs).
- [ ] Audit logs shipped to storage the application cannot alter; a review procedure.
- [ ] Decide D-1 (the `safety` role) and D-2 (human approval for sensitive tools); write a model-use and Responsible AI policy.

Acceptance criteria:
- The red-team suite passes at a recorded rate, with failures triaged.
- Cross-tenant access is denied in staging (tested).
- The retention policy is documented and enforced by a test.
- The audit trail is immutable and reviewable.

### M9.6 – Advanced GenAI Capabilities

Status: **Not Started**.

Scope: hybrid retrieval; reranking; semantic memory recall; semantic caching.

**Important distinction:** semantic memory recall and semantic caching are separate capabilities,
with separate designs, implementation tasks and acceptance criteria.

- Current memory recall (`MemoryService.recall`) ranks notes by word overlap, not by embeddings.
- No semantic cache exists.

Tasks:
- [ ] Hybrid retrieval (lexical + vector) with evaluation against the current baseline.
- [ ] Reranking with measured quality and latency impact.
- [ ] **Semantic memory recall:** design (embedding per memory, per-user scope, TTL and consent kept), implementation, tests.
- [ ] **Semantic caching:** a separate design and implementation. It must have:
  - tenant isolation, and permission-aware cache keys (user, organization, document visibility);
  - invalidation when a document or its visibility changes;
  - a TTL, similarity thresholds and freshness checks;
  - protection against cross-user data leakage.

Acceptance criteria:
- Hybrid retrieval and reranking improve Recall@K or answer quality on the evaluation set, with the results recorded.
- Semantic memory recall returns only the user's own unexpired notes, ranked by similarity (tested).
- Semantic caching:
  - no cross-user or cross-tenant hit (tested);
  - a document change or a visibility change invalidates the affected entries (tested);
  - the hit rate and staleness are measured.

### M9.7 – Production Release and Operations

Status: **Not Started**.

Scope: automated database backups; backup restoration rehearsal; deployment rollback testing; load
and performance testing; failure and resilience testing; production deployment approval;
production monitoring and operational runbooks.

Existing: a manual backup, restore and rollback runbook (`pg_dump -Fc`), never rehearsed.

Tasks:
- [ ] Scheduled backups stored off the node (for example in object storage), with retention.
- [ ] A restore rehearsal into a disposable database; a timed rollback to the previous image digest.
- [ ] Load and performance tests (several replicas, the shared Redis limiter).
- [ ] Failure tests (database, Redis, model provider unavailable).
- [ ] A production approval checklist; final operational runbooks.

Acceptance criteria:
- A restored database matches the source row counts.
- The rollback time and recovery objectives are recorded.
- Load-test thresholds are met.
- Failure behaviour matches the runbooks.
- Written production approval from the owner.

## M10 – Premium Frontend and Citation Experience (every phase implemented locally; none Completed)

M10 is a separate initiative, not part of the official M0–M9 roadmap. It was approved on 2026-11-02
to run alongside M9 (see Working rules).

**Current status (reconciled 2026-11-04, after the M10 acceptance review):**
- **M10.0** is merged (PR #36, `bad9fec`). **M10.1–M10.9** are implemented locally on
  `feature/m10-citation-passage-metadata` and are **uncommitted**. The owner handles Git.
- **No phase is Completed.** Each still lacks evidence only the owner can provide: a GitHub CI run;
  `aegis_test` migrated to `0009` with the integration suite run; a human visual and screen-reader
  review; and the D-5 decision (M10.7). See "M10 acceptance status" below.
- The status table and the per-phase checklists below agree with this. The older per-task records
  further down are kept as history; where a later record supersedes one, it says so.

### Current state relevant to M10 (verified 2026-11-02 by reading code; UI not rendered; historical, superseded by the M10 records below)

- Frontend:
  - stack: React 19, React Router 7, OIDC sign-in, Vite 8, TypeScript; CSS modules plus
    `src/styles/tokens.css`; no component library;
  - tests (before M10.0): Vitest and Testing Library (144 tests), with no automated
    accessibility, Playwright or visual tests. M10.0 added these; see its implementation record;
  - preview mode with mock data exists (`preview.html`, `src/preview/*`).
- Answers render as plain text. Citation markers (`[S1]`) are not interactive. Sources are listed
  as file name plus page only. Reopened conversations show no sources.
- There is no theme switch (themes follow the OS through `tokens.css`), little responsive layout
  (four 720 px media queries), and no reduced-motion support.
- Citation checking (`app/rag/citations.py`) only confirms that a cited id was retrieved; invalid
  ids are removed. It does **not** check that a passage supports a claim (ADR 017, D-5).
- Source fields:
  - `RAGSourceResponse` sends `source_id`, `document_id`, `filename`, `chunk_index`, `page`,
    `similarity`, `cited`;
  - it sends no passage text and no `chunk_id`;
  - the streamed final chunk has no `invalid_citations`.
  - (Superseded 2026-11-03 by M10.4 T2, locally: `chunk_id` and `passage_truncated` are now sent,
    and the final stream chunk carries `invalid_citations`. Still no passage text. See the T2
    record.)
- Saved messages (`Message` model) store no sources.
- Chunk metadata records `page_number` only for multi-page PDFs. There is no section or heading
  and no character offsets, and the stored chunk text is normalized.
- The context assembler can truncate the first source when it alone exceeds the budget; the only
  record of that is one context-wide flag.
- There is no route to view or download an original document file.

### Approved decisions (APPROVED; implementation status reconciled 2026-11-04)

Implementation status of each decision (local, uncommitted unless noted):
- **Implemented:** 2 (citation API and persistence, M10.4; migration `0009` written, not applied);
  4 (themes and motion preferences, M10.1); 5 (testing approach, M10.0, merged); 6 (evidence
  wording; "Supported" is never shown); 8 (the palette is in `tokens.css`; its contrast is checked by
  the token test and by axe in Chromium); 11 (`/overview`, M10.2/M2); 12 (document permissions kept;
  403 handled).
- **Partly implemented:** 1 (ongoing); 7 (dark-first tokens and primitives; no human visual review
  yet); 13 (XSS-safe rendering, CSP tests, authentication and authorization boundaries; CodeQL,
  secret scanning and push protection still UNKNOWN).
- **Deviated, owner acceptance pending:** 9. A dependency-free safe renderer (`MessageText`)
  replaces `react-markdown` + `remark-gfm`, whose installation was never authorized.
- **Not done:** 3 (the Apple Design Skill is not installed); 10 (the Inter font is not installed).

Decisions as approved:

1. **Parallel delivery.** M10 may proceed alongside M9. Keep their milestones, branches,
   acceptance criteria and status tracking separate. Do not mark M9 complete or imply production
   readiness.
2. **Citation API and database design:**
   - Return the exact passage supplied to the model, its chunk id and a truncation indicator.
   - Persist citation references with assistant messages, so citations survive reopening a
     conversation.
   - Store references and ids, not copied document text.
   - Add an API endpoint that returns a cited passage and its neighbouring chunks.
   - Recheck current document access on every citation read.
   - Unavailable or revoked sources must not expose their contents or leak cross-tenant
     information.
   - Changes are additive (existing clients keep working), with database migration `0009`.
3. **Apple Design Skill** (`github.com/dickwu/apple-design-skill`):
   - Approved for local, project-level installation only, at `.claude/skills/apple-design`,
     pinned to reviewed commit `ff4ebdd`.
   - Keep it outside Git: never commit or redistribute its files. Add `.claude/skills/` to
     `.gitignore` when installation is separately authorized.
   - Do not use `npx skills add`.
   - Do not copy Apple's reproduced guideline text into the repository or ship it with AegisAI.
   - Use it only as an optional review guide for design principles, foundations, interaction,
     writing and generative-AI UX. WCAG 2.2 AA and the project's tests remain binding.
   - The skill does not validate citations or evidence.
   - **Installation is approved in principle but has NOT occurred.**
4. **Theme behaviour:** default to the operating-system theme; offer optional System / Light /
   Dark settings; persist the user's override across sessions; respect reduced-motion and
   reduced-transparency preferences.
5. **M10 testing approach** (**implemented in M10.0, 2026-11-02, locally;** see the M10.0
   implementation record):
   - axe-core accessibility tests integrated with Vitest and Testing Library;
   - Playwright browser, keyboard and interaction tests;
   - automated contrast checks for both themes against WCAG 2.2 AA;
   - visual reviews at viewport widths 375 px, 768 px and 1280 px. Automated layout checks run at
     these widths; screenshot or visual-regression baselines are **not** implemented.
6. **Citation evidence wording:**
   - Initially display "Retrieved source — support not verified."
   - Retrieval alone must never be described as proof that a source supports a claim.
   - Claim-level evidence checking belongs in M10.7. Introduce a "Supported" label only after an
     evaluation set demonstrates sufficient reliability.
   - A design review passing is never evidence that a citation is correct.
7. **Visual direction:** an Apple + Linear hybrid, **dark-first** design: a calm, precise,
   content-focused enterprise interface. No Apple assets (SF Pro, SF Symbols, Apple artwork) and
   no native Apple platform conventions (see decision 3 and the risks below).
8. **Starting palette: charcoal and indigo, subject to accessibility testing.** These values come
   from the M10 design specification (2026-11-02). Their contrast was **calculated** (45 text and
   control pairs, all at or above WCAG 2.2 AA thresholds in both themes), but **not tested in a
   browser**. They are a starting point for M10.1 and may change after real testing.

   | Role | Dark | Light |
   |---|---|---|
   | App background | `#0e0f12` | `#f6f6f7` |
   | Sidebar | `#121317` | `#f0f0f2` |
   | Surface | `#16181c` | `#ffffff` |
   | Raised (panels, menus) | `#1c1e23` | `#ffffff` |
   | Hover | `#23252b` | `#ececef` |
   | Selected | `#2a2d34` | `#e4e5ea` |
   | Text: primary | `#ececef` | `#121316` |
   | Text: secondary | `#b0b3ba` | `#464a53` |
   | Text: tertiary | `#979ba3` | `#5d616a` |
   | Control border | `#6e737d` | `#80858e` |
   | Accent text (links, active) | `#a3adff` | `#3f49c4` |
   | Accent solid (primary button) | `#5b63d6` | `#4a55d4` |
   | Focus ring | `#8f9cff` | `#4a55d4` |
   | Success text / background | `#5fd39a` / `#11261c` | `#106b41` / `#e3f4ea` |
   | Warning text / background | `#f0c062` / `#2a2111` | `#7a4f00` / `#fbf0d9` |
   | Danger text / background | `#ff8f8a` / `#2d1517` | `#b4262a` / `#fbe7e7` |
   | Info text / background | `#7cc0ff` / `#0f2235` | `#165fb8` / `#e3eefb` |
   | Citation text / background | `#c3c9ff` / `#22264a` | `#323a9e` / `#e6e8fb` |
9. **Markdown rendering:** `react-markdown` with `remark-gfm`.
   - **Never `rehype-raw`;** raw HTML is never rendered.
   - Links are restricted to `http` and `https`.
   - No executable code rendering.
   - **Installation is NOT yet authorized.**
10. **Typography:** self-hosted **Inter Variable** (WOFF2), shipped with its **SIL Open Font
    License** text.
    - No external font CDN (the frontend's security policy allows fonts from its own origin only).
    - Verify the original font source, licence and redistribution conditions before
      implementation. Read-only check on 2026-11-02: `rsms/inter` reports OFL-1.1, latest release
      v4.1.
    - Not downloaded or installed.
11. **Overview:** a dedicated **`/overview`** route; **`/` stays the Copilot** (existing
    `/?conversation=` links keep working).
    - Genuine backend data only; no fabricated usage, cost, quality or operational metrics.
    - Unavailable data is shown distinctly from a zero value.
12. **Document permissions:**
    - Preserve the existing authorization and permission rules.
    - Do **not** introduce document sharing or expand ownership APIs in this redesign.
    - Handle HTTP 403 responses gracefully.
    - Never expose documents or citations the signed-in user is not authorized to access.
13. **Frontend security verification is part of M10.** Reuse the existing GitHub security
    infrastructure where practical and avoid duplicate workflows. Scope:
    - code scanning (CodeQL), Dependabot and npm audit;
    - secret scanning and push protection;
    - XSS and safe Markdown rendering;
    - authentication and authorization boundaries;
    - Content-Security-Policy compatibility;
    - dependency and supply-chain risk;
    - security-sensitive API interactions.

### M10 unresolved items (open; owner decision or verification needed)

- **Markdown dependency versus the bundle budget.**
  - Measured baseline (2026-11-02): main JavaScript 114.28 kB compressed.
  - Third-party estimates (bundlephobia, not measured in this project): `react-markdown` 10.1.0
    about 34.1 kB and `remark-gfm` 4.0.1 about 9.8 kB compressed, for roughly 158 kB in total.
  - That is above the **143 kB** compressed budget.
  - Decision needed: measure after installation, lazy-load the renderer with the Copilot view, or
    revise the budget.
- **CodeQL.** There is no CodeQL workflow in the repository (verified). Whether GitHub's CodeQL
  "default setup" is enabled is **UNKNOWN**: the API answered 401 without an admin sign-in.
- **Secret scanning and push protection:** status **UNKNOWN** (needs admin access). gitleaks
  already scans the full Git history and blocks merges (verified). Built images are not scanned
  for secrets (Trivy runs with `scanners: vuln`).
- **Ruleset bypass actors:** **UNKNOWN** (not visible without admin access). The ruleset itself is
  active (verified).
- **Production CSP testing approach: partly resolved in M10.0.**
  - Implemented: `e2e/production-csp.spec.ts` serves the production build (`vite preview`) with the
    policy built from `docker-entrypoint.sh`'s own `CSP="…"` template.
  - Not yet covered: nginx itself (its headers, caching and `/api/` proxy) and running the container
    image. Follow-up: a CI step that runs the built frontend image and checks its headers, needing
    owner approval.

### M10 status table

| Phase | Status | Notes |
|---|---|---|
| M10.0 Baseline and test foundations | In Progress | Passing locally (2026-11-02); merged in PR #36 (`bad9fec`); the PR's CI result has not been recorded here (UNKNOWN) |
| M10.1 Design tokens and themes | In Progress | Implemented locally 2026-11-03 (tokens, themes, primitives; 0 axe contrast violations); human visual review and Inter font pending |
| M10.2 Application shell and navigation | In Progress | Implemented locally 2026-11-04 (skip link, drawer below 768 px, `/overview` on real data); human visual review pending |
| M10.3 Conversation experience | In Progress | Implemented locally 2026-11-03 (safe renderer, citations, announcements); not run against the live backend |
| M10.4 Citation API and persistence | In Progress | T1 (passage metadata) implemented locally and owner-approved, 2026-11-03 (uncommitted); T2 (additive response fields) implemented locally and formally accepted, 2026-11-03 (uncommitted); T3 (model + migration `0009`, offline only) implemented locally 2026-11-03; T4–T8 (saving, reopened citations, passage endpoint, isolation tests, ADR 018) implemented locally 2026-11-03 under the full-M10 mission; `aegis_test` migrated to `0009` and the integration suite passed (123 passed, 25 skipped, incl. `test_citation_isolation.py`), 2026-11-04; migration round trip pending in CI; T9 excluded |
| M10.5 Citation source panel | In Progress | Implemented locally 2026-11-03; browser-tested in preview mode only |
| M10.6 Original document viewer | In Progress | Implemented locally 2026-11-04 (scoped download route, `/documents/:id` text viewer, cited passage); `test_document_file_isolation.py` passed against `aegis_test` at `0009` (2026-11-04); no PDF rendering; L4/L5 deferred to the owner |
| M10.7 Claim-level evidence verification | In Progress | Offline evaluation harness, 42-claim synthetic set and lexical baseline implemented 2026-11-04 (gate FAILS; ADR 019 Proposed); no support label shipped; D-5 and the gate criteria await the owner |
| M10.8 Remaining frontend pages | In Progress | Implemented locally 2026-11-04 (0 axe violations on all pages; no `<main>` overflow at 375/768/1280; lint ratchet 11 → 1); human visual review pending |
| M10.9 Document section metadata | In Progress | Implemented locally 2026-11-04 for Markdown and DOCX in chunk metadata (no schema change, no migration, no backfill); owner design review of the result pending |

### M10 phases

**M10.0 – Baseline and test foundations.** Status: **In Progress** (everything below except the
open items passes locally; see the implementation record).
- [x] Review every existing frontend screen using preview mode and mock data: automated axe,
  layout, keyboard and motion checks of all six screens in a real browser. A human visual review
  of rendered screens has **not** been done.
- [x] Record a baseline design review: the M10.0 assessment (code-based), plus the browser findings
  recorded as known issues.
- [x] Establish axe-core, Playwright and contrast testing, and responsive checks at three widths.
- [ ] Screenshot or visual-regression baselines (not implemented).
- [x] Review current behaviour at 375 px, 768 px and 1280 px (automated).
- [x] Record actual test results (local).
- [ ] Verify the extended `frontend-react-test` CI job on GitHub (needs a push or pull request
  by the owner).

**M10.1 – Design tokens and themes.** Status: **In Progress** (implemented locally 2026-11-03).
- [x] Refine role-based colour tokens, spacing and motion. Typography uses a system font stack;
  Inter (decision 10) is not installed.
- [x] Implement System / Light / Dark theme behaviour and persistence.
- [x] Respect reduced-motion and reduced-transparency settings.
- [x] Meet WCAG 2.2 AA contrast requirements in both themes, as far as automated checks go: all 36
  token pairs pass, and axe finds 0 contrast violations in Chromium. Not verified by a human review.
- [ ] Outstanding for acceptance: the Inter font, or a recorded waiver; a human visual review of
  both themes; a CI run.

**M10.2 – Application shell and navigation.** Status: **In Progress** (implemented locally
2026-11-04; drawer focus and Overview data states corrected 2026-11-04 after the review, M2/M3/L8).
- [x] Improve responsive navigation and sidebar behaviour (a drawer below 768 px).
- [x] Support keyboard navigation, visible focus and a skip link. The open drawer keeps focus;
  focus goes to the content after navigating; Escape, the backdrop and the Close button return it
  to the Menu button.
- [x] Review the Overview scope; existing backend data only. Failed, malformed and empty answers
  are shown distinctly; missing data is never shown as zero.
- [x] Validate responsive behaviour at the three approved widths (automated, Chromium).
- [ ] Outstanding for acceptance: a human visual review; a screen-reader pass; a CI run.

**M10.3 – Conversation experience.** Status: **In Progress** (implemented locally 2026-11-03).
- [x] Add safe rich-text rendering; untrusted raw HTML is never rendered. A dependency-free
  renderer replaces decision 9's library; the owner has not yet accepted that deviation.
- [x] Make citation markers interactive. They are openable only after the stream ends with
  `[DONE]`, which since M1 (2026-11-04) is sent only after the reply is committed.
- [x] Screen-reader announcements for streaming. Stop/retry and tool progress were kept.
- [x] Preserve existing chat behaviour and tests.
- [ ] Outstanding for acceptance: streaming against the real backend (approved model calls);
  acceptance of the decision 9 deviation.

**M10.4 – Citation API and persistence.** Status: **In Progress** (T1–T8 implemented locally;
migration `0009` and the integration suite NOT RUN; see the T1, T2, T3 and T4–T8 records and the
2026-11-04 remediation record).
- Task plan, from the 2026-11-02 read-only assessment. Each task needs the owner's separate
  authorization:
  - [x] T1: per-source passage metadata in the context assembler (owner-approved 2026-11-03; local,
    uncommitted);
  - [x] T2: additive response fields (`chunk_id`, per-source truncation, `invalid_citations` on the
    final stream event) (implemented locally 2026-11-03, uncommitted; formally accepted by the
    owner 2026-11-03 after review);
  - [x] T3: citation model, migration `0009`, migration tests (implemented locally 2026-11-03,
    uncommitted, offline only, **awaiting owner review**; see the T3 record);
  - [x] T4: citation repository and saving in `RAGService`, plus `message_id`, with the similarity
    rule (implemented 2026-11-03; see the M10.4 T4–T8 record);
  - [x] T5: citations on reopened conversations (implemented 2026-11-03);
  - [x] T6: passage endpoint with neighbouring chunks (implemented 2026-11-03);
  - [x] T7: isolation and security tests: unit tests run and passing; the integration suite
    (`test_citation_isolation.py`, 13 cases) **passed** against `aegis_test` at `0009`
    (2026-11-04);
  - [x] T8: ADR 018 and `data-flow.md` (implemented 2026-11-03);
  - [ ] T9 (optional): saving agent sources.
- The assessment's open owner decisions were **decided on 2026-11-03**; see "M10.4 approved
  decisions" below. (Earlier record: not yet decided.)
- **Authorization status (2026-11-03):**
  - T1 is implemented and was formally approved by the owner on 2026-11-03 (uncommitted).
  - T2 was authorized by the owner on 2026-11-03 and was formally accepted after review (uncommitted).
  - T2 was formally accepted by the owner on 2026-11-03 after a read-only review (uncommitted).
  - (Superseded by the updates below.) T3–T8 were at first not authorized; each needed the
    owner's explicit start instruction. T9 (agent citations) still needs separate authorization.
  - (Earlier record, 2026-11-03: "T2–T8 are not yet authorized".)
  - **Update 2026-11-03:** T3 was authorized by the owner and is implemented locally, awaiting
    review. T4–T8 remain **not authorized**.
  - **Update 2026-11-03 (full M10 mission):** the owner authorized implementing the whole M10
    roadmap (M10.0–M10.9) continuously, under unchanged Git, database, secret and protected-file
    restrictions. T4–T8 were implemented under that authorization.
  - Agent and multi-agent citations are excluded from M10.4.
- [x] Implement the approved additive API and database design (decision 2).
- [x] Add migration `0009` (written and checked offline only; **not applied** to any database).
- [x] Persist citation ids and references with assistant messages. Since M1 (2026-11-04), the reply
  and its citations are committed before the client learns the message id.
- [x] Return the exact passage shown to the model, its chunk id and its truncation status.
- [x] Add scoped passage retrieval and neighbouring-chunk access.
- [x] Recheck permissions on every read. Since L1 (2026-11-04), the resolved chunk must also belong
  to the citation's recorded document.
- [x] Add contract, persistence and tenant-isolation tests (unit tests run and passing).
- [x] `aegis_test` migrated to `0009` (owner-authorized, 2026-11-04); integration suite **123
  passed, 25 skipped**, including `test_citation_isolation.py`.
- [ ] Outstanding for acceptance: the migration round trip (pending in CI on the PR); a CI run;
  rollback after a real database commit failure (not yet verified; see the known-risks
  register).

**M10.4 approved decisions (owner, 2026-11-03; implemented locally in T1–T8, 2026-11-03):**
1. **Storage:** a separate `message_citations` table (not a JSONB column on `messages`).
2. **Foreign keys:** `message_id` → `messages.id` `ON DELETE CASCADE`. `document_id` and
   `chunk_id` are plain UUID columns **without** foreign keys, so a reference survives document
   deletion and reads as unavailable.
3. **Unavailable source:** HTTP 200 with `status: "unavailable"`. Deleted, made private, other
   tenant and passage mismatch all give an identical response, with **no** passage text, file name
   or page.
4. **Passage integrity:** store a rendering version and a SHA-256 of the exact passage given to
   the model. On read, verify both; if either does not match, the source is unavailable. The hash
   is never returned by the API.
5. **URL:** nested under conversations:
   `GET /api/v1/conversations/{conversation_id}/messages/{message_id}/citations/{source_id}`.
6. **Neighbouring chunks:** optional, at most 2 per side, off by default; same document only, under
   the current read filter.
7. **Old messages** (saved before M10.4): `citations: []`, with no backfill.
8. **Audit:** no audit event per citation read. Content-free operational logging of unavailable
   results is acceptable.
9. **Rate limiting:** no new rate limit in M10.4. Reassess only if measurements or a security
   review justify it.
10. **Retention:** keep citation reference metadata after document deletion, subject to the M9.5
    retention policy.
11. **Evidence status:** always `not_verified` (decision 6 of M10; ADR 017 D-5).
12. **Engineering controls:**
    - never trust client-supplied document or chunk ids;
    - recheck current document permissions on every citation read;
    - reuse the existing `AccessScope` and repository conventions;
    - keep the API additive;
    - add regression tests for every affected existing feature.

**M10.4 database restrictions (owner, 2026-11-03):**
- Migration `0009` may be written and validated **offline** only.
- **No migration may be applied to any database** (local, test, staging or production) without
  separate explicit owner approval.
- Integration tests that need the test database at the new head are recorded as **NOT RUN —
  approval pending** until then.

**M10.4 T3 decisions (owner, 2026-11-03):**
1. **Similarity: Option A.**
   - The table has `CHECK (similarity BETWEEN -1.0 AND 1.0)`, inclusive.
   - Why: T3's read-only review found the range depends on pgvector's server-side
     `cosine_distance`. Whether it clamps floating-point rounding can't be verified from this
     repository, and the `pgvector/pgvector:pg16` image is unpinned. So the application, not the
     database, must guarantee the range.
2. **T4 requirements for `similarity`** (binding on the T4 writer):
   - **reject** non-finite values (NaN, +infinity, −infinity), and never silently convert them
     into valid scores;
   - **clamp** finite values into [−1.0, 1.0] before saving.
3. **Uniqueness:** only `UNIQUE (message_id, source_id)`; no `(message_id, position)` constraint.
   - It would be redundant: `source_id = 'S' || position` with `position > 0` maps each position
     to exactly one id and back (a positive integer's text has no sign or leading zero), so the
     first constraint already makes `(message_id, position)` unique.
4. **`source_id` and `position`:** enforce `source_id = 'S' || position::text` and a positive
   `position`; `source_id` is `S1` to `S999`.

**M10.5 – Citation source panel.** Status: **In Progress** (implemented locally 2026-11-03).
- [x] Open source details from citation markers.
- [x] Support keyboard focus, accessible close behaviour and focus return.
- [x] Display the exact retrieved passage and source metadata.
- [x] Support unavailable, revoked, truncated and unverified states.
- [x] Support citations in reopened conversations.
- [ ] Citations in agent and multi-agent answers: excluded from M10.4 (T9). Needs separate
  authorization, or the owner descoping this criterion.
- [x] Do not display "Supported" without a successful evidence check (never displayed).
- [ ] Outstanding for acceptance: verification against the real backend; a CI run.

**M10.6 – Original document viewer.** Status: **In Progress** (implemented locally 2026-11-04).
- [x] Provide secure, access-scoped document viewing: a text viewer of the extracted passages, and
  an attachment-only download of the original.
- [ ] PDF page navigation and highlighting in the original layout. Not done: passages are only
  grouped by page. Needs `pdfjs-dist` (not authorized) or the owner descoping this criterion.
- [ ] Keep PDF viewer code out of the initial bundle (not applicable until a PDF viewer exists).
- [x] Test authorization, content type, caching and file-serving security: unit tests, and the
  integration test `test_document_file_isolation.py` (4) **passed** against `aegis_test` at
  `0009` (2026-11-04).
- [ ] Outstanding for acceptance: decisions on download rate limiting and streaming (L4) and on
  downloads of failed or processing documents (L5), both deferred to the owner; a CI run.

**M10.7 – Claim-level evidence verification.** Status: **In Progress** (offline evaluation only,
2026-11-04; ADR 019 **Proposed**).
- [x] Define an evaluation set: 42 SYNTHETIC claims written by the coding assistant. It is not
  representative, and far below the proposed gate.
- [x] Evaluate before enabling support labels: the lexical baseline fails the gate on every
  criterion.
- [x] Document the method, limitations, cost and failure modes (ADR 019).
- [x] Keep "Retrieved source — support not verified." (unchanged; enforced by a unit test).
- [ ] Outstanding for acceptance: the owner's D-5 decision and gate criteria. Only then a real
  evaluation set and a checker.

**M10.8 – Remaining frontend pages.** Status: **In Progress** (implemented locally 2026-11-04).
- [x] Apply the design system to the remaining pages: tokens and the recorded accessibility and
  layout fixes. There was no per-page redesign.
- [x] Keep existing functionality and authorization behaviour.
- [x] Responsive, keyboard and accessibility consistency (automated): 0 axe violations on every
  page in both themes; no overflow inside `<main>` at 375, 768 or 1280 px.
- [ ] Outstanding for acceptance: a human visual review; a screen-reader pass; the Uploader
  structure (the last lint warning); a CI run.

**M10.9 – Document section metadata.** Status: **In Progress** (implemented locally 2026-11-04;
DOCX matching corrected 2026-11-04, L7).
- [x] Section metadata for Markdown and DOCX. PDF gets none (no dependable headings).
- [x] Reprocessing behaviour: none. Earlier documents keep chunks without a section; there is no
  backfill.
- [x] Data model and migration implications reviewed: no schema change, so no migration. The
  section goes in the existing chunk `metadata`.
- [ ] Outstanding for acceptance: the owner's review of the design and the result.

### M10.0 implementation record (2026-11-02, local; not committed, CI not yet run)

All changes are under `frontend/web/` plus one CI job. **No application source changed:**
`frontend/web/src` gained only test files. No design tokens, components, routes or APIs changed.

**Dev dependencies installed** (exact versions from `package-lock.json`; `npm install --save-dev`):

| Package | Version | Purpose |
|---|---|---|
| `axe-core` | 4.14.0 | Accessibility engine |
| `jest-axe` | 11.0.0 | axe-core in Vitest (bundles its own `axe-core` 4.12.1) |
| `@playwright/test` | 1.64.1 | Browser tests (pulls `playwright` and `playwright-core` 1.64.1) |
| `@axe-core/playwright` | 4.14.0 | axe-core in Playwright |

- The install added 24 packages, all development-only; no existing package version changed. `npm
  audit`: 0 vulnerabilities (all dependencies, and runtime only).
- `vitest-axe` was not used: its last release was 2022-10-21 with a single maintainer.
- `jest-axe` has no type declarations, so `src/test/jest-axe.d.ts` declares the one function used.
  `@types/jest-axe` was avoided because it pulls in Jest globals that clash with Vitest.
- The Playwright Chromium browser (build 1248) is installed in the user cache, outside the repo.
- Not installed (out of scope): `react-markdown`, `remark-gfm`, the Inter font, `pdfjs-dist`, the
  Apple Design Skill.

**Files added:**

| File | What it does |
|---|---|
| `src/test/axe.ts` | `expectAxe` helper: WCAG 2.0–2.2 A/AA plus best-practice rules. Compares the violations against an explicit known-issues list, so new issues fail and fixed ones must be removed. `color-contrast` is off in jsdom only (no layout or canvas there). |
| `src/test/jest-axe.d.ts` | Type declaration for the `jest-axe` function used |
| `src/test/a11y.pages.test.tsx` | 20 tests. All six routes in the real shell with the preview's mock API: axe; one `h1`; `main` and `navigation` landmarks; `aria-current` on the active link; accessible names on every button and link. Also: System Status listed for administrators only, and link names kept when the sidebar is collapsed. |
| `src/test/a11y.components.test.tsx` | 10 tests: Composer, MessageBubble (waiting, error with retry, sources and tools), Uploader keyboard, EmptyState, StatusBadge text labels; each with axe |
| `src/styles/tokens.contrast.test.ts` | 46 tests. Parses `tokens.css`, checks the OS-preference and `data-theme` dark blocks match, and computes WCAG ratios for 22 colour pairs the CSS modules use, in both themes. Records today's pass or fail per pair (known failures are fixed in M10.1); any change fails. |
| `playwright.config.ts` | Two projects. `preview` runs on the Vite dev server against `preview.html` (mock data, no network). `production-csp` runs on `vite preview` against `dist/`. Chromium only; retries 0, so flakiness stays visible. |
| `e2e/preview.a11y.spec.ts` | 12 tests: axe in Chromium on all six pages, in light and dark, at 1280 px. The violated rules and element counts must exactly match `e2e/support/known-issues.ts`. |
| `e2e/preview.layout.spec.ts` | 34 tests, both themes. **As corrected 2026-11-02:** at 375/768/1280, reflow (no horizontal overflow of the document, and overflow inside `<main>` only on the recorded pages); key content visible; every page reachable from the navigation; main-area width. Then keyboard Tab and Enter navigation; a focus indicator on every tab stop **of the Copilot page** (up to 25; checks that one exists, not its contrast); first tab stop (no skip link yet); reduced motion (sidebar transition, streaming cursor). Known gaps are asserted at their current measured values, with the fixing milestone named. |
| `e2e/production-csp.spec.ts` | 4 tests on the production build under the production policy (template read from `docker-entrypoint.sh`): the template stays strict; the document carries the policy and an injected inline script is refused (control); the signed-out screen; all six signed-in pages, each with **0 policy violations** |
| `e2e/support/{policy,preview,backend,known-issues}.ts` | Shared helpers. `backend.ts` mocks the API and identity provider inside the browser; it uses a placeholder session token and makes no real network or model calls. |
| `tsconfig.e2e.json` | Type-checks the Playwright files (Node plus DOM types for `page.evaluate` callbacks); referenced from `tsconfig.json`, so `tsc -b` and `npm run build` check them |

**Files modified:**
- `.oxlintrc.json`: enabled the built-in `jsx-a11y` plugin (no new dependency) with all 36 of its
  rules. 35 are errors; `prefer-tag-over-role` is a warning, because its suggestion (replace
  `role="status"` with `<output>`, or the Uploader's `role="button"` with `<button>`) changes
  behaviour and is not a safe M10.0 fix.
- `vite.config.ts`: Vitest excludes `e2e/**`.
- `package.json`: the four dev dependencies and a `test:e2e` script.
- `package-lock.json`: the 24 added packages.
- `tsconfig.json`: references `tsconfig.e2e.json`.
- `.gitignore`: ignores `test-results/`, `playwright-report/`, `blob-report/`.

**CI change** (`.github/workflows/ci.yml`, job `frontend-react-test`; name unchanged, so it remains a
required check; no new workflow or job; permissions unchanged):
- added `timeout-minutes: 20`;
- after `npm run test`: `npx playwright install --with-deps chromium`, then `npm run test:e2e`
  (uses the `dist/` from the existing `npm run build` step);
- on failure, uploads the Playwright report and traces (`actions/upload-artifact`, the same pinned
  commit as `security.yml`, kept 7 days).
- Node stays 22 in CI (Playwright 1.64 needs Node 20 or newer).
- The 147 backend unit tests that check the workflows and frontend config pass, including the
  pinned-action and read-only-token rules.
- **The job has not run on GitHub yet.**

**Results (local, Windows, Node 24.14.0, 2026-11-02):**

| Check | Baseline (before M10.0) | After M10.0 |
|---|---|---|
| `npm run lint` | 0 errors, 3 warnings | 0 errors, **11 warnings**: the same 3, plus 8 `jsx-a11y(prefer-tag-over-role)` |
| `npx tsc -b` | pass | pass (now also checks `playwright.config.ts` and `e2e/`) |
| `npm run test` (Vitest) | 18 files, 144 tests | **21 files, 220 tests**, all passed, 0 skipped |
| `npm run test:e2e` (Playwright) | — | **50 passed**: `preview` 46 (at first including 8 expected-failure markers, replaced in the corrective pass); `production-csp` 4. 0 flaky, 0 skipped. |
| `npm run build` | JS 378.99 kB / **114.28 kB** compressed; CSS 23.45 kB / 4.69 kB | **identical** (same file hashes): dev dependencies do not reach the bundle; budget 143 kB unchanged |
| `npm audit` | 0 vulnerabilities | 0 vulnerabilities |
| Backend workflow and config tests | — | 147 passed |

**Accessibility findings now enforced by tests** (M10.0 baseline; none fixed in M10.0):
- **Colour contrast (serious)** on every page in both themes. Elements affected, light / dark:
  Copilot 2/2, Conversations 3/2, Documents 8/6, Memory 4/2, Operations 3/2, System Status 5/5.
  The token test lists the failing pairs (dark-theme accent and danger colours, status badges,
  warning text, muted text in light, field borders). Fix: M10.1.
- **`empty-table-header` (minor):** the Documents actions column header has no text. Fix: M10.8.
- **Composer:** no visible focus indicator. Fix: M10.1/M10.3.
- **No skip link.** Fix: M10.2.
- **At 375 px:**
  - the main area is exactly 135 px wide (375 − 240 px sidebar; 320 px is the minimum); fix:
    M10.2;
  - **new finding:** Conversations titles and Memory notes are squeezed to 0 px wide and cannot
    be read; fix: M10.2 and M10.8.
- **Reflow (WCAG 1.4.10), corrected 2026-11-02.** The document as a whole never scrolls
  horizontally at 375, 768 or 1280 px. But `<main>` scrolls on its own, and content overflows
  inside it on these pages (measured in Chromium on Windows, content / visible width in CSS px):
  - **375 px:** Copilot 422/135, Documents 149/135, Memory 206/135, Operations 205/135, System
    Status 216/135;
  - **768 px:** Documents 605/528;
  - **1280 px:** none.

  Fix: M10.2 and M10.8. The earlier statement "no horizontal page scrolling at any of the three
  widths" was true only of the document and missed these overflows.
- **Reduced motion is not honoured:** the sidebar transition and the streaming cursor blink. Fix:
  M10.1/M10.3.

**Limitations and unfinished items:**
- The CI run is unverified.
- No screenshot or visual-regression baselines.
- No manual screen-reader testing (NVDA, VoiceOver).
- Preview mode is not the real backend.
- The CSP tests do not exercise nginx or the container image.
- Chromium only (no Firefox or WebKit).
- Axe checks run at 1280 px only; the narrower widths get the layout checks.
- **WCAG 2.2 AA compliance is NOT claimed.**

### M10.0 corrective pass (2026-11-02, after the independent review; local, not committed)

Seven owner-authorized corrections. No application code, design token, dependency, workflow,
`.gitignore`, security policy, API or schema changed.

1. **Reflow test detects overflow inside `<main>`.** `e2e/preview.layout.spec.ts` now measures
   `main.scrollWidth` against `main.clientWidth` as well as the document. It asserts that the
   document never overflows and that exactly the recorded pages overflow inside `<main>`.
   - It passes because its expected sets at 375 px and 768 px are not empty. A check that could
     not see overflow inside `<main>` would measure nothing and fail.
   - It checks the set of pages, not pixel values, because content widths depend on fonts.
2. **Measured overflow recorded** in `e2e/support/known-issues.ts` (`KNOWN_MAIN_OVERFLOW`; values
   above, owned by M10.2/M10.8). They were re-measured in this pass and match the review
   diagnostic exactly.
3. **`CLAUDE.md` corrected:**
   - the M10 heading, and the heading of the approved decisions;
   - the working-tree status;
   - the focus-indicator scope (Copilot page only);
   - the reflow statement, and the missing 768 px Documents finding.
4. **Expected-failure markers replaced** (5 `test.fail` call sites, 8 runs) with explicit
   assertions of the measured current values. Each names its fixing milestone and checks its own
   preconditions, so a timeout or a wrong selector now fails instead of passing as "known":

   | Check | Asserted value | Fixed in |
   |---|---|---|
   | `<main>` width at 375 px | 135 px (≥ 320 at the other widths) | M10.2 |
   | Skip link | no skip link exists, and the first Tab focuses the "Copilot" navigation link | M10.2 |
   | Sidebar transition under reduced motion | `0.15s` (reduced-motion emulation confirmed first) | M10.1 |
   | Streaming cursor under reduced motion | it must appear; its animation name matches `blink` | M10.1/M10.3 |

5. **Lint warning ratchet:** `npm run lint` is now `oxlint --max-warnings=11`, which is also what
   CI runs. Verified with oxlint 1.90.0: 11 warnings exits 0; `--max-warnings=10` exits 1. No rule
   is disabled or suppressed.
6. **`frontend/web/.dockerignore`** also excludes `test-results/` and `playwright-report/` (local
   test output only; nothing a build or test needs).
7. **`src/test/axe.ts`:** the local helper `describe` was renamed `formatViolations`.

**Files changed in this pass** (all in `frontend/web/` except `CLAUDE.md`): `e2e/preview.layout.spec.ts`,
`e2e/support/known-issues.ts`, `src/test/axe.ts`, `package.json` (lint script only),
`.dockerignore`, and the root `CLAUDE.md`.

**Results** (local, Windows, Node 24.14.0, 2026-11-02, after the pass):

| Check | Result |
|---|---|
| `npm run lint` | exit 0: 11 warnings (same as before the pass), 0 errors; ratchet active |
| `npx tsc -b` | exit 0 |
| `npm run test` (Vitest) | 21 files, 220 tests passed, 0 skipped |
| `npm run test:e2e` (Playwright) | **50 passed**: `preview` 46 (8 tests at each of 375, 768 and 1280 px; the rest at 1280 px); `production-csp` 4. 0 expected-failure markers, 0 skipped, 0 flaky. |
| `npm run build` | JS 378.99 kB / 114.28 kB compressed; CSS 23.45 kB / 4.69 kB; **byte-identical** to before (same SHA-256) |
| `npm audit` | 0 vulnerabilities |

**Local Windows caveat (observed 2026-11-02):**
- After `npm run test:e2e`, the Vite dev server that Playwright's `webServer` started
  (`cmd /c vite --port 5173`) can survive as an orphaned `node` process: Playwright stops the
  `cmd` wrapper but not its child.
- This happened twice and was stopped by hand each time. It blocks port 5173 for the next run.
- Not observed in CI (Linux).
- Possible follow-up, needing approval: start the dev server with `node` directly in
  `playwright.config.ts`, or document a clean-up step.

### M10.4 T1 implementation record (2026-11-03, local; branch `feature/m10-citation-passage-metadata`, not committed)

Owner-authorized scope: T1 only. Starting point: `main` at `bad9fec`, equal to `origin/main`.
**Status: formally approved by the owner (2026-11-03).** Still uncommitted; the owner handles Git.

**Files changed (2):**
- `backend/app/rag/context/assembler.py`;
- `backend/tests/unit/rag/test_context_assembler.py`.

**What changed:**
- `AssembledSource` has two new **required** fields:
  - `passage_chars`: how many characters of the chunk's marker-neutralized content the model
    received, after the source header;
  - `passage_truncated`: whether the context budget cut that passage short.
- New function `model_visible_passage(chunk_content, passage_chars)`: returns
  `neutralize_markers(chunk_content)[:passage_chars]`, and rejects a negative length.
- **Unchanged:** the context text, source order, the budget rule, the context-wide `truncated`
  flag, marker neutralization, citation validation, the prompt and the model call.
  - Only source 1 can be cut. When the cut falls inside its header, it is still listed with
    `passage_chars = 0` (the existing behaviour).
  - Later sources that do not fit are dropped and never listed.
  - An empty passage is never reported as truncated.
- **`RAGSource` (`app/rag/schemas.py`) was deliberately NOT changed.** It is built in
  `app/rag/service.py` and feeds only the API response. Giving it the new fields would need
  changes to `service.py` and the API contract, which belong to T2.

**How reconstruction works:**
- Chunks are never edited after ingestion: nothing in `app/` updates them, and they are deleted
  only through the document cascade.
- So the stored chunk content plus the recorded `passage_chars` rebuild exactly the text the model
  received for that source, without storing any text.
- This holds only while `neutralize_markers` stays unchanged. A rendering-version marker (or a hash)
  is left to the persistence design in T3.

**Tests:**
- `test_context_assembler.py` went from 28 to 60 test cases. Existing test bodies are unchanged,
  except that the two header-cut tests now also call the rebuild helper.
- Cases covered:
  - an untruncated source;
  - neutralization changing the passage length;
  - source 1 cut by the budget;
  - a cut through neutralized text;
  - later sources dropped and not reported;
  - several sources, all whole;
  - exactly at the budget, and one character over;
  - a cut inside or at the header (budget 1, header length − 1, header length);
  - an empty passage, and an empty passage cut inside its header;
  - a negative length rejected;
  - document content that imitates the context's own structure (added after review; see below).
- **Exact reconstruction** is checked in every case by `_assert_rebuilds_the_context`.

**Adversarial reconstruction test improvement (2026-11-03, owner-requested after review):**
- **Before:** the rebuild helper parsed passages out of the context by splitting on the block
  separator `\n\n---\n\n` and the blank line after each header. Document text containing those
  sequences would have been attributed to the wrong source.
- **Now:** nothing is parsed out of the context text. The helper:
  - writes each header from the documented prompt format;
  - appends `model_visible_passage(content, passage_chars)`;
  - joins the blocks and compares the result with the real context as **one exact string**.

  It also checks that each source is the matching retrieval result, in order, with ids `S1`, `S2`,
  …; that `passage_chars` is within the rewritten passage's length; and that `passage_truncated`
  agrees with it. A budget ending inside source 1's header must give an exact prefix.
- **New tests (+9):**
  - `test_content_imitating_the_context_structure_is_still_rebuilt_exactly`, at 8 budgets from 60
    to 10,000. Its documents contain the block separator, runs of blank lines, a forged
    `[SOURCE 2]` header, and `[S2]`, `[ SOURCE 1 ]`, `【S3】` and `[/SOURCE 2]`. It asserts an
    exact rebuild, that the separator occurs inside passages at every budget, and that every
    marker look-alike is still neutralized;
  - `test_a_separator_inside_a_passage_does_not_create_an_extra_source`.
- **Checked by a scratchpad script** (outside the repository, not part of the suite):
  - the helper detects a `passage_chars` that is one too small, a flipped `passage_truncated` and a
    swapped source order;
  - on the regression data, the old split-based parse found 2–5 "blocks" where there were only 1–2
    sources.
- **Context output equivalence** (scratchpad script, not part of the suite): the `HEAD` and the
  new assembler gave identical context text, context-wide flag and existing source fields on
  20,000 random inputs. That covered 1,627 cases with source 1 cut and 5,626 with dropped sources.
- Production assembler code did not change in this improvement; only the test file did.

**Final results** (local, Windows, Python 3.12, 2026-11-03, after the last edit):

| Command | Result |
|---|---|
| `uv run pytest backend/tests/unit/rag/test_context_assembler.py -q -rs -p no:cacheprovider` | **60 passed** |
| `uv run pytest backend/tests/unit/rag -q -rs -p no:cacheprovider` | **161 passed** |
| `uv run pytest backend/tests/unit -q -rs -p no:cacheprovider` | **2,260 passed, 1 skipped** (`test_docs_gating_and_request_id.py:55`, by design), 0 failed; exit 0 (204 s) |
| `uv run ruff check .` | pass: "All checks passed!" |
| `uv run ruff format --check .` | pass: "514 files already formatted" |
| `uv run pyright` (both T1 files) | 0 errors, 0 warnings, 0 informations |

- These results supersede the interim T1 figures recorded earlier on 2026-11-03: 51 assembler
  tests, 152 RAG unit tests, and 2,251 passed / 1 skipped for the full unit suite.
  - The interim full-suite run (2,251 passed) came before a formatting-only fix to `assembler.py`.
    The run after that fix also gave 2,251 passed, 1 skipped.
  - The final run above includes the 9 new tests.
- The integration suite was **not** run: T1 forbids database connections, and the unit suite
  blocks PostgreSQL connections by design.

**Limitations:**
- Not yet used outside the assembler: nothing is persisted or returned to clients (T2–T4).
- Whether the stored chunk text matches the original document is out of scope: chunks are
  normalized text (see M10.9).
- Citation support is still **not verified** (ADR 017 D-5).

### M10.4 T2 implementation record (2026-11-03, local; same branch, not committed; awaiting owner review)

Owner-authorized scope: T2 only, with `message_id` explicitly **deferred to T4**.

**`message_id` timing (read-only assessment, 2026-11-03, before T2):**
- **Non-streaming:** `RAGService.answer` already has the id: `MessageRepository.add` flushes and
  returns the `Message`, but the service discards it.
- **Streaming:** `answer_stream` yields the final event **before** saving the assistant message
  (after the loop, before `[DONE]`).
- A UUID could be generated up front without changing transactions, but it needs an `id`
  parameter on `MessageRepository.add` and a change to `FakeMessageRepository`, which builds
  `Message(id=uuid4(), **kwargs)` and would fail with a duplicate `id`.
- **Owner decision:** keep T2 to response fields; add `message_id` in T4 together with citation
  saving.

**Files changed (8):**
- Application: `backend/app/rag/schemas.py`, `backend/app/rag/service.py`,
  `backend/app/api/schemas/rag.py`, `backend/app/api/v1/rag.py`.
- Tests: `backend/tests/unit/api/test_rag_endpoint.py`, `backend/tests/unit/rag/test_rag_service.py`,
  `backend/tests/unit/rag/test_rag_filters_and_citations.py`,
  `backend/tests/unit/safety/test_output_paths.py`.

**What changed:**
- **`RAGSource`** (internal): new required field `passage_truncated`. `_to_rag_source` maps it from
  T1's `AssembledSource.passage_truncated`. `passage_chars` stays internal (it is for T4).
- **`RAGSourceResponse`** (non-streaming `sources` and the final stream event's `sources`): new
  `chunk_id` (UUID) and `passage_truncated` (bool, default `false`). All earlier fields unchanged.
  No passage text is returned.
- **`RAGChatStreamChunk`:** new `invalid_citations`, a list on the final chunk (empty when nothing
  was removed) and `null` on every other chunk, like `sources`. The non-streaming response already
  had `invalid_citations`; it is unchanged.
- **`RAGService.answer_stream`** now yields `(conversation_id, chunk, sources, invalid_citations)`
  instead of a 3-tuple.
  - `invalid_citations` is `citations.report.removed` on the final chunk, `()` on the no-context
    final chunk, and `None` otherwise.
  - The final chunk is built after `citations.finish()` has run, so the list is complete.
  - The route maps it into the event. This internal iterator has no other application consumer
    (checked by search); tests that unpacked 3-tuples were updated.
- **Unchanged (verified):**
  - **saving and transactions:** the diff of `service.py` touches no `messages.add`, `touch`,
    `rollback`, session or flush line;
  - `MessageRepository` and `FakeMessageRepository`;
  - the database models, migrations and repositories;
  - the frontend, dependencies, the prompt, citation validation and the context text.
- **Not done (out of scope):** `message_id` (T4); frontend types (`StreamSource` in
  `frontend/web/src/api/stream.ts` copies known fields only, so the new fields are ignored);
  saving citations (T3/T4).

**Tests (+10 new, plus updates):**
- `test_rag_endpoint.py` (+5):
  - non-streaming sources carry `chunk_id` and `passage_truncated`, with the field set exactly the
    earlier fields plus the 2 new ones, and no passage text;
  - non-streaming `invalid_citations` is still reported;
  - the final stream event carries `invalid_citations` and the new source fields, and earlier
    events carry `null`;
  - an empty `invalid_citations` list when nothing was removed;
  - the error event is unchanged.

  The fake service now yields 4-tuples and can script final sources and invalid citations; a
  `make_source` helper was added.
- `test_rag_service.py` (+5):
  - `chunk_id` mapped from retrieval;
  - source 1 marked truncated by a small budget, with the dropped source not listed and the
    context-wide flag unchanged;
  - stream final sources carry `chunk_id` and truncation;
  - a removed `[S9]` is reported on the final chunk only;
  - the reply is **still saved only after the final chunk** (only the user's message exists while
    chunks are yielded).
- **Existing tests updated:**
  - 3-tuple unpacks changed to 4-tuples: 4 in `test_rag_filters_and_citations.py`, 3 in
    `test_rag_service.py`, 1 in `test_output_paths.py`;
  - the three streamed-citation tests now also assert that the removed `S8` reaches the final
    chunk only;
  - two existing stream tests assert `()` and `None` for the new element.
- One formatting fix: `ruff format` normalized line endings in `test_rag_service.py`. A diff
  ignoring carriage returns showed no content change.

**Results** (local, Windows, Python 3.12, 2026-11-03, after the last code edit):

| Command | Result |
|---|---|
| `uv run pytest backend/tests/unit/api/test_rag_endpoint.py -q -p no:cacheprovider` | 16 passed |
| `uv run pytest backend/tests/unit/rag/test_rag_service.py -q -p no:cacheprovider` | 19 passed |
| `uv run pytest backend/tests/unit/rag/test_rag_filters_and_citations.py -q -p no:cacheprovider` | 27 passed |
| `uv run pytest backend/tests/unit/safety/test_output_paths.py -q -p no:cacheprovider` | 8 passed |
| `uv run pytest backend/tests/unit/rag/test_context_assembler.py -q -p no:cacheprovider` | 60 passed (T1, unchanged) |
| `uv run pytest backend/tests/unit/rag -q -rs -p no:cacheprovider` | 166 passed |
| `uv run pytest backend/tests/unit/api -q -rs -p no:cacheprovider` | 155 passed |
| `uv run pytest backend/tests/unit/safety -q -rs -p no:cacheprovider` | 64 passed |
| `uv run pytest backend/tests/unit -q -rs -p no:cacheprovider` | **2,270 passed, 1 skipped** (`test_docs_gating_and_request_id.py:55`, by design), 0 failed; exit 0 (124 s) |
| `uv run ruff check .` | pass: "All checks passed!" |
| `uv run ruff format --check .` | pass: "514 files already formatted" (after the formatting fix above) |
| `uv run pyright` | 0 errors, 0 warnings, 0 informations |

- The 2,270 are the T1 baseline of 2,260 plus the 10 new tests.
- The api, rag and safety group runs came before the formatting fix; the full unit run, the
  per-file runs, ruff, the format check and pyright came after it.
- **Not run:**
  - the integration suite (no database access in T2; the unit suite blocks PostgreSQL by design);
  - the frontend tests (no frontend change);
  - live model calls.

**Compatibility and security notes:**
- **All changes are additive JSON fields.** The React client copies known fields only and ignores
  new ones; no exact-match assertion on a whole source object existed in the backend tests (checked
  by search).
- **`chunk_id` is now visible to clients.** Chunk ids are deterministic (UUID5 of the document id
  and chunking settings), so they were never secret. Every read of chunk content is scoped by the
  caller's current `AccessScope` (`document_read_filter`), never by knowledge of an id.
- **`invalid_citations` contains only source ids** such as `S9`, never document content.
- **Limitation (inherited):** a provider stream that ends without a final chunk sends no final
  event. Neither `sources` nor `invalid_citations` reaches the client then; the saved text is still
  correct.

**Post-review notes (2026-11-03; T2 formally accepted by the owner after a read-only review):**
- **One more `answer_stream` consumer, inspected and unaffected:**
  `backend/tests/unit/api/test_stream_setup_errors.py` has a test double,
  `_Missing.answer_stream`. It raises `NotFoundError` before yielding anything, so the tuple shape
  never applies to it. It was not mentioned in the record above; it needed no change and passes in
  the full unit run.
- **Known documentation issue, deferred to T8:** `docs/architecture/data-flow.md` (around line 413)
  still shows the old three-element `answer_stream` example,
  `yield (conversation_id, chunk, sources if chunk.is_final else None)`. That document was not
  edited; updating it belongs to T8.
- **Unapproved network access during the review demo (disclosed):**
  - The read-only review ran a scratchpad demo (outside the repository) of the real route with
    scripted test doubles. Using `TestClient(app)` ran the application's startup routine, which
    warmed up the local embedding model. That contacted the **Hugging Face Hub** anonymously to
    check the model cache.
  - This network access was **not approved**.
  - **No language-model call** was made, and nothing was written to the repository (the file
    checksums matched before and after).
  - **Rule for future demos:** avoid application startup paths that trigger network access (for
    example the app lifespan, or `TestClient(app)` used as a context manager) unless explicitly
    approved. Prefer the unit-test fixtures, which avoid it. See also Working rules.

### M10.4 T3 implementation record (2026-11-03, local; same branch, not committed; awaiting owner review)

Owner-authorized scope: T3 only:
- the model;
- migration `0009`;
- offline tests;
- the necessary head updates;
- the Kubernetes smoke workflow's expected head;
- this record.

No repository, service, API, frontend or message-saving change. **No database was connected to,
and no migration was applied anywhere.**

**Read-only review and stop (before implementation):**
- The T3 review proposed the schema. When implementation was authorized, the similarity range
  could not be established: pgvector's clamping can't be verified from the repository, and the
  image is unpinned.
- Work stopped before any edit, and the owner chose Option A (see "M10.4 T3 decisions").

**Files created (3, untracked):**
- `backend/app/domain/models/message_citation.py`: the `MessageCitation` model.
- `backend/alembic/versions/0009_add_message_citations.py`: the migration.
- `backend/tests/unit/test_message_citations_migration_offline.py`: 66 offline tests.

**Files modified (5):**
- `backend/app/domain/models/__init__.py`: exports `MessageCitation`.
- `backend/alembic/env.py`: adds `MessageCitation` to its explicit model import list.
- `backend/tests/unit/test_ownership_migrations_offline.py`: the head test is now
  `test_there_is_a_single_head_and_it_is_0009`, asserting `["0009"]`.
- `backend/tests/integration/test_ownership_migration.py`: the opt-in round trip's head assertion
  is now `"0009"`, with its comment updated. NOT RUN.
- `.github/workflows/k8s-smoke.yml`: `EXPECTED_ALEMBIC_HEAD: "0009"` (owner-authorized; a unit
  test keeps it equal to the newest migration).

**Historical `0008` references kept unchanged:**
- the 0008-specific tests (`tests/unit/memory/test_memory_structure.py`);
- literal or fake heads in `test_isolation_guard.py` and `test_isolation_entry_points.py`;
- the documentation.

**Table `message_citations`** (exactly as rendered offline; every column NOT NULL):
- **Columns:** `id` UUID (primary key `pk_message_citations`, set in Python), `message_id` UUID,
  `source_id` VARCHAR(16), `position` SMALLINT, `document_id` UUID, `chunk_id` UUID, `similarity`
  DOUBLE PRECISION, `cited` BOOLEAN, `passage_chars` INTEGER, `passage_truncated` BOOLEAN,
  `rendering_version` VARCHAR(32), `passage_sha256` CHAR(64), and `created_at` TIMESTAMPTZ
  (`DEFAULT now()`, plus a Python default as on the other models).
- **Foreign key:** only `fk_message_citations_message_id`, `message_id` → `messages (id)`
  `ON DELETE CASCADE`. **None** on `document_id` or `chunk_id`.
- **Unique:** only `uq_message_citations_message_source (message_id, source_id)`.
- **Checks:**
  - `ck_message_citations_source_id_format`: `source_id ~ '^S[1-9][0-9]{0,2}$'`;
  - `ck_message_citations_source_id_position`: `source_id = 'S' || "position"::text`;
  - `ck_message_citations_position_positive`: `"position" > 0`;
  - `ck_message_citations_passage_chars`: `passage_chars >= 0`;
  - `ck_message_citations_passage_sha256`: `passage_sha256 ~ '^[0-9a-f]{64}$'`;
  - `ck_message_citations_rendering_version`: `char_length(rendering_version) > 0`;
  - `ck_message_citations_similarity`: `similarity BETWEEN -1.0 AND 1.0`.
- **`position` is quoted inside the check expressions** (`"position"`). `POSITION` is a SQL
  keyword; quoting the identifier is always valid in PostgreSQL and means exactly
  `'S' || position::text`. The column definition itself renders unquoted, as SQLAlchemy chooses.
- **No extra index:** the unique constraint already indexes `(message_id, source_id)`.
- **No ORM relationship** on either side (no async lazy loading, no ORM-side cascades).
- **Upgrade:** one `CREATE TABLE` plus the version update, with no `ALTER`, `DROP`, `INSERT`,
  `DELETE`, `TRUNCATE` or backfill.
- **Downgrade:** `DROP TABLE message_citations` only. It deletes every saved citation reference;
  conversations, messages and documents are untouched.

**Tests (66 new, all offline; Alembic `sql=True` never connects):**
- chain: single head `0009`, parent `0008`;
- the upgrade creates only the table and changes nothing else;
- each column's type and NOT NULL, and the exact column list;
- exactly one foreign key, to `messages`, with cascade, and none to documents, chunks or
  embeddings;
- exactly one unique constraint, and no `(message_id, position)` one;
- the primary key; each of the 7 checks, and no others;
- the downgrade drops only the table;
- model and migration agree on constraint names, check expressions, columns, nullability and
  primary key;
- the model's only foreign key is `message_id`; no ORM relationships; registered in the metadata,
  the package and `env.py`;
- the check patterns evaluated in Python:
  - source ids `S1`–`S999` accepted; `S0`, `S01`, `S1000`, lowercase, padded and fullwidth
    variants rejected;
  - positions 1–999 map one-to-one to ids;
  - the hash pattern accepts 64 lowercase hex characters and rejects uppercase, wrong lengths and
    non-hex;
- the similarity bounds are exactly the approved inclusive range.

**Results** (local, Windows, Python 3.12, 2026-11-03, after the last code edit):

| Command | Result |
|---|---|
| `uv run pytest backend/tests/unit/test_message_citations_migration_offline.py -q -p no:cacheprovider` | **66 passed** |
| `uv run pytest` on the new file plus `test_ownership_migrations_offline.py`, `test_k8s_smoke_workflow.py`, `memory/test_memory_structure.py` and `test_isolation_guard.py` | 254 passed (run before a formatting-only fix) |
| `uv run pytest backend/tests/unit -q -rs -p no:cacheprovider` | **2,336 passed, 1 skipped** (`test_docs_gating_and_request_id.py:55`, by design), 0 failed; exit 0 (137 s) |
| `uv run ruff check .` | pass: "All checks passed!" (the first run found 2 over-long lines in the new test file; fixed) |
| `uv run ruff format --check .` | pass: "517 files already formatted" (the first run asked to re-wrap 2 new files; `ruff format` applied, line wrapping only) |
| `uv run pyright` | 0 errors, 0 warnings, 0 informations |

- 2,336 = the T2 total of 2,270 plus the 66 new tests (the renamed head test keeps the count).
- The full unit run, the new file's run, ruff, the format check and pyright came after the last
  edit.
- **Offline rendering:** a scratchpad script (outside the repository) rendered the
  `0008:0009` and `0009:0008` SQL in Alembic offline mode, with asyncpg's connect functions
  replaced by one that raises; no connection was attempted.

**Not run (NOT RUN — approval pending):**
- `alembic upgrade` or `downgrade` against any database;
- the opt-in migration round trip (`RUN_MIGRATION_ROUNDTRIP`, `test_ownership_migration.py`);
- the database-backed integration suite: the local `aegis_test` is still at `0008`, and
  `tests/live_database.py` refuses a database behind the code's head;
- live model calls; Docker and Kubernetes (the smoke workflow was edited, not run).

**Stale documentation found (not edited; outside T3's file scope):**
- `infra/kubernetes/README.md:148` says the smoke check expects Alembic `0008`. **Correction
  (2026-11-03, T8):** that line records smoke run #2, which really did complete at `0008`; it is
  accurate history, not a stale head reference, so it was left unchanged.
- `README.md` mentions 0008 in its memory notes (historical, still accurate).
- The protected `docs/operations/production-readiness.md` and
  `docs/operations/backup-restore-and-rollback.md` describe `0008` as the current head. They need
  owner approval to change.
- For T8, together with the `data-flow.md` item.

### M10.4 T4–T8 implementation record (2026-11-03, local; same branch, not committed)

Authorized by the owner's full-M10 mission instruction (2026-11-03). T3's source and migration were
re-reviewed first (no findings) and T4 builds on them unchanged.

**What was built:**
- **Assembler (T1 file, additive):** `PASSAGE_RENDERING_VERSION = "neutralize-markers-v1"`,
  `passage_sha256()`, and a required `AssembledSource.passage_sha256` (SHA-256 of exactly the passage
  the model saw).
- **`app/rag/citation_records.py` (new):** `CitationRecord`, `build_citation_records()`,
  `persistable_similarity()`. Non-finite scores raise `CitationIntegrityError` (never converted);
  finite scores are clamped to [−1.0, 1.0] (the T3 decision). A malformed source id is rejected.
- **`app/db/repositories/citation_repository.py` (new, scoped):** `add_for_message` (only for an
  ASSISTANT message in a conversation the caller can see), `get`, `list_for_conversation`, all
  through `conversation_filter`. Added to the "must take a scope" structural test.
- **`DocumentChunkRepository` (2 new scoped reads):** `get_readable_with_documents` (chunk must
  still exist, still belong to the cited document, and pass the CURRENT read filter; one query) and
  `list_readable_range` (neighbours of the same document, same filter).
- **`MessageRepository.add`:** optional `id`. `FakeMessageRepository` honours it.
- **`RAGService`:**
  - records are built **before** the model is called, so a broken invariant spends no tokens and,
    on the stream, sends no event;
  - citations are saved in the same flush and transaction as the assistant reply (rollback-safe);
  - `answer` returns `message_id`;
  - `answer_stream` yields a `RAGStreamItem` named tuple
    `(conversation_id, chunk, sources, invalid_citations, message_id)`: the reply id is fixed up
    front and reported on the final item (and on the no-context item). (Correction 2026-11-04,
    review finding M1: the request session committed only after `[DONE]` had been sent, so "valid
    once the stream completes" did not hold. The service now commits before the stream ends; see
    the remediation record.)
- **HTTP:** `message_id` on `RAGChatResponse` and the final `RAGChatStreamChunk` (null before).
- **`app/services/citation_service.py` (new):** resolves citations against CURRENT access and
  verifies the rebuilt passage (rendering version + SHA-256). Anything else is unavailable, with
  the reason logged content-free (`source_not_readable`, `rendering_changed`, `passage_mismatch`).
- **`app/api/schemas/citations.py` (new):** `AvailableCitation` / `UnavailableCitation`
  (discriminated by `status`; the unavailable model has **no** source fields at all), and
  `MessageCitationSummary`. `support` is always `"not_verified"`.
- **Routes (`app/api/v1/conversations.py`):**
  - `GET /api/v1/conversations/{id}` messages now carry `citations` (empty for user messages,
    no-source answers and messages saved before M10.4);
  - new `GET /api/v1/conversations/{conversation_id}/messages/{message_id}/citations/{source_id}`
    with `neighbors` 0–2 (default 0). The source id must match `S1`–`S999` (422 otherwise); a
    foreign or unknown conversation, message or source id is 404; an unreadable source is 200
    `unavailable`.
- **Docs (T8):** new `docs/architecture/decisions/018-citation-persistence.md`;
  `docs/architecture/data-flow.md`'s stale `answer_stream` example replaced (closes the T2
  post-review item).

**Tests:**
- `tests/unit/rag/test_citation_persistence.py` (23, new): similarity rejection/clamping,
  record building, exact rebuild and hash, no text in records, saving on both paths, `message_id`,
  rollback leaves no citations, non-finite score rejected before the model and before any event,
  and NaN dropped by the retrieval threshold.
- `tests/unit/services/test_citation_service.py` (19, new): available passage; unavailable when
  revoked, deleted, re-assigned to another document, hash or rendering mismatch, or longer than
  the chunk, each with **no** source fields; not found for someone else's conversation or unknown
  ids; neighbours from the same document within the window, none by default, none for an
  unavailable source, edge of document, bounded window; reopened conversation resolution.
- `tests/unit/api/test_conversations_endpoint.py` (+16): citations on detail (legacy `[]`, the
  unavailable summary's exact field values), available and unavailable responses (the
  unavailable body has exactly 5 keys), neighbours, 404, 422 for 7 malformed source ids and 3 bad
  `neighbors` values, with no lookup made.
- `tests/unit/api/test_rag_endpoint.py` (+2): `message_id` on the response and the final event.
- `tests/unit/rag/test_context_assembler.py` (+3; the rebuild helper now also checks the hash).
- `tests/unit/auth/test_isolation_structure.py`: `CitationRepository` must take a scope; the
  scope-probe test covers the new route automatically (passed).
- **`tests/integration/test_citation_isolation.py` (10, new, NOT RUN):** owner reads the exact
  passage; alan, ada, bob and bea get 404; revocation by making the document private; deleted
  document (reference kept, no text); a manipulated reference to another tenant's chunk;
  tampered hash; neighbours limited to two and to the same document (`neighbors=3` is 422);
  reopened conversation; cascade on conversation delete; saving for someone else's message refused.

**Results** (local, Windows, 2026-11-03):

| Command | Result |
|---|---|
| `uv run pytest backend/tests/unit -q -rs -p no:cacheprovider` | **2,400 passed, 1 skipped** (the by-design skip), 0 failed; exit 0 |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 524 files already formatted |
| `uv run pyright` | 0 errors, 0 warnings, 0 informations |

- 2,400 = the T3 total of 2,336 + 64 new unit tests.
- `tests/integration/test_citation_isolation.py` has a file-level `# ruff: noqa: F811`: it re-uses
  `test_data_isolation.py`'s `world` and `client` fixtures by name.

**Not run (approval pending):** migration `0009` on any database; the integration suite (the
local `aegis_test` is at `0008`); live model calls.

**Known limitations:** a revoked user still sees their old answer text (which may quote the
source); changing `neutralize_markers` needs a new rendering version; agent and multi-agent
sources are not saved (T9).

### M10.1, M10.3 and M10.5 implementation record (2026-11-03, local; same branch, not committed)

Under the full-M10 mission. No dependency was added (`package.json` and the lock file unchanged).

**M10.1 — design tokens, themes and primitives:**
- `src/styles/tokens.css` rewritten on the approved charcoal-and-indigo palette (decision 8),
  dark-first, with the old role names kept so every CSS module still works.
  - New role tokens: surface raised, hover, selected, sidebar and overlay; `--accent-solid` and
    `--accent-solid-hover` for filled buttons, separate from the accent-text colour (which is
    light in dark mode); `--focus-ring`; info and citation colours; radius, elevation, motion,
    weight and layout tokens.
  - Typography: a system font stack. **Inter was not downloaded** (decision 10 still needs the
    font file and its licence checked; that is network access not approved in this session).
- Theme behaviour (decision 4): `src/theme/theme.ts` and `ThemeSwitch` (a native radio group in
  the top bar). System by default; Light or Dark saved in `localStorage` (`aegisai.theme`), every
  access guarded; applied before the first render (`main.tsx`).
- `src/index.css`: one focus ring for everything (`--focus-ring`); `prefers-reduced-motion`
  finishes every animation and transition immediately; `prefers-reduced-transparency` makes
  overlays opaque; a `.visually-hidden` utility.
- Fixed the recorded gaps: the Composer no longer removes its focus outline; the sign-in and send
  buttons moved off `--accent-600` onto the solid-accent tokens.
- Primitives in `src/components/ui/`: `Button` (4 variants, 2 sizes, `busy`, never submits by
  default), `Badge` (6 tones), `Spinner`, `LoadingState` (`<output>`), `ErrorState` (alert with
  retry) and `SidePanel`. The panel is a native `<dialog>` with `aria-modal`, a labelled title,
  focus moved in, Tab trapped, Escape or the backdrop to close, and focus returned to the opener;
  its header and footer are plain divs, because portalled `<header>`/`<footer>` became duplicate
  page landmarks (found by axe in the browser).

**M10.3 — conversation experience:**
- `MessageText`: a safe renderer for model output (paragraphs, line breaks, bulleted and numbered
  lists, `inline code`, **bold**). It is never parsed as HTML (no `dangerouslySetInnerHTML`, no
  links), so injected markup is shown as text. **Deviation from decision 9:** this replaces
  `react-markdown` + `remark-gfm`, whose installation was never authorized and which would exceed
  the 143 kB bundle budget; it covers the formatting answers actually use, with no dependency.
- Citation markers become buttons only for ids the backend returned for this answer, and only once
  the saved answer can be opened; any other marker (such as a removed `[S9]`) stays plain text.
- The streamed answer keeps `message_id`, the conversation id and `invalid_citations` from the
  final event. A stream that stops or breaks drops the `message_id` (that reply was rolled back).
  The source list adds "Retrieved sources — support not verified." and a "View" button per
  source; removed citation ids are explained under the answer.
- Reopened conversations map each message's saved `citations` to sources; an unavailable one shows
  "Source no longer available" with no file name or page.
- A polite live region announces "Writing the answer…", then complete, stopped or failed (the text
  is not announced token by token).

**M10.5 — citation source panel (`CitationPanel`):**
- Opens from a marker or a source's "View" button and reads the passage from
  `GET …/citations/{source_id}` (new `src/api/citations.ts`); nothing is shown from memory.
- Shows the document (a link to `/documents/{id}?chunk=n`, for M10.6), page, section and passage
  number, whether it was cited, and the exact passage given to the model, with a note when it was
  truncated.
- Always shows "Retrieved source — support not verified" and explains that retrieval alone does not
  show support (decision 6).
- "Show surrounding text" asks for `neighbors=2` (never more).
- Unavailable sources show only an explanation, with no details, link or surrounding-text control;
  404 or 403 say the source could not be found; other errors offer a working retry.
- The preview mock API answers the new endpoint and returns `message_id`, clearly mock data.

**Tests and results** (local, Windows, Node 24.14.0, 2026-11-03):

| Command | Result |
|---|---|
| `npx vitest run` | **25 files, 277 tests passed** (was 21 files, 220) |
| `npm run lint` | exit 0, **11 warnings**: the ratchet held (a `<output>` element and a native `<dialog>` were used instead of adding role warnings) |
| `npm run build` (`tsc -b` + Vite) | pass; JS 392.20 kB / **118.54 kB** gzip (was 114.28 kB; budget 143 kB); CSS 33.95 kB / 6.55 kB |
| `npx playwright test` | **52 passed** (50 earlier specs + 2 new citation specs) |

- New Vitest files: `tokens.contrast.test.ts` rewritten (36 pairs × 2 themes, all pass: 74 tests);
  `components/ui/ui.test.tsx` (12); `components/Chat/MessageText.test.tsx` (6);
  `components/Chat/CitationPanel.test.tsx` (7); `pages/CopilotCitations.test.tsx` (4).
- Browser baselines updated because the gaps are fixed:
  - **axe colour contrast: 0 violations on every page in both themes** (was 2–8 per page); only
    the Documents `empty-table-header` remains (M10.8);
  - every Copilot tab stop shows a focus indicator (the Composer gap is gone);
  - under reduced motion the sidebar transition and the streaming cursor finish immediately.
- New `e2e/preview.citations.spec.ts` (2): keyboard opening, axe with the panel open (0
  violations), surrounding text, Escape returning focus to the marker.
- No orphaned Vite process was left after the runs (checked).

**Not done or not verified:**
- A human visual review and manual screen-reader testing (NVDA, VoiceOver) were not done.
- The Inter font (decision 10) is not installed.
- Live streaming against the real backend was not run (no backend or model calls in this session).

### M10.2 implementation record (2026-11-04, local; same branch, not committed)

Under the full-M10 mission. No dependency added; no backend change.

**What was built:**
- **Skip link** (`AppShell.tsx`): "Skip to main content" is the first tab stop, visible only while
  focused, and targets `<main id="main-content" tabIndex={-1}>` (WCAG 2.4.1).
- **Navigation drawer below 768 px:**
  - the sidebar becomes an off-canvas drawer (`position: fixed`, `visibility: hidden` when closed,
    so it is out of view and out of the tab order);
  - a Menu button in the top bar (`aria-expanded`, `aria-controls="app-navigation"`, "Open/Close
    navigation") opens it;
  - opening moves focus to the first link; Escape closes it and returns focus to the Menu button;
    the backdrop or any link click closes it (including the link to the current page);
  - the collapse toggle is hidden in the drawer; from 768 px up the sidebar is unchanged.
- **Top bar:** below 768 px it may wrap onto a second row (no control hidden or overlapping; found
  in the browser: the theme switch covered the Menu button at 375 px); the e-mail is hidden there.
- **Copilot header** wraps (its controls row overflowed to 427 px at 375 px).
- **Overview (`/overview`, decision 11), `pages/OverviewPage.tsx`:**
  - real backend data only: the operations summary (document total and by status), the 5 most
    recent conversations (the list endpoint returns at most 50, so no total is claimed), the number
    of saved memory notes, backend reachability, and, for administrators only, the database and
    Redis checks from `/system/status`;
  - each card shows "Unavailable: the backend did not return this data." when its request fails,
    never a zero; a real zero from the backend is shown as zero (both tested);
  - states that no usage, cost or quality metrics are shown because none are recorded;
  - `/` stays the Copilot; an Overview link was added to the navigation (`aria-label="Main"`) and
    to the preview's route allow-list (`src/preview/guard.ts`).

**Tests and results** (local, Windows, Node 24.14.0, 2026-11-04):

| Command | Result |
|---|---|
| `npx vitest run --maxWorkers=2` | **26 files, 289 tests passed** (was 25 files, 277) |
| `npm run lint` | exit 0, 11 warnings (ratchet held) |
| `npx tsc -b` / `npm run build` | pass; JS 397.96 kB / **119.96 kB** gzip (budget 143 kB); CSS 36.98 kB / 7.12 kB |
| `npx playwright test` | **58 passed** (was 52) |

- New: `src/components/Shell/AppShell.test.tsx` (11: skip link, drawer, Overview unavailable vs
  zero, admin-only checks); Overview added to `a11y.pages.test.tsx` (+3) and `PREVIEW_PAGES`;
  `e2e/preview.shell.spec.ts` (4: drawer by keyboard at 375 px, axe with it open (0 violations),
  Escape focus return, backdrop).
- Ratchets updated from measurement (Chromium, both themes):
  - `<main>` is the full viewport width below 768 px (was 135 px at 375 px);
  - **overflow inside `<main>` at 375 px: none** (was Copilot, Documents, Memory, Operations,
    System Status); still open at 768 px: Documents (M10.8);
  - every page's content is visible at every width (Conversations titles and Memory notes were
    squeezed to 0 px at 375 px);
  - the skip-link test now asserts the skip link is first, visible on focus, and moves focus into
    `<main>`.
- **Test-run note:** one default-parallel Vitest run had 6–7 tests time out at 5 s, a different set
  each run, with CPU at 63% from other processes (no leftover Node process). Run alone, each page
  axe test takes under 1 s; with `--maxWorkers=2` the whole suite passed. Not a code failure, but
  the suite is sensitive to machine load.

**Not done:** a human visual review; a manual screen-reader pass. (Superseded 2026-11-04: focus
is now kept inside the open drawer, and the Overview's states were corrected; see the remediation
record, M2, M3 and L8.)

### M10.6 implementation record (2026-11-04, local; same branch, not committed)

Under the full-M10 mission. No dependency added; no migration.

**Backend:**
- `DocumentService.get_original_file(document_id)` (`app/services/document_service.py`): the same
  scoped read as `GET /documents/{id}` (the CURRENT read filter), then the stored bytes. `None` for
  "no such document", "not readable" and "file missing from storage" alike (the last is logged
  content-free as `document_original_file_unavailable`). Returns the uploaded name, never the
  storage key.
- `ORIGINAL_FILE_MEDIA_TYPES`: the media type comes from the validated document type (PDF, DOCX,
  `text/plain; charset=utf-8`, `text/markdown; charset=utf-8`), never from the client-declared
  `content_type`.
- **New route `GET /api/v1/documents/{document_id}/file`** (`app/api/v1/documents.py`):
  - 404 for anything the caller cannot read (same body as a guessed id);
  - always `Content-Disposition: attachment` with a sanitized ASCII `filename` and the exact
    UTF-8 `filename*` (RFC 6266/5987), so quotes, CR/LF or path separators in an uploaded name
    cannot break the header;
  - `X-Content-Type-Options: nosniff`, `Cache-Control: private, no-store`,
    `Content-Security-Policy: default-src 'none'; sandbox`,
    `Cross-Origin-Resource-Policy: same-origin`;
  - audit event `document.downloaded` (outcome `success` / `not_found`; no file name in it);
  - no new rate limit. (Correction 2026-11-04: M10.4 decision 9 covers citation reads only, so
    rate limiting and streaming of downloads still need an owner decision; review finding L4.)
- Test double: `FakeStorage.read` now raises `FileNotFoundError` for a missing key, like
  `LocalFileStorage` (it raised `KeyError`; nothing relied on that).

**Frontend:**
- `src/api/documents.ts`: `getDocument()`, `MAX_CHUNKS_PER_REQUEST = 200`, and
  `downloadDocumentFile()` (an authenticated `fetch`, then a blob download under the known file
  name; the file is never opened inside the app).
- **`/documents/:documentId` — `pages/DocumentViewerPage.tsx`:**
  - details (name, type, status, pages, size, number of passages) and "Download original";
  - the extracted text as stored for search, grouped by page when `metadata.page_number` is known,
    with a note that layout, images and formatting of the original are not shown;
  - `?chunk=<n>` (only a plain integer; anything else ignored) loads pages of 200 only as far as
    that passage, marks it ("Cited passage", `aria-current="location"`), scrolls to it and moves
    focus to it; a passage that no longer exists is said so;
  - 404 or 403 show "Document not available" with no detail; other errors offer a retry;
  - "Load more passages (n of total)".
- The citation panel's document link (M10.5) now lands here; the page title is "Document".
- Preview mock: `GET /documents/{id}` from mock data; `/file` answers 404 (the preview holds no
  files, so no content is invented).

**Not done:** rendering the original PDF or DOCX in the browser (no `pdfjs-dist`; installing it is
not authorized and would add to the bundle and the CSP); exact highlighting in the original layout.

**Tests and results** (local, Windows, 2026-11-04):

| Command | Result |
|---|---|
| `uv run pytest backend/tests/unit -q -rs -p no:cacheprovider` | **2,413 passed, 1 skipped** (the by-design skip), 0 failed (387 s) |
| `uv run ruff check .` / `ruff format --check .` / `pyright` | pass / 525 files formatted / 0 errors |
| `npx vitest run --maxWorkers=2` | **27 files, 299 tests passed** |
| `npm run lint` | exit 0, 11 warnings (ratchet held) |
| `npm run build` | pass; JS 404.22 kB / **121.61 kB** gzip (budget 143 kB); CSS 38.62 kB / 7.36 kB |
| `npx playwright test` | **60 passed** |

- New backend unit tests (+13): `test_documents_endpoint.py` (+9: attachment and exact bytes; the
  security headers; 5 hostile file names; 404 without a disposition; malformed id 422) and
  `test_document_service.py` (+4: uploaded name and bytes, media type from the validated type,
  unreadable, file missing). The scope-probe structural test covers the new route (passed).
- **`tests/integration/test_document_file_isolation.py` (4, NOT RUN):** owner gets the exact bytes
  as an attachment; a private original is 404 for all four others, identical to a guessed id;
  sharing opens it to the organization only and making it private closes it again; a deleted
  document has no original. Lint, format and pyright pass; collection only.
- New `src/pages/DocumentViewerPage.test.tsx` (10, including axe); `e2e/preview.citations.spec.ts`
  (+2: marker, panel link, viewer at the cited passage focused, axe 0 violations, preview download
  says "not available").

### M10.8 implementation record (2026-11-04, local; same branch, not committed)

Under the full-M10 mission. No dependency added; no backend change. The pages already use the
M10.1 tokens through the kept role names; this pass fixed the recorded accessibility and layout
gaps rather than redesigning each page.

**What changed:**
- **Documents** (`pages/DocumentsPage.tsx` + css):
  - the actions column header has visually hidden text "Actions" (fixes axe `empty-table-header`);
  - each file name links to its viewer (`/documents/{id}`, M10.6);
  - the table sits in a CSS container and stacks into labelled blocks (`data-label` on every value
    cell) when its own width is under 640 px, replacing the old 720 px viewport query. This fixes
    the 768 px overflow (605/528 px), where the sidebar left the table 528 px;
  - header text moved from `--text-muted` to `--text-secondary`.
- **Seven `role="status"` elements became `<output>`** (same implicit status role): the Conversations
  and Memory loading text, the Memory notice, the Copilot "Loading conversation…", the two sign-in
  screens, and "Thinking…". `index.css` makes `<output>` a block.
- **Lint warnings that M10.0 recorded and deferred are gone:**
  - `toneFromCheck` and `StatusTone` moved to `components/statusTone.ts`
    (`only-export-components`);
  - Documents and System Status load their first data in promise callbacks inside the effect, with
    no synchronous `setState` (`set-state-in-effect`). (Correction 2026-11-04: on Documents an
    earlier error clears only when a later load succeeds; on System Status the Refresh button
    clears it as the new request starts, `SystemStatusPage.refresh`.)
- **Lint ratchet lowered: `oxlint --max-warnings=1`** (was 11). The one remaining warning is the
  Uploader's `role="button"` drop zone: it contains the file input, and a `<button>` cannot validly
  contain an input, so changing it needs a different structure (and its keyboard tests).

**Results** (local, Windows, Node 24.14.0, 2026-11-04):

| Command | Result |
|---|---|
| `npx vitest run --maxWorkers=2` | **27 files, 301 tests passed** |
| `npm run lint` | exit 0, **1 warning** (ratchet now 1) |
| `npx tsc -b` / `npm run build` | pass; JS 404.73 kB / **121.73 kB** gzip; CSS 39.20 kB / 7.50 kB |
| `npx playwright test` | **60 passed** |

- Ratchets emptied from measurement: **axe finds 0 violations on every page in both themes**
  (`KNOWN_ISSUES` is now empty, and the Vitest page list has no known issues), and **no page
  overflows inside `<main>` at 375, 768 or 1280 px** (`KNOWN_MAIN_OVERFLOW` is empty at every
  width).
- New in `Pages.test.tsx` (+2): the file-name link and the cell labels; a failed first listing is
  shown as an alert.

**Not done:** a human visual review of each page; manual screen-reader testing; restyling the
pages beyond the tokens (Memory, Conversations, Operations and System Status keep their layouts);
the Uploader structure.

### M10.7 implementation record (2026-11-04, local; same branch, not committed)

Under the full-M10 mission, within decision 6: **no "Supported" label exists anywhere.** The
citation API still returns `support: "not_verified"` and the UI still says "Retrieved source —
support not verified". D-5 (ADR 017) and the gate's criteria are the owner's decision.

**What was built:**
- `backend/app/evaluation/evidence.py`: a labelled-claim loader (`supported` / `unsupported` /
  `conflicting`, with validation), `LexicalSupportChecker` (a deterministic baseline with no model
  call: one sentence must cover at least 75% of the claim's content words, contain all its numbers
  and agree on negation), metrics led by supported precision and the false "supported" rate per
  label (undefined is reported as undefined, never as 1.0), `split_claims`, and `SupportLabelGate`
  with PROPOSED criteria (300 cases, 100 per label, precision 0.95, false supported at most 0.02 on
  conflicting and 0.05 on unsupported) plus `owner_approved = False`, so it cannot pass.
- `backend/tests/evaluation/data/evidence_eval_dataset.json`: **42 synthetic claims** written by
  hand by the coding assistant over 6 invented passages (18 supported, 11 unsupported,
  13 conflicting), including cases built to defeat word overlap. Its description says it is
  synthetic and small.
- `scripts/evaluate_evidence.py`: prints the report. Offline: no model, network, secret or
  database.
- `docs/architecture/decisions/019-claim-evidence-evaluation.md` (**Proposed**): method, gate,
  measurement, options (lexical / local NLI / LLM judge) with cost and failure modes.

**Measured result** (lexical baseline, dataset v1, 2026-11-04, deterministic):

| Metric | Value |
|---|---|
| Accuracy | 0.833 (35 / 42) |
| Supported precision | 0.789 (15 / 19) |
| Supported recall | 0.833 (15 / 18) |
| False "supported" on unsupported | 0.091 (1 / 11) |
| False "supported" on conflicting | 0.231 (3 / 13) |
| Gate | **FAIL** on every criterion |

- Errors: d4, r4 (number words), e7 (working vs calendar days), d6 (week vs month) wrongly called
  supported; t3, r2, l3 (paraphrase or extra words) missed. The checker was not tuned to the set.

**Tests:** `backend/tests/unit/evaluation/test_evidence.py` (19): the set is labelled synthetic and
covers every label; the measured figures and error ids are pinned; the gate fails today and cannot
pass without owner approval even on a perfect report; undefined precision is not "perfect"; checker
cases (numbers, negation, contractions, one sentence only); `split_claims`; 4 invalid datasets
rejected; **no module under `app/` outside `app/evaluation/` imports it**; the citation schemas'
`support` is still only `"not_verified"`.

| Command | Result |
|---|---|
| `uv run pytest backend/tests/unit/evaluation -q -p no:cacheprovider` | 96 passed |
| `uv run python scripts/evaluate_evidence.py` | the figures above |
| `uv run ruff check .` / `ruff format --check .` / `pyright` | pass / 529 files formatted / 0 errors |

**Not done:** a larger or real dataset; a second labeller; an NLI or LLM checker (a new model or
billed calls, not authorized); any user-facing support label.

### M10.9 implementation record (2026-11-04, local; same branch, not committed)

Under the full-M10 mission. The phase rule was "not before the data model and migration
implications are reviewed". That review found **no schema change is needed**: the section goes in
the existing chunk `metadata` JSONB as `metadata["section"]`, which the citation service already
read (M10.4) and the API already returns. Recorded here for the owner's review of the result.

**What was built:**
- `backend/app/documents/sections.py`:
  - `markdown_headings`: ATX (`#`…`######`, closing `#`s allowed) and setext (`===` / `---`
    under a plain line), ignoring fenced code (```` ``` ```` / `~~~`), lists, quotes and `#tag`;
  - `listed_headings`: whole-line matches of known heading texts in document order (DOCX).
    (Superseded 2026-11-04, review finding L7: replaced by `positioned_headings`, which matches by
    position; see the remediation record.)
  - `assign_sections`: each chunk gets the heading in effect where its **own** text begins (after
    the overlap it repeats from the previous chunk, and whitespace), via a binary search; a chunk
    it cannot locate gets none (never a guess); headings are capped at 200 characters.
- `ExtractionResult.headings` (new, default empty): DOCX paragraphs styled "Title" or
  "Heading N" (at most 2,000, 500 characters each). Kept OUT of `metadata`, which is copied into the
  document's metadata that the API returns.
- `DocumentService._with_sections`: Markdown and DOCX only (single-page formats). PDF and TXT get
  no section (no dependable headings).
- **Unchanged:** chunk content, `chunk_index`, chunk ids (UUID5 of document id and chunk
  settings), the chunker, normalization, and therefore T1–T4 passage reconstruction and hashes.
- **Reprocessing:** none. Documents ingested before M10.9 keep their chunks with no section, and
  the UI shows none. A re-upload of the same bytes is a duplicate and is not reprocessed. A
  backfill would need an owner-approved, separately reviewed job.
- **Frontend:** the document viewer shows "Passage n · Section" when a string section exists (the
  citation panel already showed it).

**Tests:** `backend/tests/unit/documents/test_sections.py` (13): heading detection (ATX, setext,
fenced code, look-alikes, the length bound, offsets); assignment (own-text rule, metadata kept,
unlocatable chunk, repeated text located in order); DOCX heading styles reported outside the
metadata; end to end through `DocumentService` (Markdown chunks identical to the chunker's output
apart from the section; DOCX sections from styles; TXT gets none). `DocumentViewerPage.test.tsx`
(+1: shown when a string, ignored otherwise).
- **Bug found and fixed by these tests:** the first version searched from the previous chunk's
  start, so a repeated passage matched its first occurrence again. It now searches from one
  character later.

### M10 full-mission final verification (2026-11-04, local, after the last code edit unless noted)

| Command | Result |
|---|---|
| `uv run pytest backend/tests/unit -q -rs -p no:cacheprovider` | **2,445 passed, 1 skipped** (the by-design skip), 0 failed (208 s). Run before two cosmetic fixes (a docstring line wrap in `sections.py` and `b"..."` for `"...".encode()` in its test); `backend/tests/unit/documents` re-run afterwards: 110 passed |
| `uv run ruff check .` / `ruff format --check .` / `pyright` | All checks passed / 532 files formatted / 0 errors, 0 warnings |
| `npm run lint` | exit 0, 1 warning (`--max-warnings=1`) |
| `npm run build` | pass; JS 404.92 kB / **121.77 kB** gzip (budget 143 kB); CSS 39.25 kB / 7.51 kB |
| `npx vitest run --maxWorkers=2` | **27 files, 302 tests passed** |
| `npx playwright test` | **60 passed** (preview + production-csp); no leftover Node process |
| `npm audit` / `npm audit --omit=dev` | 0 vulnerabilities / 0 vulnerabilities |

- **Disclosure: unapproved network access.** `npm audit` (run once each way at the end) contacts
  the public npm registry and sends the dependency tree (package names and versions; no secrets,
  no source). Network access was not approved for this mission. Nothing else contacted the network
  as far as observed: no model downloads, no model calls, no external APIs. The backend unit
  fixtures log `embedding_model_warmed_up` as before, using the test-suite stub.
- **Not run (owner approval needed):** migration `0009` on any database; the integration suite
  (`aegis_test` is at `0008`), including `test_citation_isolation.py` (10) and
  `test_document_file_isolation.py` (4); the migration round trip; live model calls; Docker,
  Kubernetes; GitHub CI.
- **Git:** branch `feature/m10-citation-passage-metadata` at `bad9fec`; 71 modified and 40
  untracked paths (including `CLAUDE.md` and `docs/technical-handover/`); **nothing staged,
  committed or pushed**. Protected docs: no diff; the backup runbook's SHA-256 still
  `f17913bf…6dfad`; the 18 handover files untouched.

### M10 acceptance-review remediation record (2026-11-04, local; same branch, not committed)

Owner-authorized scope: review findings M1, M2, M3, L1, L7, L8 and L10 only. This is defect
remediation; **M10 is not complete**. No migration was applied, no database was contacted, no
model was called, no dependency was installed and no network was used.

**M1: the reply is committed before the client learns it exists.**
- **Cause:** `get_session` commits only after the response body has been sent, so `[DONE]` (and
  the JSON answer's `message_id`) could reach the client before the reply and its citations were
  committed.
- **Fix:** `RAGService._commit_reply()` commits right after the reply, its citations and the
  conversation touch are saved. This covers all four paths: the streamed answer, the streamed
  no-context answer (committed **before** its only item is yielded), the JSON answer and the JSON
  no-context answer.
- **Effect:** the route sends `[DONE]` only after the generator ends, so it now follows the
  commit. If the commit fails, the error ends the stream, no `[DONE]` is sent, and `get_session`
  rolls back. A model failure mid-stream still rolls back explicitly and never commits.
- The non-streaming answer is included because it relied on the same teardown timing (not verified
  for JSON responses in this FastAPI version).
- `FakeSession` (`tests/unit/services/doubles.py`) gained `commit()`, `commit_calls`, an
  `on_commit` hook and `commit_error`.
- The integration `db_session` fixture already cleans up committed rows by organization; those
  tests were not run.

**M2: the Overview distinguishes unavailable, malformed and empty data.**
- New `frontend/web/src/api/overview.ts`: strict loaders that accept only a well-formed body.
  - A 204, an empty 200 or a wrongly shaped body (such as `{}`, negative or text counts, a list of
    the wrong shape) throws `MalformedDataError`.
  - A failed request throws the usual `BackendError`.
- `OverviewPage` shows:
  - "Unavailable: the request to the backend failed." when the request failed;
  - "Unavailable: the backend answered without usable data." when it came back malformed;
  - a real zero or an empty list as such.
- The general wrappers (`getOperationsSummary` etc.) are unchanged, so other pages behave as
  before.

**M3 and L8: the mobile drawer's focus handling.**
- `AppShell.tsx`, while the drawer is open:
  - Tab and Shift+Tab cycle through the drawer's visible controls and the Menu/Close button only;
  - `<main>` is `inert`.
- On closing:
  - following a drawer link closes it and moves focus to `<main>`;
  - Escape, the backdrop and the Close button return focus to the Menu button.
- **L8:** a `(min-width: 768px)` media-query listener closes the drawer when the window widens.
  The key listener and the media-query listener are added only while the drawer is open and
  removed when it closes.
- Desktop sidebar clicks are unchanged; focus moves only after drawer navigation.

**L1: the resolved chunk must belong to the citation's recorded document.**
- `DocumentChunkRepository.get_readable_with_documents` matches exact `(chunk_id, document_id)`
  pairs, so duplicate chunk ids no longer collapse into one reference.
- `CitationService._resolve` also checks both the chunk's and the document's id against the
  citation. A mismatch is unavailable, with the new content-free log reason `document_mismatch`.

**L7: DOCX headings matched by position, not by text.**
- `ExtractionResult.headings` is now `(ordinal, prefix)` pairs: the heading's first line is the
  `ordinal`-th non-blank line of the extracted text.
- `sections.positioned_headings` finds that line in the normalized text. It accepts the heading
  only if the line starts with the normalized prefix; otherwise it skips it and never guesses.
- Results:
  - body text identical to a heading no longer takes its place;
  - headings longer than 500 characters are found, with the section still capped at 200;
  - a paragraph whose style lookup raises is treated as body text, and extraction continues;
  - paragraphs with line breaks are counted correctly.
- **Limitation:** a leading line holding only a BOM or non-ASCII whitespace shifts the ordinals.
  The prefix check then skips the headings rather than mislabelling them.

**L10:** this file's M10 heading, introduction, decision status, per-phase statuses and checklists
were reconciled, and the stale statements in earlier records are corrected in place, marked with
the date.

**Tests added:**
- `backend/tests/unit/rag/test_reply_commit_ordering.py` (8):
  - commit after the save and before the stream ends, with the reply and citation present at
    commit time;
  - the no-context stream commits before its item is yielded;
  - both JSON paths commit before returning;
  - a model failure rolls back and never commits;
  - a failed commit ends the stream with the error;
  - at the route, `[DONE]` is produced only after the commit, and no `[DONE]` follows a failed
    commit.
- `backend/tests/unit/services/test_citation_service.py` (+4): the wrong-document reference never
  borrows the right one's result (both orders); the service rejects a chunk of another document
  even from a careless repository; the repository's exact pair matching.
- `backend/tests/unit/documents/test_sections.py` (+6, −2 replaced): position matching and
  verification; heading positions outside the document metadata; duplicate body text; long
  headings; line breaks; a failing style lookup.
- `frontend/web/src/pages/OverviewPage.test.tsx` (11): an empty 200, a 204, `{}` and HTTP 500 on
  every card (never zero); 4 malformed summaries; wrongly shaped lists; real zeros and empty
  lists; valid data.
- `frontend/web/src/components/Shell/AppShell.test.tsx` (+5): the Tab trap and `inert`; focus to
  `<main>` after navigation; focus return after the backdrop and the Close button; L8 (close on
  widening, listeners removed, Escape inert afterwards).
- `frontend/web/e2e/preview.shell.spec.ts` (+3 per theme, 10 in all): the Tab/Shift+Tab trap at
  375 px; navigation moves focus to `<main>`; the backdrop returns focus; widening to 1280 px
  closes the drawer.

**Results** (local, Windows, 2026-11-04, after the last code edit):

| Command | Result |
|---|---|
| `uv run pytest backend/tests/unit/rag/test_reply_commit_ordering.py -q -p no:cacheprovider` | 8 passed |
| `uv run pytest tests/unit/rag tests/unit/api tests/unit/safety tests/unit/services tests/unit/agents tests/unit/memory -q -p no:cacheprovider` (from `backend/`; corrected 2026-11-04, the paths were misrecorded) | 752 passed (after M1, before L1 and L7) |
| `uv run pytest backend/tests/unit/services/test_citation_service.py -q -p no:cacheprovider` | 23 passed |
| `uv run pytest backend/tests/unit/documents -q -p no:cacheprovider` | 114 passed |
| `uv run pytest backend/tests/unit -q -rs -p no:cacheprovider` | **2,461 passed, 1 skipped** (the by-design skip), 0 failed (333 s) |
| `uv run ruff check .` / `ruff format --check .` / `pyright` | All checks passed / 533 files formatted / 0 errors, 0 warnings |
| `npm run lint` | exit 0, 1 warning (the Uploader; limit 1) |
| `npm run build` | pass; JS 406.83 kB / **122.32 kB** gzip (budget 143 kB); CSS 39.25 kB / 7.51 kB |
| `npx vitest run --maxWorkers=2` | **28 files, 318 tests passed** (was 27 files, 302) |
| `npx playwright test --project=preview e2e/preview.shell.spec.ts` | 10 passed |
| `npx playwright test` (full) | **65 passed, 1 failed**: `preview.layout.spec.ts:159`, light theme, "the streaming cursor does not blink under reduced motion" |
| the same test with `--repeat-each=3`, both themes | 3 passed, 3 failed (`NaN` duration, or `locator.evaluate` timed out) |

- 2,461 = 2,445 + 16 (M1 8, L1 4, L7 6 new minus 2 replaced).
- **The failing Playwright test is a race in the test itself.** It waits for the streaming cursor,
  then reads its computed style in a separate step. When the mock stream ends in between, the
  element is gone: an empty style gives `NaN`, or the read times out.
  - It passed in every earlier full run (2026-11-03 and 2026-11-04).
  - This remediation changed nothing it exercises: the Copilot page, `MessageBubble` and the
    preview stream are untouched, and the `AppShell` changes act only while the drawer is open
    (closed in this 1280 px test).
  - The machine was under load from other processes (40% CPU, including a VS Code update). That
    supports the race explanation but does not prove it.
  - **Fixed in the follow-up below (2026-11-04).** At the time it was not fixed, as it was outside
    that task's scope.
- **NOT RUN:** migration `0009`; the integration suite (`aegis_test` at `0008`), including
  `test_citation_isolation.py` and `test_document_file_isolation.py`; live model calls; `npm
  audit` (network); Docker; GitHub CI.

**Remaining risks:**
- Every new SQL path still runs only against fakes until the integration suite is run.
- The service now commits by itself. A future caller that wants to add more writes in the same
  transaction after `answer` or `answer_stream` would have to account for that.
- The drawer's Tab trap relies on `getComputedStyle(...).display` to skip hidden controls.
- Review findings L2–L6 and L9 are still open, by design (not in scope).

### M10 remediation follow-up (2026-11-04, local; same branch, not committed)

Owner-authorized: fix the flaky Playwright test, rerun the suites, and do a read-only review of the
remediation. **M10 remains In Progress.** No database, migration, model call, network or dependency
install was involved.

**Flaky test fixed** (`frontend/web/e2e/preview.layout.spec.ts`, "the streaming cursor does not
blink under reduced motion"):
- **Cause:** the cursor exists only while the preview answer streams (a few hundred ms). The test
  found it, then read its style in a second round trip; when the stream ended in between, the
  element was gone (`NaN`, or `locator.evaluate` timed out).
- **Fix:** a `MutationObserver`, installed before the message is sent, reads the cursor's computed
  animation inside the browser in the same task that adds it. The test then waits for that record.
- **Intent kept:** the cursor must still appear, or the wait times out and fails. The test now also
  asserts the animation name matches `blink`, so it checks the real animation, not `none`.
- **Negative control** (a temporary spec, run and then deleted, not in the repository): with
  reduced motion off, the same observer saw `1s` / `infinite` in 3 of 3 runs. So the check really
  distinguishes the two cases.
- No application code changed.

**Results** (local, Windows, 2026-11-04):

| Command | Result |
|---|---|
| `npx playwright test --project=preview e2e/preview.layout.spec.ts -g "streaming cursor" --repeat-each=10` | **20 passed** (10 per theme; before the fix: 3 of 6 failed) |
| the temporary negative control, `--repeat-each=3` | 3 passed (saw `1s` / `infinite`); file deleted afterwards |
| `npx playwright test --workers=2` (the CI worker count; the config uses the default locally) | **66 passed**, 0 failed; no Node process left |
| `npx tsc -b` | pass |
| `npm run lint` | exit 0 (1 warning, the Uploader) |

Not re-run in this follow-up (unchanged since the remediation run): the backend unit suite
(2,461 passed), Vitest (318 passed), the build.

**Read-only review of the remediation:**
- **Transaction ownership (M1), verified by reading:**
  - all four paths commit after the reply, its citations and the conversation touch are saved, and
    before the caller learns the message id;
  - nothing writes after the commit;
  - the only callers of `RAGService` are the two RAG routes, which write nothing afterwards;
  - the A2A research agent deliberately does not use `RAGService`.
- **Rollback:**
  - a model failure rolls back explicitly before any commit (tested);
  - a failed commit raises before `[DONE]` or the JSON response (tested with a fake);
  - **assumption, not verified:** that `get_session` then rolls back the real session. It either
    receives the exception, or its own `commit()` fails again on the failed session and its
    `except` rolls back. This needs a real database.
- **Overview (M2):** the validators match the backend schemas. **Finding F1 (Low; fixed
  2026-11-04, see the F1–F3 record):** a 2xx whose
  body is not JSON makes `requestJson` throw a `BackendError` (`malformed_response`), not a
  `MalformedDataError`. The card then says "the request to the backend failed" instead of
  "answered without usable data". It is never shown as zero (decision 11 holds); the wording is
  wrong and there is no test.
- **Drawer (M3, L8):** the trap, the focus targets and the listener clean-up match the code.
  - **Finding F2 (Low; fixed 2026-11-04):** when the window widens with focus on the Menu/Close
    button, the drawer
    closes but focus stays on that button, which is now hidden. Keyboard focus is then lost until
    the next Tab.
  - **Finding F3 (Low; fixed 2026-11-04):** only `<main>` is made `inert`. The top bar (theme switch, sign-out) stays
    reachable for a screen reader's virtual cursor while the drawer is open; Tab cannot reach it.
- **Citation identity (L1):** pair matching in the repository and the double check in
  `_resolve` are as recorded. Neighbours are read only after that check passes.
- **DOCX headings (L7):** nothing else builds `ExtractionResult.headings`. The new type is a tuple
  of tuples, which crosses the isolated-extraction process boundary. A style-lookup failure is
  confined to that paragraph; any other parsing failure is still an `ExtractionError`, as before.
  The known limitation is unchanged: a leading BOM-only or non-ASCII-whitespace-only line shifts
  the ordinals, and the prefix check then skips the headings.
- **This file:** the stale remediation statements are corrected above, including the misrecorded
  pytest paths.

### M10 follow-up findings F1–F3 record (2026-11-04, local; same branch, not committed)

Owner-authorized: fix the three Low findings from the remediation review. **M10 remains In
Progress.** No backend change, database, migration, model call, network or dependency install.

**F1: a 2xx with an invalid JSON body is unusable data, not a failed request.**
- `frontend/web/src/api/overview.ts`: a new `successfulBody()` turns the client's
  `malformed_response` error (a 2xx whose body does not parse) into `MalformedDataError`.
- Every other error passes through unchanged: a non-2xx stays a request failure, even with a
  non-JSON body.
- The three states are kept:
  - failed request: "the request to the backend failed";
  - unusable data (204, empty, invalid JSON, wrong shape): "answered without usable data";
  - a genuine zero or empty list, shown as such.

**F3: assistive technology reaches only the drawer while it is open.**
- **The Close control moved into the drawer:** `Sidebar` renders a "Close navigation" button in
  its header only while it is open as a drawer.
- **Two sibling `inert` regions while open:** the skip link, and one wrapper around the top bar and
  `<main>`. `<main>` no longer has its own `inert`, so no inert region is nested and none contains
  the drawer.
- **The top-bar Menu button** (now `id="app-menu-button"`) is inside the inert region while the
  drawer is open. It keeps one label, "Open navigation", and `aria-expanded` gives its state; it no
  longer turns into a Close button.
- **Focus:** the Tab trap cycles through the drawer only. Escape, the backdrop and the drawer's
  Close button return focus to the Menu button, after `inert` is lifted in the same render.
  Following a link moves focus to `<main>`.

**F2: no focus left on a hidden control after widening to desktop.**
- `AppShell`: on crossing 768 px the drawer closes. If focus is no longer on a usable element (the
  drawer's Close button is removed), it moves to the current page's link in the sidebar, which is
  visible beside the content (or to the first link if none is current).
- Focus already on a sidebar link stays there.

**Tests:**
- `OverviewPage.test.tsx` (+3): a 200 with an HTML body and a 201 with JSON cut off are unusable
  data; a 502 with an HTML body is still a failed request.
- `AppShell.test.tsx`: the drawer block was rewritten (net +2, 18 in the file):
  - exactly two inert regions, not nested, not containing the drawer, covering the top bar (banner),
    the Menu button and `<main>`;
  - closing with Escape, the backdrop or the drawer's Close button lifts every inert region and
    focuses the Menu button;
  - the Tab trap; navigation focus to `<main>`;
  - F2: widening with focus on the Close button moves it to the current link, and the listeners
    are removed; widening with focus on a link keeps it.
- `e2e/preview.shell.spec.ts` (14, 7 per theme):
  - **F3 in Chromium's real accessibility tree**, read locally through the DevTools protocol.
    Closed, the banner, `<main>`, the Menu button and the theme radios are exposed. Open, none of
    them, the page heading or the skip link are; the "Main" navigation, its links and "Close
    navigation" are. After Escape they return;
  - the Tab/Shift+Tab trap;
  - navigation focus;
  - the backdrop and Close button focus return;
  - **F2:** widening with focus on the Close button moves it to the visible current-page link,
    with no `[inert]` left;
  - L8 with focus on a link.

**Results** (local, Windows, Node 24.14.0, 2026-11-04, after the last edit):

| Command | Result |
|---|---|
| `npx vitest run src/pages/OverviewPage.test.tsx` | 14 passed |
| `npx vitest run src/components/Shell` | 18 passed |
| `npx playwright test --project=preview e2e/preview.shell.spec.ts --workers=2` | 14 passed |
| `npx tsc -b` | pass |
| `npm run lint` | exit 0 (1 warning, the Uploader; limit 1) |
| `npm run build` | pass; JS 407.53 kB / **122.50 kB** gzip (budget 143 kB); CSS 39.58 kB / 7.53 kB |
| `npx vitest run --maxWorkers=2` | **28 files, 323 tests passed** (was 318) |
| `npx playwright test --workers=2` | **70 passed**, 0 failed (was 66); no Node process left |

- Not run (no backend change): the backend suites.
- Not verified: a real screen reader (NVDA, VoiceOver). Chromium's accessibility tree is the
  automated stand-in.

**Remaining risks:**
- `inert` needs a current browser (Chromium, Firefox and Safari support it). Only Chromium is
  tested.
- The Tab trap still skips hidden controls by checking `getComputedStyle(...).display`.
- While the drawer is open, the top bar's Menu button reports `aria-expanded="true"` from inside an
  inert region; that is intended, since it cannot be reached then.

### M10 database verification record (2026-11-04, local; same branch, not committed)

**Owner authorization (2026-11-04):**
- apply `0009` to the local `aegis_test`, and run the database-backed integration tests against
  it;
- run the migration round trip on the disposable CI PostgreSQL when the PR workflow runs;
- production migration is **not** authorized.

**Documentation corrected first:**
- ADR 007 "Commit ownership": `RAGService` commits itself on all four paths. Rollback is
  unchanged. Callers may not add writes to the transaction afterwards.
- ADR 018 §5: commit before `[DONE]`.
- ADR 018 §6: the four log reasons, including `document_mismatch`.
- `data-flow.md`: the RAG sections, with the commit before `[DONE]` in the stream diagram. The chat
  flow is unchanged and still uses the ambient commit.
- This file: the CI instruction (a plain push runs no workflow; a pull request into `main` runs the
  CI `test` job with migrations and the round trip).
- The protected operations documents and the handover files were not touched.

**Target verification** (`uv run python scripts/test_db.py check`; output filtered so the user name
and password are never shown):
- the guard's rules passed before connecting: `localhost:5432`, `postgresql+asyncpg`, no query
  parameters, a name ending in `_test`, different from the development `DATABASE_URL`;
- in a read-only session the server reported `current_database()` = **`aegis_test`**;
- PostgreSQL **18.6** (CI uses `pgvector/pgvector:pg16`); `vector` installed;
- revision **`0008`**; exit 1 ("not migrated"), as expected.

**Migration:**

| Command | Result |
|---|---|
| `uv run python scripts/test_db.py migrate --yes` | exit 0: `Running upgrade 0008 -> 0009, add message citations` (transactional DDL); "Alembic revision now: 0009" |
| `uv run python scripts/test_db.py check` (again) | exit 0: revision **0009** (code expects 0009); "Ready" |

**Integration tests** (`HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1` set as a safeguard against any
model download; no `RUN_*` or `GROQ*` variable set, checked by name only):

| Command | Result |
|---|---|
| `uv run pytest backend/tests/integration -rs -q -p no:cacheprovider` | **exit 0: 120 passed, 25 skipped** (76 s) |
| `uv run pytest backend/tests/integration/test_citation_isolation.py backend/tests/integration/test_document_file_isolation.py backend/tests/integration/test_rag_flow.py backend/tests/integration/test_data_isolation.py -v -rs -p no:cacheprovider` | **exit 1: 46 passed, 1 FAILED** |

- **All 25 skips are by design:** live A2A, MCP, multi-agent, Groq, embedding and RAG end-to-end
  flags not set; Redis not running (5 + 2); and `RUN_MIGRATION_ROUNDTRIP` not set (2).
- **Passed in both runs:**
  - `test_citation_isolation.py` (13 cases): exact passage for the owner; 404 for the four
    others; revocation; a deleted document; another tenant's chunk; a tampered hash; neighbours;
    a reopened conversation; cascade on delete; saving for someone else's message refused;
  - `test_document_file_isolation.py` (4): exact bytes as an attachment; 404 for the others, like
    a guessed id; sharing and revoking; a deleted document;
  - `test_rag_flow.py` (4): the RAG flow after the `RAGService` commit change.
- **FAILED in the second run only:**
  `test_data_isolation.py::test_a_colleague_who_can_read_a_shared_document_cannot_change_or_delete_it`.
  - It passed in the full run a few minutes earlier.
  - Error: `sqlalchemy.exc.MissingGreenlet`, raised in `set_document_visibility`
    (`app/api/v1/documents.py:196`) when `DocumentResponse.from_document` reads an expired
    `document.updated_at`.
  - **Not an M10 change:** `git diff` is empty for the `Document` model, `document_repository.py`,
    `api/schemas/documents.py`, `db/session.py`, `app/core/`, the test and its conftest.
  - `DocumentRepository.set_visibility` already sets `updated_at = datetime.now(UTC)` to avoid
    exactly this error.
  - **Likely cause (a hypothesis, NOT verified):** when the new timestamp equals the stored one
    (the Windows clock is coarse, and the upload and the share happen within one tick), SQLAlchemy
    sees no change to `updated_at`. It applies `onupdate=func.now()` server-side anyway (because
    `visibility` changed), which expires the attribute.
  - **Work stopped at this failure, as instructed.**
- **Not verified, because work stopped:**
  - rollback after a failed commit against the real database: no integration test exists; it is
    covered by unit tests with fakes only;
  - a re-run to confirm the failure is intermittent;
  - a fix.
- **Migration round trip: NOT RUN locally.** `RUN_MIGRATION_ROUNDTRIP=1` makes
  `test_identity_migration.py` and `test_ownership_migration.py` connect to the server's `postgres`
  maintenance database, `CREATE DATABASE` a throwaway database and `DROP DATABASE ... WITH (FORCE)`
  it afterwards. Creating and dropping databases was not authorized locally, and the round trip
  was authorized only on the disposable CI database.
  - In CI, `test_ownership_migration.py` upgrades to head and downgrades to `0005`, so it also
    exercises `0009`'s downgrade.

**(Resolved 2026-11-04: root cause established and fixed; see the next record.)** Owner decision
needed at the time: how to handle the intermittent `MissingGreenlet` failure before the PR, since CI
runs the same test. Options:
- make `set_visibility` refresh `updated_at` after the flush;
- assign a value guaranteed to differ;
- remove the server-side `onupdate` for this path.

### Document visibility `MissingGreenlet` fix record (2026-11-04, local; same branch, not committed)

Owner-authorized: investigate and fix the intermittent failure of
`test_data_isolation.py::test_a_colleague_who_can_read_a_shared_document_cannot_change_or_delete_it`,
using only the migrated local `aegis_test`. **Not an M10 regression:** none of the files involved
had been changed on this branch.

**Root cause (established by a deterministic reproduction):**
1. `Document.updated_at` (`app/domain/models/document.py`) has a Python `default` and
   `onupdate=func.now()`: a SQLAlchemy `onupdate` that renders as SQL, not a database trigger.
2. `DocumentRepository.set_visibility` assigns `updated_at = datetime.now(UTC)` before flushing,
   so that the server-side `onupdate` is not used.
3. When the assigned value **equals** the value the object already holds, SQLAlchemy records no
   change for `updated_at`. Because `visibility` did change, the UPDATE still runs, the column's
   `onupdate=func.now()` is applied in SQL, and the ORM **expires** `updated_at`: it cannot know the
   server's value.
4. The route builds the response (`DocumentResponse.from_document`) from that object outside an
   awaited call. Reading the expired attribute starts a synchronous lazy load, which async
   SQLAlchemy refuses with `MissingGreenlet`. The traceback runs `set_document_visibility` →
   `from_document` → `_load_expired`.
5. **Why the values collide:** on this machine Python 3.12.12 uses `GetSystemTimeAsFileTime()`
   (reported resolution 15.625 ms). Measured: 200,000 consecutive `datetime.now(UTC)` calls gave
   only 20 distinct values, ticking about every 1.1 ms.
   - The test's `client` shares one `db_session`, so the upload's `Document` stays in the identity
     map with the `updated_at` that processing assigned (`finished_at`).
   - A share request within the same tick assigns the identical value.
   - **Reproduction:** with the repository's clock frozen to the stored value, the 3 new tests
     failed with exactly this `MissingGreenlet` before the fix (3 of 3).
6. `expire_on_commit=False` (`app/db/session.py`) is not involved: the attribute is expired by the
   flush, not the commit.

**Fix (smallest safe change):** `app/db/repositories/document_repository.py`,
`DocumentRepository.set_visibility`:
- after the flush, if `updated_at` is in `sqlalchemy.inspect(document).expired_attributes`, run
  `await self._session.refresh(document, attribute_names=["updated_at"])`;
- this reloads it inside the same async call and transaction, before the route serializes the
  response;
- when there is no collision, no extra query runs;
- there is no model, schema, migration or route change.

**Regression test:** `backend/tests/integration/test_document_visibility_timestamp.py` (3). Each
freezes the repository's clock to the document's stored `updated_at`, so the collision happens on
every run and on any platform:
- sharing returns 200 with `visibility: "organization"`, and the returned `updated_at` equals the
  database value and is no longer expired; the test also asserts that the collision really
  happened;
- making a shared document private within the same tick returns 200;
- the collision changes no authorization: the colleagues alan and ada can read it; bob and bea
  (another organization) get 404; alan still cannot change it (404).

**Results** (local, Windows, against the verified `aegis_test` at `0009`; `HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1` as a safeguard):

| Command | Result |
|---|---|
| `uv run pytest backend/tests/integration/test_document_visibility_timestamp.py` **before** the fix | **3 failed**, all with `MissingGreenlet` |
| the same, **after** the fix | **3 passed** |
| `uv run pytest "backend/tests/integration/test_data_isolation.py::test_a_colleague_who_can_read_a_shared_document_cannot_change_or_delete_it"` × 20 (shell loop) | **20 passed, 0 failed** |
| the four-file run that failed earlier (`test_citation_isolation.py`, `test_document_file_isolation.py`, `test_rag_flow.py`, `test_data_isolation.py`) × 3 | **47 passed** each time |
| `uv run pytest backend/tests/integration -rs -q -p no:cacheprovider` | **exit 0: 123 passed, 25 skipped** (the same 25 by-design skips as before) |
| `uv run pytest backend/tests/unit -q -rs -p no:cacheprovider` | 2,461 passed, 1 skipped (unchanged) |
| `uv run ruff check .` / `ruff format --check .` / `pyright` | All checks passed / 534 files formatted / 0 errors |
| `uv run python scripts/test_db.py check` | `aegis_test` still at `0009`, "Ready" |

**Not run:** the migration round trip (not authorized locally: it creates and drops a throwaway
database; it runs in CI). Rollback after a failed commit against the real database is still not
covered by an integration test.

**Remaining risks:**
- **The same pattern exists, unfixed, in document processing** (`DocumentService`, which sets
  `document.updated_at = finished_at` on success and on failure). If `finished_at` equalled the
  insert-time value, the upload response could hit the same error. It was not observed: extraction
  runs in a child process and takes much longer than a clock tick. Not changed (outside this fix's
  scope).
- A broader alternative would be `eager_defaults=True` on the `Document` mapper, which fetches
  server-side `onupdate` values with RETURNING. It would change every `Document` flush, so it was
  not chosen.

### M10 pre-PR cleanup record (2026-11-04, local; same branch, not committed)

Owner-authorized controlled cleanup. **M10 remains In Progress.** No database access, migration,
network, dependency install or model call.

**Fixed:**
- **L2:** an unavailable citation in a reopened conversation no longer exposes `passage_truncated`.
  - `MessageCitationSummary.passage_truncated` is now `bool | None`, null for unavailable, like
    every other source-describing field.
  - This matches the endpoint's `UnavailableCitation`, which has no such field.
  - Frontend type: `boolean | null`. `CopilotPage` maps it only for available citations.
- **L3:** neighbouring citation text is `neutralize_markers(chunk.content)`, exactly like the cited
  passage. Neighbours are still read only when the cited source is available (hash and read filter
  unchanged), and only from the same readable document.
- **L9:** `DocumentViewerPage` stops loading at the total the backend reports. A `?chunk=` at or
  beyond the end loads the first page only.
- **The tautological assertion** in `test_document_visibility_timestamp.py` is replaced: the test
  now records `session.refresh` calls and asserts the repository reloaded exactly `updated_at` of
  that document, which happens only on the collision path.
- **Docs:**
  - ADR 018 §5 and `data-flow.md`: `[DONE]` confirms a reply, but its absence does not prove
    nothing was saved. A connection lost between the commit and `[DONE]` leaves a committed reply,
    and the client treats a stream without `[DONE]` as unconfirmed.
  - ADR 018 §6 and §7: L3 and L2.
  - ADR 007: unit-test evidence kept apart from database-backed evidence; rollback after a real
    commit failure marked not yet verified.
  - The `CopilotPage` comment on unfinished streams is corrected the same way.
  - The stale status lines in this file are corrected.

**Tests and results** (local, Windows, 2026-11-04):

| Command | Result |
|---|---|
| `uv run pytest backend/tests/unit/services/test_citation_service.py backend/tests/unit/api/test_conversations_endpoint.py -q -p no:cacheprovider` | 47 passed |
| `uv run pytest backend/tests/unit -q -rs -p no:cacheprovider` | **2,463 passed, 1 skipped** (the by-design skip) |
| `uv run ruff check .` / `ruff format --check .` / `pyright` | All checks passed / 534 files formatted / 0 errors, 0 warnings |
| `uv run pytest backend/tests/integration/test_document_visibility_timestamp.py --collect-only` | 3 collected (**not run**: database access not allowed in this task) |
| `npx vitest run src/pages/DocumentViewerPage.test.tsx src/pages/CopilotCitations.test.tsx` | 18 passed |
| `npm run lint` / `npx tsc -b` / `npm run build` | exit 0 (1 warning, the Uploader) / pass / pass, JS 122.51 kB gzip |
| `npx vitest run --maxWorkers=2` | **28 files, 326 tests passed** (was 323) |
| `npx playwright test --workers=2` | **70 passed** |

- New tests:
  - backend unit +2 (L3): neighbours neutralized; an unavailable source still gives no neighbours,
    whether from a tampered hash or an unreadable document;
  - the L2 expectation updated in `test_conversations_endpoint.py`;
  - Vitest +3 (L9): indexes 450 and 99,999 of 450 make one request and load 200 passages; index
    449 still loads (3 requests).
- **NOT RUN:**
  - the edited `test_document_visibility_timestamp.py` (it needs `aegis_test`; it passed in its
    earlier form). It will run on the PR's CI, or locally when database access is next
    authorized;
  - the integration suite as a whole after this cleanup. No integration assertion depends on the
    changed fields: the neighbour test checks indexes only, and no integration test reads an
    unavailable summary's `passage_truncated`.

### M10 known risks and deferred decisions (open; NOT resolved)

| Item | Status | Evidence | Needs |
|---|---|---|---|
| **L4** download limits | Deferred to the owner | `GET /documents/{id}/file` has no rate limit (upload and embedding have one); the whole file, up to 20 MB, is read into memory; only `FileNotFoundError` and `ValueError` are mapped, so other storage errors give a 500 | A rate-limit and streaming decision |
| **L5** downloads by status | Deferred to the owner | `get_original_file` serves failed and processing documents (the upload was validated either way) | Confirm or restrict |
| **L6** fingerprint retention | Deferred to M9.5 | `message_citations` keeps the passage SHA-256 and length after the document is deleted | The M9.5 retention policy |
| **`DocumentService` processing timestamp** | Risk, unverified | Processing sets `updated_at = finished_at`, and the upload response reads it. A value equal to the insert-time one would expire it (the `set_visibility` pattern). Not reproducible through real paths, because extraction always runs in a child process (`IsolatedExtractionRunner`) | Fix with the same refresh if ever observed |
| **Rollback after a real commit failure** | Not verified | Unit tests with doubles only; no integration test makes PostgreSQL reject a commit | A database-backed test, if wanted |
| **A reply committed without `[DONE]`** | Accepted design (documented) | A connection lost between the commit and `[DONE]` leaves a saved reply the client treated as unconfirmed; it reappears on reopening | Acceptance as a known limitation |
| **Migration round trip** | Pending in CI | Not run locally (it creates and drops databases); `test_ownership_migration.py` goes from head down to `0005` | The PR's CI run |

### PR #37 Trivy blocker: libexpat fix record (2026-11-05, local; on top of `8d242dc`, not committed)

**Blocker (owner-reported, from the `trivy-reports` SARIF artifact of PR #37; the artifact itself
was not read here):**
- image `aegisai-frontend`, Alpine Linux 3.24.2;
- package `libexpat`, installed `2.9.0-r0`, Trivy's fixed version `2.10.0-r0`;
- blocking HIGH CVEs: CVE-2026-113351, CVE-2026-117610 and CVE-2026-118370;
- also CVE-2026-115506 (UNKNOWN severity; not blocking under the CRITICAL/HIGH policy).

**Source of the package (read from the code):**
- `libexpat` is inherited unchanged from the pinned runtime base image
  `nginxinc/nginx-unprivileged:1.30.6-alpine@sha256:f5116ed4…cdf03` in `frontend/web/Dockerfile`;
- no installation step in the Dockerfile names it;
- the `node:22-slim` builder stage is not shipped.

**Package availability (official Alpine sources, read-only web access, 2026-11-05; not inferred
from Trivy):**
- `https://pkgs.alpinelinux.org/packages?name=libexpat&branch=v3.24&arch=x86_64` lists
  `libexpat 2.10.0-r0`, branch v3.24, repository `main`, architecture x86_64, built
  2026-11-02 13:12:51;
- `https://dl-cdn.alpinelinux.org/alpine/v3.24/main/x86_64/` contains `libexpat-2.10.0-r0.apk`
  (02-Nov-2026 13:28, 62K), the only `libexpat` file listed, together with `expat`,
  `expat-dev`, `expat-doc` and `expat-static` 2.10.0-r0;
- aarch64 was not checked (CI builds amd64 only).

**Change (owner-approved minimal fix):**
- `frontend/web/Dockerfile`: `"libexpat>=2.10.0-r0"` added to the existing
  `apk add --no-cache` floor list, and its comment updated from six packages to seven. The pinned
  base digest, the Alpine release, nginx and every other floor are unchanged.
- `backend/tests/unit/test_frontend_proxy_config.py`
  (`test_runtime_package_fixes_are_narrow_minimum_versions`): `"libexpat": "2.10.0-r0"` added to
  the expected floors, and its docstring updated from six to seven (re-wrapped to the
  100-character line limit; no other change).
- **No CVE suppressed or ignored; the security policy is unchanged.**

**Local results** (Windows, 2026-11-05, after the last edit):

| Command | Result |
|---|---|
| `uv run pytest backend/tests/unit/test_frontend_proxy_config.py` | **14 passed**, exit 0 |
| `uv run ruff check backend/tests/unit/test_frontend_proxy_config.py` | All checks passed |
| `uv run ruff format --check backend/tests/unit/test_frontend_proxy_config.py` | 1 file already formatted |

**Not verified:**
- the image build and the Trivy rescan: there is no Docker locally. They run in the PR's
  `Container image scan (Trivy)` job once the owner pushes this change;
- whether `2.10.0-r0` also resolves CVE-2026-115506 (check the next report);
- that the base image's `/etc/apk/repositories` points at `dl-cdn.alpinelinux.org` (standard for
  Alpine images; not inspected). If the floor cannot be met, the build fails visibly instead of
  shipping 2.9.0.

### M10 acceptance criteria (targets, not results)

- **Contrast (WCAG 2.2 AA):** 4.5:1 for normal text, and 3:1 for interface components and
  graphical objects where applicable.
- **Accessibility:**
  - no serious or critical automated accessibility findings;
  - keyboard access to citation panels, with correct focus management and return;
  - streamed answers announced accessibly;
  - reduced-motion preferences respected.
- **Responsive:** verified at 375 px, 768 px and 1280 px.
- **Citation security:**
  - cross-tenant access to documents, chunks and saved citations discloses no content and
    returns an appropriate unavailable response;
  - revoked or deleted documents do not leak previously saved passage text.
- **Citation truthfulness:**
  - citation source states are derived from actual backend facts;
  - no "Supported" status without a separately evaluated claim-level check.
- **Preservation:** all existing backend and frontend behaviour and tests are preserved, and actual
  test counts and results are recorded after each implementation task.

### M10 recommended implementation order

1. M10.0 — baseline and testing foundations.
2. M10.4 — citation API and persistence (engineering; does not depend on the Apple Design Skill).
3. M10.1 — design tokens and themes.
4. M10.3 — conversation experience.
5. M10.5 — citation source panel.
6. M10.2 — application shell and navigation.
7. M10.6 — document viewer.
8. M10.8 — remaining frontend pages.
9. M10.7 — evidence verification, after the D-5 design and evaluation criteria are agreed.
10. M10.9 — section metadata, after a separate design review.

### M10 risks and constraints

- **Apple Design Skill:**
  - It has no declared licence and contains Apple's reproduced guideline text. Never commit,
    redistribute or ship its files.
  - Do not copy native Apple platform conventions into the web application.
  - Do not use SF Pro, SF Symbols or Apple artwork.
  - WCAG 2.2 AA is authoritative over differing Apple platform targets.
- **Copy style:** keep sentence-case interface copy consistent.
- **PDF highlighting:** exact highlighting may be approximate, because extracted and normalized
  text can differ from the original document's layout.
- **Saved citations:** they must not bypass current authorization; avoid storing document text in
  saved citation references.
- **PDF viewer:** its dependencies may increase bundle size and require Content-Security-Policy
  changes.
- **Claim-level verification:** may add model costs, latency, and false positives or negatives.
- **Progress tracking:** keep the single-document convention (root `CLAUDE.md` only; no
  `UPDATE.md`, `CHANGES.md` or other progress files).

## Blockers and risks (2026-11-02)

- **P0:**
  - no image registry or release pipeline; no ARM64 image has been built or run;
  - the staging target is unverified, and no staging deployment has occurred;
  - no secrets-management procedure; no deployed OIDC provider;
  - no automated backups, and a restore has never been rehearsed.
- **P1:**
  - OCI Always Free limits (storage minimums, idle reclamation, ARM capacity);
  - the backend's 1 Gi memory limit is unmeasured;
  - the embedding model is downloaded from Hugging Face at each start (revision not pinned);
  - the smoke test and live RAG evidence are stale;
  - no tracing or alerts; no load or failure tests;
  - the ruleset bypass list is unknown; `actions/checkout` targets Node 20.
- **P2:**
  - Responsible AI policies; hybrid retrieval and reranking; semantic memory recall; semantic caching;
  - the remaining base images are not pinned by digest;
  - `readOnlyRootFilesystem: false` on the backend;
  - a single backend replica (ReadWriteOnce uploads volume);
  - the React lint warnings (3 before M10.0; 11 after it; 1 since M10.8, the Uploader's
    `role="button"`); the flaky extraction-deadline test. (The flaky Playwright reduced-motion
    cursor test was fixed on 2026-11-04; see the remediation follow-up.)

## Next recommended task

**Update 2026-11-04 (after the review remediation):**
- Findings M1, M2, M3, L1, L7, L8 and L10 are fixed locally (see the remediation record). M10 is
  **not** complete.
- **Owner actions:**
  - review the remediation;
  - (Done 2026-11-04: `aegis_test` migrated to `0009` and the integration suite run; 123 passed.
    The round trip is pending in CI.)
  - (Corrected 2026-11-04.) Pushing the feature branch alone runs **no** workflow: `ci.yml` and
    `security.yml` run only on a push to `main` or a **pull request into `main`**, and the other
    workflows are manual. Opening that pull request runs the CI `test` job, which:
    - starts a disposable `pgvector/pgvector:pg16` database;
    - runs `alembic upgrade head` (so `0009`);
    - sets `RUN_MIGRATION_ROUNDTRIP=1` (the downgrade/upgrade round trip);
    - runs the whole pytest suite, including the integration tests.

    That disposable CI database was authorized by the owner on 2026-11-04; production was not;
  - decide D-5 (ADR 019), the decision 9 deviation, the Inter font, agent citations (T9) and PDF
    viewing (`pdfjs-dist`);
  - decide the open review findings L2–L6 and L9;
  - (Done 2026-11-04: the flaky reduced-motion cursor test is fixed; see the follow-up record.)
  - (Done 2026-11-04: the follow-up findings F1–F3 are fixed; see the F1–F3 record.)

**Update 2026-11-03 (full M10 mission, in progress):**
- M10.4 backend (T1–T8) is implemented locally; see the T4–T8 record. Next in the agreed order:
  M10.1, M10.3, M10.5, M10.2, M10.6, M10.8, M10.7, M10.9.
- M10.1, M10.3 and M10.5 are implemented locally (see their record). Next: M10.2, M10.6, M10.8,
  M10.7, M10.9.
- M10.2 is implemented locally (2026-11-04; see its record). Next: M10.6, M10.8, M10.7, M10.9.
- M10.6 is implemented locally (2026-11-04; see its record). Next: M10.8, M10.7, M10.9.
- M10.8 is implemented locally (2026-11-04; see its record). Next: M10.7, M10.9.
- M10.7: the offline evaluation is built and its gate fails (see its record; ADR 019 Proposed). **Owner decision needed: D-5 and the gate criteria.** Next: M10.9.
- M10.9 is implemented locally (2026-11-04; see its record). **Every M10 phase now has a local
  implementation; none is marked Completed**, because each still needs evidence only the owner
  can provide: a CI run, the migrated test database, a human visual and screen-reader review, and
  the D-5 decision.
- (Done 2026-11-04: `aegis_test` migrated to `0009`; integration suite 123 passed, including
  both isolation suites. Still open: the migration round trip, pending in CI.)

**Update 2026-11-03 (T3 implemented; kept for history):**
- **Review M10.4 T3 (owner action):** see the M10.4 T3 implementation record. On
  `feature/m10-citation-passage-metadata`: 15 modified and 3 new files (T1 + T2 + T3), all
  uncommitted.
- **T4 is not authorized.** When it is, it must apply the similarity rule (reject non-finite,
  clamp finite) and add `message_id`.
- **Decision needed:** migrating the local `aegis_test` to `0009`, and running the migration
  round trip against a disposable database. Until then, the local database-backed tests are
  NOT RUN.
- **Documentation for T8:** `data-flow.md`, `infra/kubernetes/README.md:148`, and (with approval)
  the two protected operations documents.

**Update 2026-11-03 (T2 accepted; kept for history):**
- M10.4 T2 was formally accepted by the owner after review. T1 and T2 are both accepted and still
  uncommitted (10 modified files; the owner handles Git).
- **T3 and T4 remain unauthorized.**
- **Open documentation item for T8:** the stale `answer_stream` example in
  `docs/architecture/data-flow.md` (see the T2 post-review notes).

**Update 2026-11-03 (after T2; kept for history):**
- **Review M10.4 T2 (owner action):** see the M10.4 T2 implementation record. 10 files are
  modified and uncommitted on `feature/m10-citation-passage-metadata` (T1 + T2).
- **T3 and T4 are not authorized.** T4 carries `message_id`, as decided on 2026-11-03.
- **Database restrictions unchanged:** migration `0009` (T3) may only be written and checked
  offline; nothing may be applied without separate approval.

**Update 2026-11-03 (before T2; kept for history):**
- **Review M10.4 T1 (owner action):** the uncommitted changes on
  `feature/m10-citation-passage-metadata` (see the M10.4 T1 implementation record).
- **T2 is not authorized yet.** It, and each later M10.4 task, needs separate owner approval. The
  assessment's open decisions were answered on 2026-11-03 (see "M10.4 approved decisions").
- **T1 review evidence, re-checked 2026-11-03:** the assembler tests (51 passed) and the RAG unit
  tests (152 passed) pass, and ruff, the format check and pyright pass on the changed files; the
  operations docs show no diff. (Interim figures; the final T1 results are 60, 161 and
  2,260 passed. See the M10.4 T1 implementation record.)
- **T1 formally approved by the owner (2026-11-03).** T2 is still not authorized.
- **Not checked:** the result of M10.0's CI run on PR #36. M10.0 stays In Progress until it is
  recorded.

The text below is the 2026-11-02 recommendation, kept for history. M10.0 has since been merged
(PR #36).

**Finish M10.0 (owner action):** the review corrections are done. Review the local M10.0 changes
(including the corrective pass), then commit them on a branch and open a pull request, so the
extended `frontend-react-test` job runs on GitHub. M10.0 can be marked Completed only after that CI
run passes.

On that first run, watch two things:
- whether the axe element counts and the overflow page sets measured on Windows hold on Linux;
- whether the `docker-build` and Trivy jobs pass now that `tsc -b` also checks the Playwright files.

The owner handles Git; nothing has been staged or committed.

**After that, in the approved order:** M10.4 (citation API and persistence), **awaiting explicit
owner approval**. Not started. The Apple Design Skill installation and its `.gitignore` change are
still separately pending.

**Paused (not cancelled):** M9.2, the image registry and multi-architecture release pipeline,
including the registry and embedding-model decisions, and the rest of M9 and the Oracle Cloud
deployment. Resume only with the owner's approval. The open M9.1 items (alert and scan-report
review, the ruleset bypass list) still need a signed-in GitHub account.
