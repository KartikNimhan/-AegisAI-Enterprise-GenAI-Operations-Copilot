"""Whatever the traffic, the exposition must carry no identity or request data.

Drives a mix of authenticated, unauthenticated, failing and rate-limited requests and a few LLM
calls, then inspects EVERY sample line.
"""

from __future__ import annotations

import contextlib
import re
import uuid

from fastapi.testclient import TestClient

from app.llm.exceptions import LLMTimeoutError
from app.llm.gateway import LLMGateway
from app.llm.schemas import ChatMessage, ChatRole, ModelRole
from app.observability import metrics

from ...conftest import DEFAULT_TEST_BEARER_TOKEN, DEFAULT_TEST_PRINCIPAL
from ..llm.doubles import ScriptedProvider
from ..llm.test_gateway import make_settings
from .helpers import exposition, samples

BOUNDED_VALUE = re.compile(r"[a-z0-9][a-z0-9_.-]{0,31}")
ROUTE_TEMPLATE = re.compile(r"/[A-Za-z0-9_./{}-]{0,127}")


async def test_no_identity_or_request_data_appears_anywhere(client: TestClient) -> None:
    # Requests that need no database: an authenticated one (its body carries the caller's e-mail
    # and ids), and ones rejected by validation, with identifying text in path and query.
    conversation_id, document_id = "alice-conversation-77", "alice-secret-report"
    client.get("/health", headers={"X-Request-ID": "req-should-not-appear"})
    me = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {DEFAULT_TEST_BEARER_TOKEN}"}
    )
    assert me.status_code == 200 and DEFAULT_TEST_PRINCIPAL.email in me.text
    client.get(f"/api/v1/conversations/{conversation_id}")
    client.get(f"/api/v1/documents/{document_id}/chunks?filename=secret-report.pdf&q=alice")
    client.get("/totally/unknown/alice@example.test/secret-report.pdf")
    gateway = LLMGateway(
        make_settings(llm_max_retries=0),
        provider=ScriptedProvider([LLMTimeoutError("alice's private prompt", provider="fake")]),
    )
    with contextlib.suppress(LLMTimeoutError):
        await gateway.chat_completion(
            model_role=ModelRole.PRIMARY,
            messages=[ChatMessage(role=ChatRole.USER, content="alice's private prompt")],
        )

    text = exposition()

    forbidden = [
        DEFAULT_TEST_PRINCIPAL.email,
        str(DEFAULT_TEST_PRINCIPAL.user_id),
        str(DEFAULT_TEST_PRINCIPAL.organization_id),
        DEFAULT_TEST_PRINCIPAL.issuer,
        DEFAULT_TEST_BEARER_TOKEN,
        str(conversation_id),
        str(document_id),
        "req-should-not-appear",
        "secret-report",
        "alice",
        "private prompt",
        "Bearer",
    ]
    for item in forbidden:
        assert item not in text, f"{item!r} leaked into the metrics"


async def test_every_label_value_is_a_bounded_token_or_a_route_template(
    client: TestClient,
) -> None:
    client.get("/health")
    client.get("/api/v1/documents/not-a-uuid/chunks")  # 422, no database
    client.get("/zzz")
    gateway = LLMGateway(
        make_settings(llm_max_retries=0),
        provider=ScriptedProvider([LLMTimeoutError("x", provider="fake")]),
    )
    with contextlib.suppress(LLMTimeoutError):
        await gateway.chat_completion(model_role=ModelRole.FAST, messages=[])

    found = samples()
    assert found
    for name, labels, _ in found:
        assert name.startswith("aegis_")
        for label_name, label_value in labels.items():
            if label_name == "le":  # histogram bucket boundary
                continue
            if label_name == "route":
                assert label_value == "unmatched" or ROUTE_TEMPLATE.fullmatch(label_value)
                assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}", label_value)  # no raw ids
            elif label_name in {"method", "status"}:
                assert re.fullmatch(r"[A-Za-z0-9]{1,16}", label_value)
            elif label_name == "error_type":
                assert label_value in metrics.KNOWN_LLM_ERROR_TYPES | {"other"}
            else:
                assert BOUNDED_VALUE.fullmatch(label_value), (name, label_name, label_value)


def test_the_series_count_stays_small_however_many_distinct_requests_arrive(
    client: TestClient,
) -> None:
    for _ in range(60):
        client.get(
            f"/api/v1/documents/id-{uuid.uuid4().hex}/chunks"
        )  # not a UUID: 422, no database
        client.get(f"/random/{uuid.uuid4()}")

    series = {(name, tuple(sorted(labels.items()))) for name, labels, _ in samples()}

    assert len(series) < 100  # bounded by templates and status codes, not by traffic
