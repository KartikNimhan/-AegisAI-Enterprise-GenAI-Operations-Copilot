"""FastAPI application entrypoint.

Run with: `uvicorn app.main:app` (from the `backend/` directory).
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.api.v1 import health
from app.api.v1.research_agent import well_known_router
from app.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import CorrelationIdMiddleware

settings = get_settings()
configure_logging(settings)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )

    application.add_middleware(CorrelationIdMiddleware)
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
