# Backend (FastAPI) production image.
#
# Two stages: `builder` resolves dependencies with uv (the project's
# existing, established dependency mechanism — not pip/poetry) into a
# virtualenv; `runtime` is a clean slim image that copies only that
# virtualenv and the application code — no uv, no pip cache, no build
# tools ship in the final image. See
# docs/architecture/decisions/012-deployment-architecture.md, "Backend
# image," for the full reasoning.

# ---- builder -----------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy

RUN pip install --no-cache-dir uv==0.11.2

WORKDIR /srv

# Dependencies before application code so this layer is cached across code
# changes — only pyproject.toml/uv.lock changes bust it. --frozen makes
# the install deterministic (fails rather than silently re-resolving if
# uv.lock is out of date); --no-dev excludes dev-only tooling (pytest,
# ruff, pyright) from the resolved set entirely.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# ---- runtime -------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/srv/.venv/bin:${PATH}" \
    HOST=0.0.0.0 \
    PORT=8000

# A dedicated, unprivileged user — the application never runs as root.
RUN groupadd --system app && useradd --system --gid app --no-create-home app

WORKDIR /srv

COPY --from=builder /srv/.venv /srv/.venv
COPY backend/app ./app
# alembic/alembic.ini are included so the *same* image can also run
# `alembic upgrade head` as a one-off command (docker-compose.yml's
# `migrate` service, infra/kubernetes/migration-job.yaml) — migrations
# are never run implicitly by the API server itself on startup; see
# docs/architecture/decisions/012-deployment-architecture.md, "Migration
# strategy."
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini
COPY backend/scripts/docker_healthcheck.py ./docker_healthcheck.py

# The app writes nothing under /srv at runtime (DOCUMENT_STORAGE_DIR is a
# separate, explicitly volumed path — see docker-compose.yml) — chown is
# only so `app` can read everything it needs and alembic can write its
# own transient state if ever required.
RUN chown -R app:app /srv

USER app

EXPOSE 8000

# A pure-Python check (no curl/wget installed, keeping the image minimal)
# against the real /health liveness endpoint — see docker_healthcheck.py's
# own docstring for why /health, not /health/ready.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "docker_healthcheck.py"]

# Shell form so $HOST/$PORT are expanded and are configurable without a
# rebuild; `exec` replaces the shell with uvicorn so it becomes PID 1 and
# receives SIGTERM directly from Docker/Kubernetes for a graceful
# shutdown — no separate init/supervisor process is introduced.
CMD exec uvicorn app.main:app --host "$HOST" --port "$PORT"
