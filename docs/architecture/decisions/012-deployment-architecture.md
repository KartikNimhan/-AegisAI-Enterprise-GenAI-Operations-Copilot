# 12. Deployment Architecture: Docker, Compose, and Kubernetes Foundation

## Status

Accepted — 2026-10-09

## Context

Milestones M0–M9 built a complete, tested application: a FastAPI backend
(modular monolith — [ADR 001](001-modular-monolith.md)) and a Streamlit
frontend ([ADR 011](011-copilot-ui-architecture.md)), backed by Postgres
+pgvector and Redis. A root-level `Dockerfile` and `docker-compose.yml`
already existed (backend + Postgres + Redis — no frontend container, no
Kubernetes manifests, no `.dockerignore`). Milestone 10's job is to make
this *existing* system reproducibly runnable in containers and provide a
Kubernetes deployment foundation — explicitly **not** to redesign the
application, introduce a second orchestration/config system, or fabricate
a cloud deployment this project hasn't actually made.

## Decision

### What already existed vs. what this milestone added

| | Already existed | Added/changed this milestone |
|---|---|---|
| Backend Dockerfile | Single-stage, root, no healthcheck, runs as root, host/port hardcoded | Multi-stage, non-root, `HEALTHCHECK`, configurable `HOST`/`PORT`, now also carries `alembic/`/`alembic.ini` so it can run migrations |
| Frontend Dockerfile | None | New (`frontend/streamlit/Dockerfile`) |
| Compose | `backend`, `postgres`, `redis` | Added `frontend`, a profile-gated `migrate` one-off service, a backend `HEALTHCHECK`, `GROQ_API_KEY` passthrough |
| `.dockerignore` | None | New |
| Kubernetes manifests | None (`infra/kubernetes/` was an empty, committed placeholder directory) | New — see `infra/kubernetes/README.md` |
| CI | lint/typecheck/backend-test/frontend-test | Added a container-build job + a manifest-validation step |

Nothing in `app/`, `frontend/streamlit/{app.py,pages,components,services}`,
or any M0–M9 API contract was changed — only deployment plumbing around
the existing, unchanged application.

### Backend image

Two stages (`builder`/`runtime`): `builder` runs `uv sync --frozen
--no-install-project --no-dev` (uv, the project's established dependency
mechanism — never pip/poetry introduced) into a virtualenv; `runtime` is
a fresh `python:3.12-slim` that copies only that virtualenv plus
`app/`/`alembic/`/`alembic.ini` — no uv, no pip cache, no build toolchain
ships in the final image. A dedicated `app` system user runs the process
(never root); `HOST`/`PORT` are now configurable via environment
variables (previously hardcoded in `CMD`) without touching the
application's own `Settings` (which has no host/port fields — binding
address is a deployment concern, not an application one). `CMD exec
uvicorn ...` (shell form, `exec`) makes uvicorn itself PID 1, so it
receives `SIGTERM` directly from Docker/Kubernetes for a graceful
shutdown — no separate init/supervisor process was introduced. A
`HEALTHCHECK` runs `backend/scripts/docker_healthcheck.py` (copied into
the image), a pure-stdlib script that hits the real `/health` endpoint —
no `curl`/`wget` installed just for this.

`alembic/`/`alembic.ini` are now included in the image specifically so
the *same* image can run `alembic upgrade head` as a one-off command
(see "Migration strategy" below) — not a second image, not a second
dependency-install step.

### Frontend image

