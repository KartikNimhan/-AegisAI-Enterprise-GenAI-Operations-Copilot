"""Rate-limit refusals and limiter failures, measured at the `rate_limited` dependency."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.core.rate_limit import get_rate_limiter
from app.embeddings.service import get_embedding_service
from app.main import app
from app.services.document_service import DocumentUploadResult, get_document_service

from ..api.test_documents_endpoint import make_document
from ..api.test_embeddings_endpoint import FakeEmbeddingService, make_result
from ..api.test_rate_limited_routes import CountingDocumentService, post_upload, small_limiter
from .helpers import exposition, value


@pytest.fixture
def wired() -> Iterator[None]:
    app.dependency_overrides[get_document_service] = lambda: CountingDocumentService(
        upload_result=DocumentUploadResult(document=make_document(), is_duplicate=False)
    )
    app.dependency_overrides[get_embedding_service] = lambda: FakeEmbeddingService(
        embed_result=make_result()
    )
    yield
    for dependency in (
        get_rate_limiter,
        get_document_service,
        get_embedding_service,
        get_settings,
    ):
        app.dependency_overrides.pop(dependency, None)


def test_refusals_are_counted_per_bucket_and_admissions_are_not(
    client: TestClient, wired: None
) -> None:
    limiter = small_limiter(upload=2, embedding=1)
    app.dependency_overrides[get_rate_limiter] = lambda: limiter

    codes = [post_upload(client).status_code for _ in range(4)]
    embedding_url = f"/api/v1/documents/{uuid.uuid4()}/embeddings"
    embedding_codes = [client.post(embedding_url).status_code for _ in range(3)]

    assert codes == [201, 201, 429, 429]
    assert embedding_codes == [200, 429, 429]
    assert value("aegis_rate_limit_refusals_total", bucket="upload") == 2
    assert value("aegis_rate_limit_refusals_total", bucket="embedding") == 2
    assert value("aegis_rate_limit_refusals_total", bucket="llm") == 0
    # The same refusals are visible in the request metrics, under the route template.
    assert value("aegis_http_requests_total", route="/api/v1/documents", status="429") == 2
    assert value("aegis_http_requests_total", route="/api/v1/documents", status="201") == 2
    assert "aegis_rate_limiter_unavailable_total" not in _nonzero_names()


def test_the_429_response_is_unchanged_by_metrics(client: TestClient, wired: None) -> None:
    limiter = small_limiter(upload=1)
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    post_upload(client)

    refused = post_upload(client)

    assert refused.status_code == 429
    assert int(refused.headers["retry-after"]) >= 1
    assert refused.json()["error"]["code"] == "rate_limited"
    assert refused.json()["error"]["message"] == "Too many requests. Please try again later."


class BrokenLimiter:
    def check(self, *args: Any, **kwargs: Any) -> int | None:
        raise RuntimeError("limiter state is corrupt")


def test_a_failing_limiter_is_counted_separately_and_still_fails_closed(
    client: TestClient, wired: None
) -> None:
    app.dependency_overrides[get_rate_limiter] = lambda: BrokenLimiter()

    response = post_upload(client)

    assert response.status_code == 503
    assert value("aegis_rate_limiter_unavailable_total", bucket="upload") == 1
    assert value("aegis_rate_limit_refusals_total", bucket="upload") == 0
    assert "limiter state is corrupt" not in exposition()


def test_nothing_is_counted_when_rate_limiting_is_switched_off(
    client: TestClient, wired: None
) -> None:
    limiter = small_limiter(upload=1)
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,  # type: ignore[call-arg]
        rate_limit_enabled=False,
    )

    codes = [post_upload(client).status_code for _ in range(3)]

    assert codes == [201, 201, 201]
    assert value("aegis_rate_limit_refusals_total", bucket="upload") == 0


def test_a_refusal_for_one_user_exposes_no_user_identity(client: TestClient, wired: None) -> None:
    limiter = small_limiter(upload=1)
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    post_upload(client)
    post_upload(client)

    text = exposition()

    assert "test-user@example.test" not in text
    assert "00000000-0000-0000-0000-0000000000a1" not in text  # the default test user's id


def _nonzero_names() -> set[str]:
    from .helpers import samples

    return {name for name, _, v in samples() if v}
