"""`GET /metrics`: Prometheus exposition, opt-in and bearer-token protected.

Mounted by `create_app` ONLY when `METRICS_ENABLED=true`, at the application root like `/health`
and deliberately NOT on the OIDC-protected API router: scrapers do not do OIDC. It has its own
guard, a static bearer token (`METRICS_TOKEN`) compared in constant time. When metrics are disabled
the route does not exist (404). The token is never logged or returned.
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from app.core.exceptions import UnauthorizedError
from app.observability import metrics

router = APIRouter(tags=["metrics"])


def require_metrics_token(request: Request) -> None:
    # The settings of THIS application (stored by `create_app`), not the process-wide cache: an app
    # built with its own settings must be guarded by its own token. No settings means no token,
    # which fails closed.
    settings = getattr(request.app.state, "metrics_settings", None)
    token = getattr(settings, "metrics_token", None)
    expected = token.get_secret_value() if token else ""
    scheme, _, supplied = request.headers.get("authorization", "").partition(" ")
    # Fails closed: no configured token means nobody is accepted. The comparison runs on bytes of
    # equal treatment either way, so response time does not reveal how much of a guess matched.
    token_ok = hmac.compare_digest(supplied.strip().encode("utf-8"), expected.encode("utf-8"))
    if not (expected and scheme.lower() == "bearer" and token_ok):
        raise UnauthorizedError()  # generic 401 with WWW-Authenticate; says nothing about why


@router.get("/metrics", include_in_schema=False, dependencies=[Depends(require_metrics_token)])
async def scrape() -> Response:
    return Response(content=metrics.render(), media_type=metrics.CONTENT_TYPE)