Same two-stage pattern, resolving the existing `frontend` dependency
group (`uv sync --group frontend`) instead of the default group. Copies
only `app.py`/`healthcheck.py`/`pages/`/`components/`/`services/` — the
same files `frontend/streamlit/`'s own test suite already exercises, no
more. `AEGIS_BACKEND_URL`/`AEGIS_BACKEND_TIMEOUT_SECONDS` (the two env
vars `services/api/client.py` already reads — see ADR 011) are set as
image defaults (pointing at the Compose service name `backend`) but
remain overridable per-deployment via Compose/Kubernetes config. Health
is checked via Streamlit's own real, built-in `/_stcore/health` endpoint
(confirmed present in the installed package's source, not invented) — the
same endpoint `frontend/streamlit/healthcheck.py` and Kubernetes' probes
both use. Does **not** migrate the UI to React/Next.js/anything else — it
is the exact same Streamlit app, containerized.

### Compose architecture

`backend`, `frontend`, `postgres`, `redis`, plus a new `migrate` service
under the `tools` Compose profile (never started by `docker compose up`
— no `restart` policy, nothing depends on it; invoked explicitly via
`make docker-migrate` / `docker compose run --rm migrate`). `depends_on`
alone was already insufficient before this milestone and remains paired
with real `condition: service_healthy` checks (backend now has its own
`HEALTHCHECK` too, so `frontend`'s `depends_on: backend: condition:
service_healthy` means something real — the frontend doesn't start
serving until the backend has actually passed its own `/health` check,
not merely "the container process started"). `GROQ_API_KEY` is now
passed through from the host shell/a root `.env` file (`${GROQ_API_KEY:-}`
— Compose's own variable-substitution mechanism, a different thing from
the application's `Settings` reading its own `.env` file *inside* a
container, which it never does here) — previously it was silently absent
from the backend service's environment entirely.

### PostgreSQL/pgvector

Unchanged version (`pgvector/pgvector:pg16`, already pinned, not
upgraded) — a newer major version was not evaluated against
`backend/alembic/versions/0001_enable_pgvector.py` and the rest of the
migration history, and the brief is explicit not to upgrade without that
check. The named volume (`pgdata`) was already correct and is unchanged.

### Redis

Already pinned (`redis:7-alpine`, not `:latest`) and unchanged. Confirmed
by inspection (`app/db/redis.py`/`app/dependencies.py`): Redis is
currently used **only** by `check_redis` (the readiness probe) — no
application code anywhere stores real data in it. It is therefore
correctly treated as ephemeral: no named volume was added for it, in
Compose or Kubernetes, and this is now documented rather than left
implicit.

### Configuration, secrets, and the two different ".env" mechanisms

Two genuinely different things share the name "environment configuration"
here, and conflating them is the most common mistake in this kind of
setup:
1. **The application's own configuration** (`app.config.Settings`,
   reusing the Milestone 0 mechanism unchanged — no second config system
   introduced): reads `.env` *inside whatever process runs it*. Inside a
   container, there is no `.env` file (the Dockerfiles never `COPY` one —
   confirmed via `.dockerignore`), so every `Settings` field is populated
   purely from real process environment variables, which is exactly what
   `envFrom: [configMapRef, secretRef]` (Kubernetes) and `environment:`
   (Compose) provide.
2. **Compose's own `${VAR}` substitution**, which *does* read a `.env`
   file in the directory `docker compose` is run from — this is how
   `GROQ_API_KEY: ${GROQ_API_KEY:-}` in `docker-compose.yml` picks up a
   value from a developer's own root `.env` (or their shell) without that
   value ever being baked into an image layer.

Secrets (`GROQ_API_KEY`, `DATABASE_URL` — which embeds the Postgres
password) are never baked into an image and never committed:
`backend-secret.example.yaml`/`postgres-secret.example.yaml` are
templates only (enforced by `validate_manifests.py`, which refuses to
treat a Secret manifest as safe unless it's named `*.example.yaml`,
every field is an obvious placeholder, and no field looks like a real
base64-encoded credential) — the real Secret is created directly via
`kubectl create secret generic ...` or a proper secret-manager
integration, never written to a file in this repository.

### Healthchecks

Both Docker `HEALTHCHECK` instructions and the Kubernetes
liveness/readiness probes reuse the application's **existing** health
semantics, not a new fake endpoint invented for Docker:
- Backend liveness → `/health` (process is up, no dependency check —
  `app.api.v1.health.health`). Deliberately *not* `/health/ready`: an
  outage of Postgres/Redis must not restart every backend Pod in a loop
  (a restart storm fixes nothing if the dependency itself is the problem)
  — this is exactly the brief's own "do not make liveness dependent on
  every external dependency" instruction.
- Backend readiness → `/health/ready` (checks Postgres *and* Redis —
  `app.api.v1.health.readiness`) — a Pod that can't reach its database
  is correctly removed from the Service's endpoints without being
  killed.
- Frontend liveness/readiness → Streamlit's own `/_stcore/health` (no
  meaningful distinction for the frontend: it has no external dependency
  of its own whose outage should change its own probe result — a
  degraded backend is surfaced in-page via `components/errors.py`, per
  ADR 011, not by failing the frontend's readiness probe).

### Migration strategy

Alembic remains the only migration mechanism (no second one introduced).
Migrations are **never** run implicitly by the API server's own startup
(no `lifespan` hook, no entrypoint-script `alembic upgrade head` before
`exec uvicorn`) and never run independently by every replica — both would
risk an unsafe concurrent/partial migration if ever scaled beyond one
backend replica. Instead: the *same* backend image, with its `CMD`
overridden to `alembic upgrade head`, runs as a **separate, explicit
step** — `docker compose run --rm migrate` locally, a one-shot
`batch/v1` `Job` (`infra/kubernetes/migration-job.yaml`) in Kubernetes —
applied/run once, before rolling out a backend image update that needs
it. This is a manual/CI-triggered step in this milestone, not automated
via a Helm post-install hook (no Helm is introduced).

### Kubernetes architecture

`infra/kubernetes/` (the project's own pre-existing, empty placeholder
directory — not a new `deploy/k8s/` convention): plain `kubectl
apply`-able manifests, no Helm/Kustomize overlay, no operator. One
Deployment each for backend/frontend (matching the modular-monolith
architecture — ADR 001 — not split into per-module microservices), one
Service each (`ClusterIP`, internal-only — see "Network security"),
ConfigMaps for non-secret config, Secret *templates* for credentials, a
migration Job, and dev/staging-only Postgres (`StatefulSet` + PVC) and
Redis (`Deployment`, no PVC) manifests. See `infra/kubernetes/README.md`
for the exact apply order and `infra/kubernetes/validate_manifests.py`
for what was actually checked.

### Resource management

`replicas`, `resources.requests/limits`, and the `RollingUpdate` strategy
are all **initial, conservative starting defaults**, explicitly labeled
as such in the manifests' own comments — never presented as benchmark-
derived or production-sized. Backend defaults to `replicas: 1`
specifically because of a real, current architectural constraint (see
"Persistence" below), not an oversight; frontend defaults to `replicas:
2` since it is genuinely stateless (`maxUnavailable: 0` on both means a
rolling update never drops below the configured replica count, though no
load test was run to validate zero-downtime under real traffic — an
honest limitation, not a guarantee).

### Security context

Both Deployments set `runAsNonRoot: true` and `seccompProfile:
RuntimeDefault` at the Pod level, and `allowPrivilegeEscalation: false` +
`capabilities.drop: ["ALL"]` at the container level — no privileged
containers, no host networking/PID/IPC anywhere in these manifests.
`readOnlyRootFilesystem` was deliberately **not** forced: uvicorn/Python
(transient files during multipart upload parsing) and Streamlit (its own
cache/config under `$HOME`) both need a writable path outside the one
location (`/data/uploads`) already on its own volume — the brief
explicitly warns against blindly forcing this if it would break the
application, and it was not audited/emptyDir-mounted-away just to tick
the box.

### Persistence

- **PostgreSQL**: persistent (PVC, `ReadWriteOnce`, in both Compose's
  named volume and the Kubernetes `StatefulSet`'s `volumeClaimTemplates`).
- **Redis**: ephemeral by design — see "Redis" above.
- **Backend**: stateless *except* for uploaded document files
  (`app.storage.local.LocalFileStorage`, writing to `DOCUMENT_STORAGE_DIR`
  on a local filesystem path) — this is a **real, current architectural
  constraint**, not papered over: a `ReadWriteOnce` PVC does not reliably
  share files across more than one Pod, which is exactly why
  `backend-deployment.yaml` defaults to `replicas: 1` rather than
  silently claiming horizontal scalability the storage layer doesn't
  actually support yet. A future object-storage-backed `DocumentStorage`
  implementation (S3-compatible, GCS, Azure Blob) would remove this
  constraint; not built here, since M10's job is containerizing the
  *existing* system, not redesigning it.
- **Frontend**: stateless except for per-browser-session
  `st.session_state` (already documented in ADR 011) — safe to run
  multiple replicas and to lose on a Pod restart by design.

### Network security

Postgres/Redis are never exposed outside the cluster in Kubernetes
(headless/`ClusterIP` only); in Compose, their host-mapped ports
(`5433`/`6380`) are a **local developer convenience** (so a host-side
tool can connect directly), not how the backend reaches them
(container-to-container traffic always uses the internal service name
and default port — this was already true before this milestone and is
unchanged). The frontend reaches the backend exclusively through the
configured `AEGIS_BACKEND_URL` (a Compose/Kubernetes-internal address by
default) — never a user-editable field anywhere in the UI (ADR 011).

### Cloud assumptions

No cloud provider has been chosen anywhere in this repository (no
Terraform, no provider-specific config found at any point in M0–M9) —
this milestone does not invent one. The containers/manifests are written
to be cloud-portable: no cloud-specific annotation, storage class, or
load-balancer assumption is hardcoded. `postgres-statefulset.yaml`/
`redis-deployment.yaml` are explicitly labeled dev/staging-only, with a
clear pointer to use a managed database/cache service (RDS/Cloud
SQL/Azure Database, ElastiCache/Memorystore/Azure Cache) for a real
production deployment — a decision this project has not made and this
milestone does not make for it. No Terraform/CloudFormation/Pulumi
resource was created, and no actual cloud resource was provisioned.

### Image tagging

No registry hostname is invented anywhere in these files — image
references use a bare name (`aegisai-backend:REPLACE_WITH_TAG`) with an
explicit placeholder, to be prefixed with whatever registry is actually
chosen (e.g. `<registry>/<org>/aegisai-backend:<tag>`) at push time.
Recommended strategy, documented rather than automated via a release
pipeline (none exists yet): tag every CI build with the Git SHA
(`aegisai-backend:$(git rev-parse --short HEAD)`) for full traceability,
and additionally tag `:vX.Y.Z` on an actual tagged release. Never rely on
`:latest` alone for anything beyond fast local iteration (Compose's
`build: .` with no explicit tag is fine for that; the Kubernetes
manifests always require a real tag to be filled in).

### CI/CD

Added a `docker-build` job: builds the backend and frontend images
(`docker build` against the Dockerfiles above) on GitHub's own
ubuntu-latest runner (which has a working Docker daemon, unlike this
development environment — see "What was actually tested") — proving the
Dockerfiles themselves are buildable, without pushing to any registry
(none is configured) and without requiring a live deployment. Added a
`k8s-validate` step reusing `infra/kubernetes/validate_manifests.py` — no
new CI platform/deployment tooling was introduced.

### Observability

No monitoring stack (Prometheus/Grafana/Loki) was added — explicitly out
of scope per the brief ("M11 is the appropriate place"). The application's
existing `structlog` JSON logging is unchanged and still writes to
stdout/stderr inside every container, which is exactly what `docker
compose logs`/`kubectl logs` already capture correctly with zero
additional configuration — nothing needed adding here. No code path logs
secrets/prompts/raw document content; this was already true (Milestones
1–9) and is unchanged.

## Testing

- `docker compose config` — the compose file parses and merges
  correctly (does **not** require the Docker daemon to be running; it is
  pure YAML parsing/merging). Run and confirmed in this environment.
- `infra/kubernetes/validate_manifests.py` — all 15 manifest documents
  parse as valid YAML, carry the required `apiVersion`/`kind`/
  `metadata.name` fields, and every Secret manifest is confirmed to be a
  safe, non-functional template (verified the check has real teeth: it
  was deliberately fed a tampered copy with a real-looking credential
  value and correctly failed, then re-run clean). Run and confirmed in
  this environment.
- What was **not** run, and why: an actual `docker build`/`docker compose
  up`, a real `kubectl apply --dry-run=client` or `kubeconform` against a
  live API server's schema, and any container health/runtime check — see
  this milestone's own end-of-milestone report for the precise
  environment limitation (Docker Desktop's daemon unreachable; `kubectl`
  present but no cluster context configured) and what is honestly
  claimed vs. not.
- Full M0–M9 backend/frontend test suites continue to pass unchanged
  (nothing in `app/`/`frontend/streamlit/` application code was touched).

## Consequences

- **Positive**: the backend image now runs as non-root with a real
  `HEALTHCHECK`, closing two genuine gaps the pre-existing Dockerfile had
  — these are real hardening improvements, not cosmetic.
- **Positive**: documenting the `replicas: 1` constraint explicitly
  (rather than letting someone set `replicas: 3` and discover silently
  inconsistent uploaded-file visibility across Pods later) turns a latent
  bug into a known, intentional limitation.
- **Positive**: the Secret-template validator is a genuinely load-bearing
  safety check (verified against a tampered example), not a box-ticking
  test — it would catch a real accidental-credential-commit in these
  specific files.
- **Negative**: this milestone's Kubernetes manifests have never been
  applied to a real cluster — they are correct by careful construction
  and static validation, not by observed runtime behavior. Treat them as
  a reviewed starting point, not a battle-tested deployment, until
  validated in an environment with a real cluster.
- **Negative**: the backend's `replicas: 1` ceiling (driven by local
  file storage) is a real scaling limitation carried forward from M3,
  now made visible rather than fixed — resolving it is future work
  (object storage), not something M10 was scoped to solve.
- **Negative**: no HPA was added (the brief explicitly discourages one
  without real metrics backing it, and no metrics-server-fed signal
  exists yet) — scaling remains a manual `replicas:` edit for now.

## Related

- [001-modular-monolith.md](001-modular-monolith.md) (the one-deployable-
  unit architecture these manifests deploy as exactly that — one backend
  Deployment, not per-module microservices)
- [011-copilot-ui-architecture.md](011-copilot-ui-architecture.md) (the
  frontend's own `AEGIS_BACKEND_URL`/health-endpoint/statelessness
  decisions this milestone's frontend image and Kubernetes manifests
  build on directly)
