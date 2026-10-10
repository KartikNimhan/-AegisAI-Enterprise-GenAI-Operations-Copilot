# AegisAI — Kubernetes manifests

A deployment **foundation**, not a managed Helm chart/operator — plain
`kubectl apply`-able YAML, matching the project's current scale (a
modular monolith backend + one React frontend; see
[ADR 001](../../docs/architecture/decisions/001-modular-monolith.md) and
[ADR 012](../../docs/architecture/decisions/012-deployment-architecture.md)).
No Helm/ArgoCD/Flux/service mesh is introduced.

**Known gap:** the frontend manifests below target the React app
(`frontend/web/`, port 80), but the backend remains ClusterIP-only (see
`backend-service.yaml`) — fine for the original Streamlit app, which
called the backend server-side, but the React app's API calls happen in
the browser and need a backend URL reachable from outside the cluster.
That's a network-security decision this project hasn't made yet; see
`frontend-configmap.yaml` and `ingress.example.yaml`'s own comments.
Applying these manifests as-is will deploy a frontend that *starts*
successfully but cannot actually reach the backend from a real browser.

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
   an ingress controller. Either way, also set `API_BASE_URL` in
   `frontend-configmap.yaml` to a URL your browser can actually reach —
   see that file's own comment and the "Known gap" note above.

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
