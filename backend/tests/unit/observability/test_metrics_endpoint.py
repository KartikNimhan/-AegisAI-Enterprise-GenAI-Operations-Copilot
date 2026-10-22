"""GET /metrics: absent when disabled; bearer-token protected when enabled; separate from OIDC.

Each test builds its own application with `create_app(settings)`, so the real wiring decision
("mount the route only when enabled") is what is tested.
"""

from __future__ import annotations

import hmac
from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from app.api.v1 import metrics as metrics_endpoint
from app.config import Settings
from app.main import create_app
from app.observability import metrics

from .helpers import samples

TOKEN = "scrape-token-for-tests-only-0123456789"  # clearly fake


def make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, debug=True, environment="local", **overrides)  # type: ignore[call-arg,arg-type]


def build(**overrides: object) -> tuple[FastAPI, Settings]:
    settings = make_settings(**overrides)
    application = create_app(settings)
    return application, settings


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# -- disabled ----------------------------------------------------------------------------------


def test_the_endpoint_does_not_exist_when_metrics_are_disabled() -> None:
    application, _ = build()  # metrics_enabled defaults to False
    client = TestClient(application)

    for path in ("/metrics", "/api/v1/metrics"):
        assert client.get(path, headers=bearer(TOKEN)).status_code == 404
    assert metrics.is_enabled() is False


def test_even_a_configured_token_does_not_mount_the_route_while_disabled() -> None:
    application, _ = build(metrics_enabled=False, metrics_token=TOKEN)

    assert TestClient(application).get("/metrics", headers=bearer(TOKEN)).status_code == 404


# -- enabled: tokens ----------------------------------------------------------------------------


@pytest.fixture
def enabled() -> tuple[TestClient, Settings]:
    application, settings = build(metrics_enabled=True, metrics_token=TOKEN)
    return TestClient(application), settings


def test_a_missing_token_is_refused(enabled: tuple[TestClient, Settings]) -> None:
    client, _ = enabled

    response = client.get("/metrics")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize(
    "header",
    [
        "Bearer wrong-token-value-0123456789012345",
        "Bearer ",
        "Bearer",
        f"Basic {TOKEN}",
        f"Token {TOKEN}",
        TOKEN,  # no scheme
        f"Bearer {TOKEN} extra",
        f"Bearer {TOKEN[:-1]}",  # one character short
        f"Bearer {TOKEN}x",  # one character long
    ],
)
def test_a_wrong_or_malformed_token_is_refused(
    enabled: tuple[TestClient, Settings], header: str
) -> None:
    client, _ = enabled

    response = client.get("/metrics", headers={"Authorization": header})

    assert response.status_code == 401
    assert TOKEN not in response.text  # the real token is never echoed back


def test_the_correct_token_returns_prometheus_text(enabled: tuple[TestClient, Settings]) -> None:
    client, _ = enabled
    metrics.record_http_request("GET", "/health", 200, 0.01)

    response = client.get("/metrics", headers=bearer(TOKEN))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "version=" in response.headers["content-type"]
    assert "aegis_http_requests_total" in response.text
    assert TOKEN not in response.text


def test_the_scheme_is_case_insensitive_like_http_auth(
    enabled: tuple[TestClient, Settings],
) -> None:
    client, _ = enabled

    assert client.get("/metrics", headers={"Authorization": f"bearer {TOKEN}"}).status_code == 200


def test_the_token_is_never_written_to_the_logs(enabled: tuple[TestClient, Settings]) -> None:
    client, _ = enabled

    with capture_logs() as logs:
        client.get("/metrics", headers=bearer(TOKEN))
        client.get("/metrics", headers=bearer("wrong-wrong-wrong-wrong-wrong"))
        client.get("/metrics")

    assert TOKEN not in repr(logs)


def test_every_token_check_goes_through_a_constant_time_comparison(
    enabled: tuple[TestClient, Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = enabled
    calls: list[tuple[bytes, bytes]] = []
    real = hmac.compare_digest

    def spy(a: bytes, b: bytes) -> bool:
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(metrics_endpoint.hmac, "compare_digest", spy)

    assert client.get("/metrics", headers=bearer(TOKEN)).status_code == 200
    assert client.get("/metrics", headers=bearer("x" * 40)).status_code == 401
    assert client.get("/metrics").status_code == 401
    assert len(calls) == 3  # a wrong, a right and a missing credential are all compared


def test_each_application_is_guarded_by_its_own_token() -> None:
    first, _ = build(metrics_enabled=True, metrics_token=TOKEN)
    second, _ = build(metrics_enabled=True, metrics_token="second-app-token-0123456789")

    assert TestClient(first).get("/metrics", headers=bearer(TOKEN)).status_code == 200
    assert TestClient(second).get("/metrics", headers=bearer(TOKEN)).status_code == 401
    assert (
        TestClient(second)
        .get("/metrics", headers=bearer("second-app-token-0123456789"))
        .status_code
        == 200
    )


def test_an_application_without_settings_fails_closed() -> None:
    application, _ = build(metrics_enabled=True, metrics_token=TOKEN)
    del application.state.metrics_settings

    assert TestClient(application).get("/metrics", headers=bearer(TOKEN)).status_code == 401


@pytest.mark.parametrize("header", ["Bearer", "Bearer ", "Basic " + TOKEN, TOKEN, "bearer", ""])
def test_malformed_authorization_headers_are_rejected(
    enabled: tuple[TestClient, Settings], header: str
) -> None:
    client, _ = enabled

    response = client.get("/metrics", headers={"Authorization": header})

    assert response.status_code == 401
    assert response.headers.get("www-authenticate")


# -- enabled without a token (local development only) ----------------------------------------


def test_enabled_without_a_token_answers_401_to_everyone() -> None:
    application, settings = build(metrics_enabled=True)  # local: allowed to start, fails closed
    client = TestClient(application)
    assert settings.metrics_token_configured is False

    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers=bearer("")).status_code == 401
    assert client.get("/metrics", headers=bearer("anything-at-all-0123456789")).status_code == 401


# -- separate from OIDC ------------------------------------------------------------------------


def test_the_endpoint_sits_outside_the_oidc_protected_api(
    enabled: tuple[TestClient, Settings],
) -> None:
    client, _ = enabled

    api = client.get("/api/v1/auth/me")  # real authentication: no identity provider here
    scrape = client.get("/metrics", headers=bearer(TOKEN))

    assert api.status_code in (401, 503)  # the API still needs OIDC
    assert scrape.status_code == 200  # the scrape needs only the metrics token
    assert client.get("/api/v1/metrics", headers=bearer(TOKEN)).status_code in (401, 404, 503)


def test_the_route_is_not_part_of_the_published_api_schema(
    enabled: tuple[TestClient, Settings],
) -> None:
    client, _ = enabled

    schema = client.get("/openapi.json").json()

    assert "/metrics" not in schema["paths"]


def test_scrapes_are_not_counted_in_the_request_metrics(
    enabled: tuple[TestClient, Settings],
) -> None:
    client, _ = enabled

    for _ in range(3):
        client.get("/metrics", headers=bearer(TOKEN))
    client.get("/metrics")  # a refused scrape is not counted either

    assert not [s for s in samples() if s[1].get("route") == "/metrics"]


def test_creating_an_app_follows_the_setting_in_both_directions() -> None:
    build(metrics_enabled=True, metrics_token=TOKEN)
    assert metrics.is_enabled() is True

    build()
    assert metrics.is_enabled() is False


def test_helpers_used_here_exist() -> None:
    assert isinstance(build, Callable)
