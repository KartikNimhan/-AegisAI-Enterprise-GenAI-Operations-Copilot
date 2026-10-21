"""Shared pytest fixtures.

Unit tests must not require a live Postgres/Redis — connectivity checks are
monkeypatched where needed. Integration tests (backend/tests/integration)
skip themselves gracefully when no live dependency is reachable.

Authentication (Milestone 12): every business route requires a valid user, so
by default every test runs with `get_current_principal` / `get_bearer_token`
overridden to a fixed test principal and token. Tests that exercise the REAL
authentication path request the `real_auth` fixture (or `auth_env`, which also
wires a test key set and in-memory identity tables) to opt out.
"""

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.auth.principal import Principal
from app.auth.service import IdentityService
from app.config import get_settings
from app.core import rate_limit
from app.core.security import (
    get_bearer_token,
    get_current_principal,
    get_identity_service,
    get_token_verifier,
)
from app.domain.enums.user_role import UserRole
from app.main import app

from .auth_fixtures import (
    FakeIdentityRepository,
    SigningKey,
    generate_signing_key,
    make_verifier,
)

DEFAULT_TEST_PRINCIPAL = Principal(
    user_id=uuid.UUID("00000000-0000-0000-0000-0000000000a1"),
    organization_id=uuid.UUID("00000000-0000-0000-0000-0000000000b1"),
    role=UserRole.MEMBER,
    email="test-user@example.test",
    issuer="https://idp.example.test/realms/aegis",
)
DEFAULT_TEST_BEARER_TOKEN = "test-bearer-token"


@pytest.fixture
def real_auth() -> None:
    """Opts a test out of the default authentication overrides (see module docstring)."""
    return None


@pytest.fixture(autouse=True)
def _default_authentication(request: pytest.FixtureRequest) -> Iterator[None]:
    if "real_auth" in request.fixturenames:
        yield
        return
    app.dependency_overrides[get_current_principal] = lambda: DEFAULT_TEST_PRINCIPAL
    app.dependency_overrides[get_bearer_token] = lambda: DEFAULT_TEST_BEARER_TOKEN
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_principal, None)
        app.dependency_overrides.pop(get_bearer_token, None)


@pytest.fixture(scope="session")
def signing_key() -> SigningKey:
    return generate_signing_key()


@pytest.fixture
def identity_repo() -> FakeIdentityRepository:
    return FakeIdentityRepository()


@pytest.fixture
def auth_env(
    real_auth: None, signing_key: SigningKey, identity_repo: FakeIdentityRepository
) -> Iterator[None]:
    """The real authentication dependencies, backed by a test key set and
    in-memory identity tables (no network, no database)."""
    app.dependency_overrides[get_token_verifier] = lambda: make_verifier(signing_key)
    app.dependency_overrides[get_identity_service] = lambda: IdentityService(identity_repo)
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_token_verifier, None)
        app.dependency_overrides.pop(get_identity_service, None)


@pytest.fixture(autouse=True)
def _fresh_rate_limiter() -> Iterator[None]:
    """The limiter's counters are process-wide and most tests act as the same default user, so
    every test starts with empty counters (or unrelated tests would start receiving 429)."""
    rate_limit._cached_limiter.cache_clear()
    yield
    rate_limit._cached_limiter.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def anon_client(auth_env: None) -> Iterator[TestClient]:
    """A client with NO credentials against the real authentication path."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def clear_settings_cache() -> Iterator[None]:
    """Clears the lru_cache on get_settings so env var overrides take effect."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
