"""Request correlation ID and access-logging middleware."""

import re
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping

import structlog
from starlette.datastructures import MutableHeaders
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.observability import metrics

logger = structlog.get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"

# Every API response: never let a browser guess a different content type for a JSON body, and
# never store one in a browser or proxy cache (responses carry conversations, documents and
# memories). A route that chooses its own caching keeps it.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
}


def apply_security_headers(headers: MutableHeaders) -> None:
    for name, value in SECURITY_HEADERS.items():
        if name not in headers:
            headers[name] = value


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
        apply_security_headers(response.headers)
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


class _BodyTooLargeError(Exception):
    pass


# Room for multipart framing (boundaries, part headers) on top of the uploaded file itself.
MULTIPART_OVERHEAD_BYTES = 1024 * 1024


class BodySizeLimitMiddleware:
    """Refuses a request body larger than its limit with 413, before the application reads it.

    Pydantic length limits only apply AFTER a whole body is read into memory, and a multipart
    upload is spooled to disk before the route sees it, so neither bounds the read itself. Every
    request gets `max_body_bytes`, except a POST to one of `upload_limits`' paths, which gets that
    path's own (larger) limit. The client's Content-Type is deliberately NOT consulted: labelling a
    request `multipart/form-data` used to skip the check entirely. A declared Content-Length is
    checked up front; for a body with no (or a false) length the bytes are counted as they arrive.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_body_bytes: int,
        upload_limits: Mapping[str, int] | None = None,
    ) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.upload_limits = dict(upload_limits or {})

    def limit_for(self, scope: Scope) -> int:
        if scope.get("method") == "POST" and scope.get("path") in self.upload_limits:
            return self.upload_limits[scope["path"]]
        return self.max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.limit_for(scope)
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                too_large = int(declared) > limit
            except ValueError:
                too_large = False  # the server layer rejects a malformed length itself
            if too_large:
                await self._reject(scope, receive, send)
                return

        received = 0
        started = False

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyTooLargeError
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _BodyTooLargeError:
            if started:
                raise  # cannot change a response already begun; the connection is cut
            await self._reject(scope, receive, send)

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        request_id = scope.get("state", {}).get("request_id")
        response = JSONResponse(
            status_code=413,
            content={
                "error": {
                    "code": "payload_too_large",
                    "message": "The request body is too large",
                    "request_id": request_id,
                }
            },
        )
        await response(scope, receive, send)
