"""HTTP request counts and latency, measured by `CorrelationIdMiddleware`.

Most tests drive the real module-level `app` (its middleware is always installed; recording is
switched on by this package's fixture). The unhandled-exception tests add a throwaway route to a
separate application.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.observability import metrics

from .helpers import exposition, samples, value


def test_a_request_is_counted_with_its_route_and_status(client: TestClient) -> None:
    assert client.get("/health").status_code == 200
    assert client.get("/health").status_code == 200

    assert value("aegis_http_requests_total", method="GET", route="/health", status="200") == 2
    assert value("aegis_http_request_duration_seconds_count", method="GET", route="/health") == 2
    assert value("aegis_http_request_duration_seconds_sum", route="/health") >= 0


def test_the_route_is_the_full_template_not_the_raw_path(anon_client: TestClient) -> None:
    # Unauthenticated, so the request is refused (401) before any route code or database use,
    # but only after the route matched: exactly what the template label needs.
    ids = [str(uuid.uuid4()) for _ in range(2)] + [str(uuid.uuid4()).upper()]
    for identifier in ids:
        anon_client.get(f"/api/v1/documents/{identifier}/chunks")

    routes = {lab["route"] for n, lab, _ in samples() if n == "aegis_http_requests_total"}

    # The router prefix is kept (FastAPI reports an included router's path relative to it).
    assert routes == {"/api/v1/documents/{document_id}/chunks"}
    text = exposition()
    for identifier in ids:
        assert identifier.lower() not in text.lower()


def test_many_distinct_ids_create_one_series_not_many(anon_client: TestClient) -> None:
    for _ in range(25):
        anon_client.get(f"/api/v1/documents/{uuid.uuid4()}/chunks")

    series = {
        tuple(sorted(lab.items()))
        for n, lab, _ in samples()
        if n == "aegis_http_requests_total" and lab["route"].startswith("/api/v1/documents")
    }

    assert len(series) == 1  # one route template and one status code, whatever the ids


def test_unmatched_paths_share_one_fixed_label(client: TestClient) -> None:
    for path in ("/nope", f"/a/{uuid.uuid4()}", "/../etc/passwd", "/x?email=alice@example.test"):
        assert client.get(path).status_code == 404

    unmatched = value("aegis_http_requests_total", route="unmatched", status="404")
    assert unmatched == 4
    text = exposition()
    assert "nope" not in text and "passwd" not in text and "alice" not in text


def test_validation_errors_are_counted_under_their_route(client: TestClient) -> None:
    response = client.get("/api/v1/documents/not-a-valid-id/chunks")

    assert response.status_code == 422  # rejected before any route code runs (no database)
    assert value("aegis_http_requests_total", route="/api/v1/documents/{document_id}/chunks") == 1
    assert "not-a-valid-id" not in exposition()


def test_unauthenticated_requests_are_counted_by_status(anon_client: TestClient) -> None:
    anon_client.get("/api/v1/auth/me")

    assert value("aegis_http_requests_total", route="/api/v1/auth/me", status="401") == 1


def test_methods_are_normalised(client: TestClient) -> None:
    client.request("OPTIONS", "/health")
    client.request("FOOBAR", "/health")

    methods = {lab["method"] for n, lab, _ in samples() if n == "aegis_http_requests_total"}

    assert methods <= {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "OTHER"}
    assert "FOOBAR" not in exposition()


def test_the_request_id_and_the_caller_never_appear(client: TestClient) -> None:
    client.get("/health", headers={"X-Request-ID": "req-abcdef-123456"})

    text = exposition()

    assert "req-abcdef-123456" not in text and "request_id" not in text


def test_the_help_text_says_latency_is_time_to_response_start() -> None:
    metrics.record_http_request("GET", "/health", 200, 0.01)

    text = exposition()

    assert "NOT the total stream duration" in text


# -- unhandled exceptions ----------------------------------------------------------------------


def _app_with_failing_route() -> TestClient | object:
    application = create_app(Settings(_env_file=None, debug=True, environment="local"))  # type: ignore[call-arg]
    metrics.configure(enabled=True)  # create_app applied the (disabled) default; re-enable

    async def boom() -> None:
        raise RuntimeError("secret internal detail that must never become a label")

    application.add_api_route("/__boom/{item_id}", boom)
    return application


def test_an_unhandled_exception_is_counted_as_a_500_and_the_response_is_unchanged() -> None:
    application = _app_with_failing_route()
    client = TestClient(application, raise_server_exceptions=False)  # type: ignore[arg-type]

    response = client.get(f"/__boom/{uuid.uuid4()}")

    # The existing handler still produces the same generic 500 envelope.
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "secret internal detail" not in response.text
    assert value("aegis_http_requests_total", route="/__boom/{item_id}", status="500") == 1
    assert value("aegis_http_request_duration_seconds_count", route="/__boom/{item_id}") == 1
    assert "secret internal detail" not in exposition()


def test_the_exception_still_propagates_through_the_middleware() -> None:
    application = _app_with_failing_route()
    client = TestClient(application)  # type: ignore[arg-type]  # re-raises server errors

    with pytest.raises(RuntimeError, match="secret internal detail"):
        client.get(f"/__boom/{uuid.uuid4()}")

    assert value("aegis_http_requests_total", route="/__boom/{item_id}", status="500") == 1


def _explode(*_args: object, **_kwargs: object) -> None:
    raise RuntimeError("metrics machinery down")


@pytest.mark.parametrize("failing", ["record_http_request", "_route_template"])
def test_a_recording_failure_does_not_change_a_successful_response(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    from app.core import middleware

    target = middleware.metrics if failing == "record_http_request" else middleware
    monkeypatch.setattr(target, failing, _explode)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"]


@pytest.mark.parametrize("failing", ["record_http_request", "_route_template"])
def test_a_recording_failure_does_not_replace_the_original_exception(
    monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    from app.core import middleware

    application = _app_with_failing_route()
    target = middleware.metrics if failing == "record_http_request" else middleware
    monkeypatch.setattr(target, failing, _explode)

    # Re-raised server errors: the application's own exception, not the metrics failure.
    with pytest.raises(RuntimeError, match="secret internal detail"):
        TestClient(application).get(f"/__boom/{uuid.uuid4()}")  # type: ignore[arg-type]

    # And over HTTP the client still gets the generic 500 envelope.
    response = TestClient(application, raise_server_exceptions=False).get("/__boom/1")  # type: ignore[arg-type]
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
