"""Request correlation ID and access-logging middleware."""

import re
import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.observability import metrics

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
        try:
            response = await call_next(request)
        except Exception:
            # An unhandled error is turned into a 500 by an outer layer, so it passes through
            # here as an exception. Count it as a 500 and re-raise unchanged.
            _record(request, 500, time.perf_counter() - start)
            raise
        duration_ms = (time.perf_counter() - start) * 1000
        # Time until the response STARTED; for streaming responses not the total stream time.
        _record(request, response.status_code, duration_ms / 1000)

        response.headers[REQUEST_ID_HEADER] = request_id
        logger.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
        )
        return response


_STATIC_PREFIX = re.compile(r"(/[A-Za-z0-9_.-]+)*")
_MAX_PREFIX_CHARS = 64


def _route_template(request: Request) -> str | None:
    """The matched route's path template (for example `/api/v1/documents/{document_id}`), never
    the raw path, so ids cannot become metric labels. `None` when no route matched.

    FastAPI reports an included router's route path RELATIVE to the router (`/documents/{id}`),
    so the router's static prefix (`/api/v1`) is taken from the front of the request path: the
    route matched, hence those leading segments equal the prefix. If the route uses a multi-segment
    converter, or the prefix does not look like a plain static prefix, the relative template alone
    is used. Neither case can put a request-supplied value into the label."""
    scope = request.scope
    template = getattr(scope.get("route"), "path", None)
    if not isinstance(template, str):
        return None
    if ":path}" in template:
        return template
    relative = [segment for segment in template.split("/") if segment]
    actual = [segment for segment in str(scope.get("path", "")).split("/") if segment]
    if len(actual) < len(relative):
        return template
    prefix = "".join(f"/{segment}" for segment in actual[: len(actual) - len(relative)])
    if len(prefix) > _MAX_PREFIX_CHARS or not _STATIC_PREFIX.fullmatch(prefix):
        return template
    return prefix + (template if template.startswith("/") else f"/{template}")


def _record(request: Request, status_code: int, seconds: float) -> None:
    """Counts the request, except scrapes of the metrics endpoint itself."""
    try:
        template = _route_template(request)
        if template == "/metrics" or request.url.path == "/metrics":
            return
        metrics.record_http_request(request.method, template, status_code, seconds)
    except Exception:  # noqa: BLE001 - observability must never break a request
        logger.debug("metrics_recording_failed", exc_info=True)
