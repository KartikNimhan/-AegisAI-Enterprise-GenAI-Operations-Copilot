"""The /api/v1/memories endpoints: a user manages only their own notes.

The real service and repository run over SQLite (harness.py); the service dependency is bound to
whichever person the test says is calling.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from app.main import app
from app.memory.service import get_memory_service

from .harness import Person, World


@pytest.fixture
def world() -> Iterator[World]:
    w = World(agent_memory_max_items_per_user=2, agent_memory_max_item_chars=40)
    yield w
    w.close()


@pytest.fixture
def act_as(world: World) -> Iterator[Callable[[Person], None]]:
    def _act_as(person: Person) -> None:
        app.dependency_overrides[get_memory_service] = lambda: world.service(person)

    yield _act_as
    app.dependency_overrides.pop(get_memory_service, None)


def test_create_list_update_delete_round_trip(
    client: TestClient, act_as: Callable[[Person], None]
) -> None:
    act_as(Person())

    created = client.post("/api/v1/memories", json={"content": "Likes tea", "kind": "preference"})
    assert created.status_code == 201
    body = created.json()
    assert body["content"] == "Likes tea" and body["source"] == "user"
    assert body["kind"] == "preference"

    assert [m["id"] for m in client.get("/api/v1/memories").json()] == [body["id"]]

    updated = client.patch(f"/api/v1/memories/{body['id']}", json={"content": "Likes coffee"})
    assert updated.status_code == 200 and updated.json()["content"] == "Likes coffee"

    assert client.delete(f"/api/v1/memories/{body['id']}").status_code == 204
    assert client.get("/api/v1/memories").json() == []
    assert client.delete(f"/api/v1/memories/{body['id']}").status_code == 404


def test_another_user_gets_404_for_a_memory_they_do_not_own(
    client: TestClient, act_as: Callable[[Person], None]
) -> None:
    alice, bob = Person(), Person()
    act_as(alice)
    memory_id = client.post("/api/v1/memories", json={"content": "Alice only"}).json()["id"]

    act_as(bob)
    assert client.get("/api/v1/memories").json() == []
    assert client.patch(f"/api/v1/memories/{memory_id}", json={"content": "x"}).status_code == 404
    assert client.delete(f"/api/v1/memories/{memory_id}").status_code == 404
    assert client.delete("/api/v1/memories").json() == {"deleted": 0}

    act_as(alice)
    assert [m["content"] for m in client.get("/api/v1/memories").json()] == ["Alice only"]


def test_clear_removes_only_the_callers_notes(
    client: TestClient, act_as: Callable[[Person], None]
) -> None:
    alice, bob = Person(), Person()
    act_as(alice)
    client.post("/api/v1/memories", json={"content": "a1"})
    client.post("/api/v1/memories", json={"content": "a2"})
    act_as(bob)
    client.post("/api/v1/memories", json={"content": "b1"})

    act_as(alice)
    assert client.delete("/api/v1/memories").json() == {"deleted": 2}

    act_as(bob)
    assert [m["content"] for m in client.get("/api/v1/memories").json()] == ["b1"]


@pytest.mark.parametrize(
    "payload",
    [
        {"content": ""},
        {"content": "x" * 41},
        {"content": "bell\x07"},
        {"content": "ok", "kind": "x"},
    ],
)
def test_invalid_notes_are_rejected(
    client: TestClient, act_as: Callable[[Person], None], payload: dict[str, str]
) -> None:
    act_as(Person())

    assert client.post("/api/v1/memories", json=payload).status_code == 422
    assert client.get("/api/v1/memories").json() == []


def test_a_full_memory_is_a_conflict(client: TestClient, act_as: Callable[[Person], None]) -> None:
    act_as(Person())
    client.post("/api/v1/memories", json={"content": "one"})
    client.post("/api/v1/memories", json={"content": "two"})

    response = client.post("/api/v1/memories", json={"content": "three"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "memory_full"


def test_unknown_ids_and_body_fields_cannot_reassign_ownership(
    client: TestClient, act_as: Callable[[Person], None]
) -> None:
    alice, bob = Person(), Person()
    act_as(alice)
    created = client.post(
        "/api/v1/memories",
        json={
            "content": "mine",
            "owner_user_id": str(bob.user_id),
            "organization_id": str(uuid.uuid4()),
        },
    )

    assert created.status_code == 201
    assert "owner_user_id" not in created.json()
    act_as(bob)
    assert client.get("/api/v1/memories").json() == []


def test_changes_are_audited_without_the_note_text(
    client: TestClient, act_as: Callable[[Person], None]
) -> None:
    act_as(Person())

    with capture_logs() as logs:
        memory_id = client.post("/api/v1/memories", json={"content": "very private text"}).json()[
            "id"
        ]
        client.delete(f"/api/v1/memories/{memory_id}")
        client.delete(f"/api/v1/memories/{uuid.uuid4()}")

    audit = [entry for entry in logs if entry.get("event") == "audit"]
    assert [(e["audit_action"], e["audit_outcome"]) for e in audit] == [
        ("memory.saved", "success"),
        ("memory.deleted", "success"),
        ("memory.deleted", "not_found"),
    ]
    assert "very private text" not in repr(logs)


def test_the_endpoints_require_authentication(anon_client: TestClient) -> None:
    for method, path in (("GET", "/api/v1/memories"), ("DELETE", "/api/v1/memories")):
        assert anon_client.request(method, path).status_code == 401
