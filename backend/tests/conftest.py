"""Shared pytest fixtures.

Unit tests must not require a live Postgres/Redis — connectivity checks are
monkeypatched where needed. Integration tests (backend/tests/integration)
skip themselves gracefully when no live dependency is reachable.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def clear_settings_cache() -> Iterator[None]:
    """Clears the lru_cache on get_settings so env var overrides take effect."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
