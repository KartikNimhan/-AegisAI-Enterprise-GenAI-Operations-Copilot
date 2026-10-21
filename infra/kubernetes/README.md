# AegisAI — Kubernetes manifests

A deployment **foundation**, not a managed Helm chart/operator — plain
`kubectl apply`-able YAML, matching the project's current scale (a
modular monolith backend + one React frontend; see
[ADR 001](../../docs/architecture/decisions/001-modular-monolith.md) and
[ADR 012](../../docs/architecture/decisions/012-deployment-architecture.md)).
No Helm/ArgoCD/Flux/service mesh is introduced.

**Browser access:** the React app's API calls happen in the browser, so the
frontend image's nginx serves the app *and* proxies `/api/` to the
cluster-internal `aegisai-backend` Service (`BACKEND_UPSTREAM` in
`frontend-configmap.yaml`). The browser only ever talks to the frontend's
own origin; the backend stays ClusterIP-only and needs no separate external
URL or CORS configuration. (The previous "known gap" is closed by this; it has
not been exercised in a real cluster — see "What was actually validated".)
The frontend image is `nginx-unprivileged` (user 101, container port **8080**; the
Service port stays 80), so the Deployment keeps `runAsNonRoot: true` and drops all
capabilities. The proxy also forwards the exact path `/health` for the UI's
connection indicator.

**Authentication is required before anything works end to end.** The backend
refuses to start until `AUTH_ISSUER`, `AUTH_AUDIENCE` and `AUTH_JWKS_URL` in
`backend-configmap.yaml` are set to your identity provider's values, and the
React UI needs `OIDC_AUTHORITY` (empty by default) in `frontend-configmap.yaml`, otherwise a browser cannot obtain a
token. API clients that already hold a token work. Link each person's account with
`scripts/provision_identity.py` (see the root README, "Authentication setup"), run against
the cluster database, for example through `kubectl port-forward`.

## What's here

| File | Purpose |
|---|---|
| `backend-configmap.yaml` | Non-secret backend config |
| `backend-secret.example.yaml` | **Template only** — see its header |
| `backend-pvc.yaml` | Uploaded-document storage (ReadWriteOnce) |
| `backend-deployment.yaml` | The FastAPI backend (`replicas: 1` — see its own comment on why) |
| `backend-service.yaml` | ClusterIP, internal only |
| `frontend-configmap.yaml` | Non-secret frontend config |
| `frontend-deployment.yaml` | The React Copilot UI (nginx-served static build) |
| `frontend-service.yaml` | ClusterIP by default |
| `migration-job.yaml` | Runs `alembic upgrade head` once, as a separate step |
| `postgres-statefulset.yaml` + `postgres-service.yaml` + `postgres-secret.example.yaml` | **Dev/staging only** self-hosted Postgres+pgvector |
| `redis-deployment.yaml` + `redis-service.yaml` | **Dev/staging only** self-hosted Redis (no persistence — see its own comment) |
| `ingress.example.yaml` | **Template only** — optional external access to the frontend |
| `validate_manifests.py` | Client-side structural validation (no cluster/kubectl needed) |

## Deployment order

1. Create the real Secrets (never apply the `.example.yaml` files
   directly):
   ```bash
   kubectl create secret generic aegisai-backend-secret \
     --from-literal=DATABASE_URL='postgresql+asyncpg://aegis:<password>@aegisai-postgres:5432/aegis' \
     --from-literal=GROQ_API_KEY='<your-groq-api-key>'
   # Only if self-hosting Postgres via postgres-statefulset.yaml:
   kubectl create secret generic aegisai-postgres-secret \
     --from-literal=POSTGRES_PASSWORD='<password>'
   ```
2. If self-hosting Postgres/Redis: `kubectl apply -f postgres-statefulset.yaml -f postgres-service.yaml -f redis-deployment.yaml -f redis-service.yaml`.
   If using managed services instead, point `DATABASE_URL`/`REDIS_URL` at
   them and skip this step.
3. `kubectl apply -f backend-configmap.yaml -f backend-pvc.yaml`
4. Run migrations once: `kubectl apply -f migration-job.yaml`, wait for
   it to complete (`kubectl wait --for=condition=complete job/aegisai-migrate`),
   then `kubectl delete job aegisai-migrate`.
5. `kubectl apply -f backend-deployment.yaml -f backend-service.yaml`
6. `kubectl apply -f frontend-configmap.yaml -f frontend-deployment.yaml -f frontend-service.yaml`
7. Optional external access: `kubectl port-forward svc/aegisai-frontend 8080:80`
   for local access, or edit and apply `ingress.example.yaml` if you have
   an ingress controller. No backend URL needs to be configured:
   `API_BASE_URL` is empty (same origin) and `/api/` is proxied by the
   frontend.

Update `image:` in `backend-deployment.yaml`/`frontend-deployment.yaml`/
`migration-job.yaml` to your own registry/tag first — see ADR 012,
"Image tagging," for the strategy. There is no registry hostname assumed
anywhere in these manifests.

## What was actually validated

`validate_manifests.py` (YAML syntax + required fields + a check that
every Secret manifest is an obvious, non-functional template) — run via
`make k8s-validate`. **Not** validated: a real `kubectl apply --dry-run`
or `kubeconform`/`kubeval` run against a live API server's schema, and
no manifest here was ever actually applied to a running cluster — see
the Milestone 10 report for exactly what environment limitation caused
that, and re-run those checks in an environment with a reachable
cluster/kubectl context before trusting this foundation in anger.
