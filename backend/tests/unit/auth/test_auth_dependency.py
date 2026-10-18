"""The authentication gate end to end through the real FastAPI app
(`GET /api/v1/auth/me` is the probe route): status codes, generic bodies, the
principal being built from the database, fail-closed behavior, and that the
token is never logged. Key set and identity tables are in-memory fakes."""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

import app.core.security as security_module
from app.auth.exceptions import AuthKeysUnavailableError
from app.auth.principal import Principal
from app.auth.tokens import TokenVerifier
from app.config import Settings, get_settings
from app.core.exceptions import ForbiddenError
from app.core.security import get_token_verifier, require_admin
from app.domain.enums.user_role import UserRole
from app.main import app

from ...auth_fixtures import (
    AUDIENCE,
    ISSUER,
    FakeIdentityRepository,
    SigningKey,
    generate_signing_key,
    mint_token,
)

ME = "/api/v1/auth/me"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _error(response: Any) -> dict[str, Any]:
    return response.json()["error"]


def test_missing_credentials_is_401_with_a_bearer_challenge(anon_client: TestClient) -> None:
    response = anon_client.get(ME)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert _error(response)["code"] == "unauthorized"
    assert _error(response)["message"] == "Authentication required"
    assert _error(response)["request_id"]


def test_a_non_bearer_scheme_is_401(anon_client: TestClient) -> None:
    response = anon_client.get(ME, headers={"Authorization": "Basic dXNlcjpwYXNz"})

    assert response.status_code == 401


def test_a_garbage_token_is_401_and_is_not_echoed(anon_client: TestClient) -> None:
    response = anon_client.get(ME, headers=_bearer("garbage-token-value"))

    assert response.status_code == 401
    assert "garbage-token-value" not in response.text


def test_every_kind_of_token_problem_gets_the_same_generic_response(
    anon_client: TestClient, signing_key: SigningKey
) -> None:
    now = int(time.time())
    other_key = generate_signing_key()  # same kid, different key material -> bad signature
    tokens = {
        "expired": mint_token(signing_key, claims={"iat": now - 4000, "exp": now - 3000}),
        "wrong_audience": mint_token(signing_key, claims={"aud": ["someone-else"]}),
        "wrong_issuer": mint_token(signing_key, claims={"iss": ISSUER + "/x"}),
        "bad_signature": mint_token(other_key),
        "missing_claim": mint_token(signing_key, drop=("iat",)),
        "malformed": "a.b.c",
    }

    responses = {name: anon_client.get(ME, headers=_bearer(tok)) for name, tok in tokens.items()}

    assert {r.status_code for r in responses.values()} == {401}
    # Indistinguishable to the caller: same code and message for every reason.
    assert {(_error(r)["code"], _error(r)["message"]) for r in responses.values()} == {
        ("unauthorized", "Authentication required")
    }


def test_a_valid_token_for_an_unknown_identity_is_403_and_creates_nothing(
    anon_client: TestClient, signing_key: SigningKey, identity_repo: FakeIdentityRepository
) -> None:
    response = anon_client.get(ME, headers=_bearer(mint_token(signing_key)))

    assert response.status_code == 403
    assert _error(response)["code"] == "forbidden"
    assert identity_repo.lookups == 1


def test_the_principal_comes_from_the_database_not_from_token_claims(
    anon_client: TestClient, signing_key: SigningKey, identity_repo: FakeIdentityRepository
) -> None:
    context = identity_repo.link(email="db-user@example.test", role=UserRole.MEMBER)
    token = mint_token(
        signing_key,
        claims={"role": "admin", "roles": ["admin"], "email": "claimed-admin@example.test"},
    )

    response = anon_client.get(ME, headers=_bearer(token))

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "user_id": str(context.user.id),
        "organization_id": str(context.organization.id),
        "email": "db-user@example.test",
        "role": "member",
    }


@pytest.mark.parametrize(
    ("user_active", "organization_active"), [(False, True), (True, False), (False, False)]
)
def test_disabled_users_and_organizations_are_403_even_with_a_valid_token(
    anon_client: TestClient,
    signing_key: SigningKey,
    identity_repo: FakeIdentityRepository,
    user_active: bool,
    organization_active: bool,
) -> None:
    identity_repo.link(user_active=user_active, organization_active=organization_active)

    response = anon_client.get(ME, headers=_bearer(mint_token(signing_key)))

    assert response.status_code == 403
    assert _error(response)["code"] == "forbidden"


