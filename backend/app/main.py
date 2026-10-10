"""FastAPI application entrypoint.

Run with: `uvicorn app.main:app` (from the `backend/` directory).
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.api.v1 import health
from app.api.v1.research_agent import well_known_router
from app.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import CorrelationIdMiddleware
from app.embeddings.providers.local import get_local_embedding_provider

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
    asyncio.create_task(_warm_up_embedding_model())
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
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
    application.include_router(health.router)
    application.include_router(well_known_router)
    # Versioned business routes (empty for now; see app.api.router docstring).
    application.include_router(api_router, prefix=settings.api_v1_prefix)

    return application


app = create_app()
