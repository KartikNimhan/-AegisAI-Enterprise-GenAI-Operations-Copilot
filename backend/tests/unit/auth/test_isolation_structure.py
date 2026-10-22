"""Structural guards for data isolation.

These fail if someone makes it possible to reach business data without an access scope:
a repository whose constructor no longer requires one, an unrestricted scope built inside
the request path, or a data route that no longer depends on the scope.
"""

from __future__ import annotations

import inspect
import re
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.security import get_access_scope
from app.db.repositories.chunk_embedding_repository import ChunkEmbeddingRepository
from app.db.repositories.conversation_repository import ConversationRepository
from app.db.repositories.document_chunk_repository import DocumentChunkRepository
from app.db.repositories.document_repository import DocumentRepository
from app.db.repositories.message_repository import MessageRepository
from app.main import app
from app.rag.retrieval.repository import RetrievalRepository

APP_DIR = Path(__file__).resolve().parents[3] / "app"

BUSINESS_REPOSITORIES = [
    DocumentRepository,
    DocumentChunkRepository,
    ChunkEmbeddingRepository,
    ConversationRepository,
    MessageRepository,
    RetrievalRepository,
]


@pytest.mark.parametrize("repository", BUSINESS_REPOSITORIES, ids=lambda r: r.__name__)
def test_a_business_repository_cannot_be_built_without_a_scope(repository: type) -> None:
    parameter = inspect.signature(repository.__init__).parameters.get("scope")

    assert parameter is not None, f"{repository.__name__} takes no scope"
    assert parameter.default is inspect.Parameter.empty, "the scope must be required, not optional"


def test_the_unrestricted_scope_is_defined_in_one_place_and_never_used_by_the_application() -> None:
    users = [
        path.relative_to(APP_DIR).as_posix()
        for path in APP_DIR.rglob("*.py")
        if "unrestricted_for_operators" in path.read_text(encoding="utf8")
    ]

    # Operator tools (scripts/) may use it; nothing under app/ may except its definition.
    assert users == ["auth/scope.py"]


# Operations that read or write business data themselves. Deliberately not in this list: agent
# cards, health, auth/me and the admin-only system status; the analyst agent (it only calls the LLM
# on evidence the caller supplies); and /multi-agent/run, which touches no repository itself: it
# forwards the CALLER'S OWN bearer token to the research and document agent endpoints below, and
# those resolve the same principal and are scoped.
DATA_PREFIXES = (
    "/api/v1/documents",
    "/api/v1/conversations",
    "/api/v1/chat",
    "/api/v1/rag",
    "/api/v1/agents/run",
    "/api/v1/memories",
    "/api/v1/operations",
    "/api/v1/agents/research/tasks",
    "/api/v1/agents/document/tasks",
)
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def _data_operations() -> list[tuple[str, str]]:
    return [
        (method.upper(), path)
        for path, item in app.openapi()["paths"].items()
        if path.startswith(DATA_PREFIXES)
        for method in item
        if method in HTTP_METHODS
    ]


def test_the_data_operation_list_covers_the_known_surface() -> None:
    operations = set(_data_operations())

    assert ("GET", "/api/v1/documents/{document_id}") in operations
    assert ("PATCH", "/api/v1/documents/{document_id}/visibility") in operations
    assert ("DELETE", "/api/v1/conversations/{conversation_id}") in operations
    assert ("POST", "/api/v1/rag/chat") in operations
    assert ("DELETE", "/api/v1/memories/{memory_id}") in operations
    assert ("POST", "/api/v1/agents/document/tasks") in operations
    assert len(operations) >= 18


def test_every_data_operation_asks_for_the_callers_access_scope(client: TestClient) -> None:
    """A probe replaces the scope dependency and stops the request. A route that no longer
    depends on the scope never reaches the probe, so this cannot pass vacuously."""
    reached: list[str] = []

    def probe() -> None:
        reached.append("scope requested")
        raise HTTPException(status_code=418, detail="stopped at the scope probe")

    app.dependency_overrides[get_access_scope] = probe
    try:
        not_reached = []
        for method, path in _data_operations():
            reached.clear()
            url = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)
            response = client.request(method, url)
            if response.status_code != 418 or not reached:
                not_reached.append(f"{method} {path} -> {response.status_code}")
    finally:
        app.dependency_overrides.pop(get_access_scope, None)

    assert not not_reached, f"operations that never ask for a scope: {not_reached}"


def test_the_access_scope_is_derived_from_the_authenticated_principal() -> None:
    parameters = inspect.signature(get_access_scope).parameters

    assert list(parameters) == ["principal"]
