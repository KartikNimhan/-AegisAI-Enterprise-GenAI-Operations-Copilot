"""Rate limits applied to the real routes (offline: fake services, a controllable limiter).

Covers: which routes are metered and in which bucket; what a refused caller sees (429, generic
message, Retry-After, no limit values); that a refused request never reaches the service; that
each user has their own budget; that an anonymous request is refused by authentication before it
can touch any budget; that the limiter failing closes the route (503); and that the audit trail
records a refusal.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.core import audit
from app.core.rate_limit import RateLimitBucket, SlidingWindowRateLimiter, get_rate_limiter
from app.embeddings.service import get_embedding_service
from app.main import app
from app.services.document_service import DocumentUploadResult, get_document_service

from ...conftest import DEFAULT_TEST_PRINCIPAL
from .test_documents_endpoint import FakeDocumentService, make_document
from .test_embeddings_endpoint import FakeEmbeddingService, make_result


def post_upload(client: TestClient) -> Any:
    return client.post(
        "/api/v1/documents", files={"file": ("report.txt", b"hello world", "text/plain")}
    )


class CountingDocumentService(FakeDocumentService):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.uploads = 0

    async def upload(self, **kwargs: Any) -> DocumentUploadResult:
        self.uploads += 1
        return await super().upload(**kwargs)


class CountingEmbeddingService(FakeEmbeddingService):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.jobs = 0

    async def embed_document(self, document_id: uuid.UUID) -> Any:
        self.jobs += 1
        return await super().embed_document(document_id)


@pytest.fixture
def install() -> Iterator[Any]:
    """Installs a limiter (and optionally services) for the test; restores everything after."""

    def _install(limiter: Any) -> None:
        app.dependency_overrides[get_rate_limiter] = lambda: limiter

    yield _install
    for dependency in (get_rate_limiter, get_document_service, get_embedding_service, get_settings):
        app.dependency_overrides.pop(dependency, None)


def small_limiter(**limits: int) -> SlidingWindowRateLimiter:
    mapping = {
        RateLimitBucket.LLM: limits.get("llm", 0),
        RateLimitBucket.UPLOAD: limits.get("upload", 0),
        RateLimitBucket.EMBEDDING: limits.get("embedding", 0),
    }
    return SlidingWindowRateLimiter(window_seconds=60, limits=mapping, max_tracked_keys=1_000)


def act_as_new_user() -> None:
    other = replace(DEFAULT_TEST_PRINCIPAL, user_id=uuid.uuid4())
    from app.core.security import get_current_principal

    app.dependency_overrides[get_current_principal] = lambda: other


# -- uploads ---------------------------------------------------------------------------


def test_uploads_beyond_the_limit_are_refused_with_a_generic_429(
    client: TestClient, install: Any
) -> None:
    install(small_limiter(upload=2))
    service = CountingDocumentService(
        upload_result=DocumentUploadResult(document=make_document(), is_duplicate=False)
    )
    app.dependency_overrides[get_document_service] = lambda: service

    statuses = [post_upload(client).status_code for _ in range(3)]
    refused = post_upload(client)

    assert statuses == [201, 201, 429]
    assert refused.status_code == 429
    assert int(refused.headers["retry-after"]) >= 1
    error = refused.json()["error"]
    assert error["code"] == "rate_limited"
    assert error["message"] == "Too many requests. Please try again later."
    assert "2" not in error["message"]  # the configured limit is not disclosed
    assert service.uploads == 2  # a refused upload never reached the service


def test_each_user_has_their_own_budget(client: TestClient, install: Any) -> None:
    install(small_limiter(upload=1))
    app.dependency_overrides[get_document_service] = lambda: CountingDocumentService(
        upload_result=DocumentUploadResult(document=make_document(), is_duplicate=False)
    )

    first_user = [post_upload(client).status_code for _ in range(2)]
    act_as_new_user()
    second_user = post_upload(client).status_code

    assert first_user == [201, 429]
    assert second_user == 201  # another user is not affected by the first user's usage


# -- embedding jobs --------------------------------------------------------------------


def test_embedding_jobs_beyond_the_limit_are_refused_before_any_work_starts(
    client: TestClient, install: Any
) -> None:
    install(small_limiter(embedding=1))
    service = CountingEmbeddingService(embed_result=make_result())
    app.dependency_overrides[get_embedding_service] = lambda: service
    url = f"/api/v1/documents/{uuid.uuid4()}/embeddings"

    codes = [client.post(url).status_code for _ in range(3)]

    assert codes == [200, 429, 429]
    assert service.jobs == 1


def test_reading_embedding_status_is_not_metered(client: TestClient, install: Any) -> None:
    install(small_limiter(embedding=1))
    from .test_embeddings_endpoint import make_status

    app.dependency_overrides[get_embedding_service] = lambda: FakeEmbeddingService(
        status_result=make_status()
    )
    url = f"/api/v1/documents/{uuid.uuid4()}/embeddings"

    assert [client.get(url).status_code for _ in range(5)] == [200] * 5


# -- which routes are metered, and in which bucket ---------------------------------------


class RecordingLimiter:
    """Refuses everything and remembers which bucket each request asked about."""

    def __init__(self) -> None:
        self.asked: list[RateLimitBucket] = []

    def check(self, bucket: RateLimitBucket, key: str) -> int:
        self.asked.append(bucket)
        return 7


METERED = [
    ("POST", "/api/v1/chat/completions", RateLimitBucket.LLM),
    ("POST", "/api/v1/chat/completions/stream", RateLimitBucket.LLM),
    ("POST", "/api/v1/rag/chat", RateLimitBucket.LLM),
    ("POST", "/api/v1/rag/chat/stream", RateLimitBucket.LLM),
    ("POST", "/api/v1/agents/run", RateLimitBucket.LLM),
    ("POST", "/api/v1/agents/run/stream", RateLimitBucket.LLM),
    ("POST", "/api/v1/multi-agent/run", RateLimitBucket.LLM),
    ("POST", "/api/v1/agents/research/tasks", RateLimitBucket.LLM),
    ("POST", "/api/v1/agents/analyst/tasks", RateLimitBucket.LLM),
    ("POST", "/api/v1/documents", RateLimitBucket.UPLOAD),
    ("POST", f"/api/v1/documents/{uuid.uuid4()}/embeddings", RateLimitBucket.EMBEDDING),
]


@pytest.mark.parametrize(("method", "path", "bucket"), METERED)
def test_every_expensive_route_is_metered_in_the_right_bucket(
    client: TestClient, install: Any, method: str, path: str, bucket: RateLimitBucket
) -> None:
    limiter = RecordingLimiter()
    install(limiter)

    response = client.request(method, path, json={"message": "hi"})

    assert response.status_code == 429, (path, response.text)
    assert limiter.asked == [bucket]
    assert response.headers["retry-after"] == "7"


CHEAP = [
    ("GET", "/api/v1/documents"),
    ("GET", f"/api/v1/documents/{uuid.uuid4()}"),
    ("DELETE", f"/api/v1/documents/{uuid.uuid4()}"),
    ("GET", "/api/v1/auth/me"),
]


@pytest.mark.parametrize(("method", "path"), CHEAP)
def test_cheap_routes_are_never_metered(
    client: TestClient, install: Any, method: str, path: str
) -> None:
    limiter = RecordingLimiter()
    install(limiter)
    app.dependency_overrides[get_document_service] = lambda: FakeDocumentService()

    response = client.request(method, path, json={"visibility": "private"})

    assert response.status_code != 429
    assert limiter.asked == []


# -- authentication comes first, and the limiter fails closed --------------------------


def test_an_anonymous_request_is_refused_by_authentication_and_never_touches_a_budget(
    anon_client: TestClient, install: Any
) -> None:
    limiter = RecordingLimiter()
    install(limiter)

    response = anon_client.post("/api/v1/chat/completions", json={"message": "hi"})

    assert response.status_code == 401
    assert limiter.asked == []


def test_a_limiter_that_cannot_enforce_closes_the_route_instead_of_opening_it(
    client: TestClient, install: Any
) -> None:
    class Broken:
        def check(self, bucket: RateLimitBucket, key: str) -> None:
            raise RuntimeError("limiter state is corrupt")

    install(Broken())
    service = CountingDocumentService(
        upload_result=DocumentUploadResult(document=make_document(), is_duplicate=False)
    )
    app.dependency_overrides[get_document_service] = lambda: service

    response = post_upload(client)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert "corrupt" not in response.text  # the cause is logged, not returned
    assert service.uploads == 0


def test_switching_rate_limiting_off_is_explicit_and_complete(
    client: TestClient, install: Any
) -> None:
    limiter = RecordingLimiter()
    install(limiter)
    app.dependency_overrides[get_settings] = lambda: Settings(rate_limit_enabled=False)
    app.dependency_overrides[get_document_service] = lambda: CountingDocumentService(
        upload_result=DocumentUploadResult(document=make_document(), is_duplicate=False)
    )

    response = post_upload(client)

    assert response.status_code == 201
    assert limiter.asked == []


# -- the audit trail -------------------------------------------------------------------


def test_a_refusal_is_recorded_in_the_audit_trail_without_the_limit_values(
    client: TestClient, install: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    class Recorder:
        def __getattr__(self, level: str) -> Any:
            return lambda event, **kw: calls.append((level, kw))

    monkeypatch.setattr(audit, "logger", Recorder())
    install(RecordingLimiter())

    client.post("/api/v1/chat/completions", json={"message": "hi"})

    assert len(calls) == 1
    level, fields = calls[0]
    assert level == "warning"
    assert fields["audit_action"] == "rate_limit.exceeded"
    assert fields["audit_outcome"] == "limited"
    assert fields["resource_id"] == "llm"
    assert fields["actor_user_id"] == str(DEFAULT_TEST_PRINCIPAL.user_id)
    assert not {"limit", "retry_after", "remaining"} & set(fields)  # no limit values in the log