def test_an_unreachable_key_set_is_503_not_401(
    anon_client: TestClient, signing_key: SigningKey
) -> None:
    class _Down:
        async def get_signing_key(self, token: str) -> Any:
            raise AuthKeysUnavailableError("jwks_unreachable")

    app.dependency_overrides[get_token_verifier] = lambda: TokenVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        algorithms=["RS256"],
        leeway_seconds=30,
        key_provider=_Down(),
    )

    response = anon_client.get(ME, headers=_bearer(mint_token(signing_key)))

    assert response.status_code == 503
    assert _error(response)["code"] == "auth_unavailable"


def test_a_database_failure_during_identity_lookup_is_503(
    anon_client: TestClient, signing_key: SigningKey, identity_repo: FakeIdentityRepository
) -> None:
    identity_repo.fail_with = SQLAlchemyError("database is down")

    response = anon_client.get(ME, headers=_bearer(mint_token(signing_key)))

    assert response.status_code == 503
    assert _error(response)["code"] == "auth_unavailable"
    assert "database is down" not in response.text


def test_unconfigured_authentication_fails_closed(real_auth: None) -> None:
    """Local development without AUTH_* settings: nothing gets through."""
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,  # type: ignore[call-arg]
        auth_issuer=None,
        auth_audience=None,
        auth_jwks_url=None,
    )
    try:
        with TestClient(app) as client:
            response = client.get(ME, headers=_bearer("anything"))
            anonymous = client.get(ME)
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 503
    assert anonymous.status_code == 503
    assert _error(response)["code"] == "auth_unavailable"


def test_cors_preflight_does_not_need_a_token(anon_client: TestClient) -> None:
    response = anon_client.options(
        ME,
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_streaming_endpoints_reject_anonymous_callers_before_streaming(
    anon_client: TestClient,
) -> None:
    for path in (
        "/api/v1/agents/run/stream",
        "/api/v1/rag/chat/stream",
        "/api/v1/chat/completions/stream",
    ):
        response = anon_client.post(path, json={"message": "hi"})

        assert response.status_code == 401, path
        assert response.headers["content-type"].startswith("application/json"), path


def test_the_token_is_never_written_to_the_logs(
    anon_client: TestClient, signing_key: SigningKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    class _Recorder:
        def __getattr__(self, level: str) -> Any:
            return lambda event, **kw: calls.append((event, kw))

    monkeypatch.setattr(security_module, "logger", _Recorder())
    now = int(time.time())
    tokens = [
        mint_token(signing_key, claims={"iat": now - 4000, "exp": now - 3000}),
        mint_token(signing_key),  # valid but unknown identity
        "garbage-token-value",
    ]

    for token in tokens:
        anon_client.get(ME, headers=_bearer(token))

    logged = repr(calls)
    assert calls, "expected the denials to be logged"
    for token in tokens:
        assert token not in logged
    assert "reason" in logged


def test_the_real_verifier_factory_builds_one_verifier_per_configuration() -> None:
    """The production path (no overrides): settings -> a cached TokenVerifier
    backed by a PyJWKClient. No network is touched until a token is verified."""
    security_module._cached_verifier.cache_clear()

    def configured(audience: str) -> Settings:
        return Settings(
            _env_file=None,  # type: ignore[call-arg]
            auth_issuer=ISSUER,
            auth_audience=audience,
            auth_jwks_url="https://idp.example.test/realms/aegis/protocol/openid-connect/certs",
        )

    first = get_token_verifier(configured(AUDIENCE))
    again = get_token_verifier(configured(AUDIENCE))
    other = get_token_verifier(configured("another-api"))

    assert isinstance(first, TokenVerifier)
    assert again is first  # one verifier (and one cached key set) across requests
    assert other is not first
    security_module._cached_verifier.cache_clear()


def test_require_admin_allows_only_admins() -> None:
    def principal(role: UserRole) -> Principal:
        import uuid

        return Principal(
            user_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            role=role,
            email="x@example.test",
            issuer=ISSUER,
        )

    admin = principal(UserRole.ADMIN)
    assert require_admin(admin) is admin
    with pytest.raises(ForbiddenError):
        require_admin(principal(UserRole.MEMBER))
