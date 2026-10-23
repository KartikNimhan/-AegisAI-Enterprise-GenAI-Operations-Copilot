"""FastAPI application entrypoint.

Run with: `uvicorn app.main:app` (from the `backend/` directory).
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router, public_api_router
from app.api.v1 import health
from app.api.v1 import metrics as metrics_endpoint
from app.api.v1.research_agent import well_known_router
from app.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import (
    MULTIPART_OVERHEAD_BYTES,
    BodySizeLimitMiddleware,
    CorrelationIdMiddleware,
)
from app.embeddings.providers.local import get_local_embedding_provider
from app.observability import metrics

settings = get_settings()
configure_logging(settings)
logger = structlog.get_logger(__name__)


async def _warm_up_embedding_model() -> None:
    """Fire-and-forget startup task: loads the embedding model in the
    background so the first real research/chat request doesn't pay the
    (potentially 60s+) first-load cost itself and risk tripping the A2A
    client's task timeout. Never blocks startup/the healthcheck, and a
    failure here doesn't crash the app — embed_texts still lazily retries
    loading the model on first real use."""
    try:
        await get_local_embedding_provider().warm_up()
        logger.info("embedding_model_warmed_up")
    except Exception:
        logger.warning("embedding_model_warm_up_failed", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # The event loop keeps only a weak reference to a task, so a fire-and-forget task can be
    # garbage-collected before it finishes. Keep it on the app, and cancel it on shutdown if the
    # model is still loading, instead of leaving a pending task behind.
    warm_up = asyncio.create_task(_warm_up_embedding_model())
    app.state.embedding_warm_up = warm_up
    try:
        yield
    finally:
        if not warm_up.done():
            warm_up.cancel()


def create_app(app_settings: Settings | None = None) -> FastAPI:
    settings = app_settings or get_settings()
    # Outside local development the API refuses to start without authentication
    # configured (raises, naming the missing variables). Settings loading itself
    # does not require it, so Alembic and scripts can still run.
    settings.validate_for_serving()
    if not settings.auth_configured:
        # Local development only (validate_for_serving passed): say so ONCE here
        # rather than on every request.
        logger.error(
            "auth.not_configured",
            detail="AUTH_ISSUER/AUTH_AUDIENCE/AUTH_JWKS_URL are unset: every protected "
            "route will answer 503 until they are set",
        )
    # Interactive docs and the OpenAPI schema describe the whole API surface;
    # they are served only in local development (Milestone 12).
    docs_enabled = settings.environment == "local"
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )

    # Innermost of the three, so a 413 still carries the request id and is counted in metrics.
    application.add_middleware(
        BodySizeLimitMiddleware,
        max_body_bytes=settings.max_request_body_bytes,
        # The document upload is the only route with a bigger body: the file limit plus framing.
        upload_limits={
            f"{settings.api_v1_prefix}/documents": settings.document_max_upload_size_bytes
            + MULTIPART_OVERHEAD_BYTES
        },
    )
    application.add_middleware(CorrelationIdMiddleware)
    # Required for any browser-based frontend (the React app, served from
    # its own origin/port) to call this API at all — without it the
    # browser blocks the response before JS ever sees it, regardless of
    # whether the server-side request itself succeeded. Was previously
    # configured (settings.cors_origins) but never actually wired in.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(application)

    # Unversioned: liveness/readiness probes, and the A2A well-known Agent
    # Card path (a fixed protocol convention, not an AegisAI API path),
    # are conventionally not versioned.
    # Metrics are opt-in: nothing is recorded, and /metrics does not exist (404), unless enabled.
    # The endpoint sits outside the OIDC-protected API and has its own bearer-token guard.
    metrics.configure(enabled=settings.metrics_enabled)
    application.state.metrics_settings = settings
    if settings.metrics_enabled:
        if not settings.metrics_token_configured:
            logger.error(
                "metrics.token_not_configured",
                detail="METRICS_ENABLED is true but METRICS_TOKEN is unset: /metrics answers "
                "401 to every request until a token is set (local development only; other "
                "environments refuse to start)",
            )
        application.include_router(metrics_endpoint.router)
    application.include_router(health.router)
    application.include_router(well_known_router)
    # Versioned routes: the three public Agent Cards, then everything else
    # behind the authentication gate (see app.api.router docstring).
    application.include_router(public_api_router, prefix=settings.api_v1_prefix)
    application.include_router(api_router, prefix=settings.api_v1_prefix)

    return application


app = create_app()
