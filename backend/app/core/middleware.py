"""Request correlation ID and access-logging middleware."""

import re
import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"

# A client-supplied id is only trusted if it is short and made of safe
# characters; otherwise a fresh one is generated (it ends up in every log line
# and in the response header).
# (`fullmatch`, not `match` with `$`: `$` also matches before a trailing newline.)
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Binds a request/correlation ID to each request and logs its outcome."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        supplied = request.headers.get(REQUEST_ID_HEADER)
        request_id = (
            supplied if supplied and _SAFE_REQUEST_ID.fullmatch(supplied) else str(uuid.uuid4())
        )
        request.state.request_id = request_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        response.headers[REQUEST_ID_HEADER] = request_id
        logger.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
        )
        return response
