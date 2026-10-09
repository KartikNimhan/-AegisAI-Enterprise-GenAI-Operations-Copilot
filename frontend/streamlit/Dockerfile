# Frontend (Streamlit) production image.
#
# Built with the same two-stage pattern as the root backend Dockerfile —
# uv resolves the `frontend` dependency group in a `builder` stage; the
# `runtime` stage ships only that virtualenv and the app's own files, no
# uv/pip/build tools. Build context is the repository root (not this
# directory) since `pyproject.toml`/`uv.lock` (the dependency source of
# truth) live there — see docker-compose.yml's `frontend.build.context`.
#
# This does NOT migrate the UI to React/Next.js/etc. — it is still the
# same Streamlit app from frontend/streamlit/, only containerized. See
# docs/architecture/decisions/012-deployment-architecture.md, "Frontend
# image."

# ---- builder -----------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy

RUN pip install --no-cache-dir uv==0.11.2

WORKDIR /srv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev --group frontend

# ---- runtime -------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/srv/.venv/bin:${PATH}" \
    PORT=8501 \
    # Configurable at the container level — services/api/client.py reads
    # these two directly from the environment (see that module's own
    # docstring); never a URL a user can type into the UI itself.
    AEGIS_BACKEND_URL=http://backend:8000 \
    AEGIS_BACKEND_TIMEOUT_SECONDS=30.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

RUN groupadd --system app && useradd --system --gid app --no-create-home app

WORKDIR /srv

COPY --from=builder /srv/.venv /srv/.venv
COPY frontend/streamlit/app.py ./app.py
COPY frontend/streamlit/healthcheck.py ./healthcheck.py
COPY frontend/streamlit/pages ./pages
COPY frontend/streamlit/components ./components
COPY frontend/streamlit/services ./services

# Streamlit writes its own cache/config under a user-writable home
# directory even with STREAMLIT_SERVER_HEADLESS=true — give the
# unprivileged user one rather than leaving $HOME unset (which would
# resolve to "/", unwritable by a non-root user).
RUN mkdir -p /home/app/.streamlit && chown -R app:app /srv /home/app
ENV HOME=/home/app

USER app

EXPOSE 8501

# See healthcheck.py's own docstring: hits Streamlit's real, built-in
# /_stcore/health endpoint, no curl/wget installed.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "healthcheck.py"]

CMD exec streamlit run app.py --server.address=0.0.0.0 --server.port="$PORT"
