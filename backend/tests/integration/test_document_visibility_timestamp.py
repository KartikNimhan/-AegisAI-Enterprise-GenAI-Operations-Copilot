"""Regression test: changing a document's visibility when the new `updated_at` equals the old one.

`Document.updated_at` has `onupdate=func.now()`. `DocumentRepository.set_visibility` assigns
`updated_at = datetime.now(UTC)` itself, so that the server-side default is not used and the
attribute is not left expired. But when the assigned value EQUALS the one already held by the
object, SQLAlchemy sees no change to `updated_at`. Because `visibility` did change, the UPDATE
still runs, `onupdate=func.now()` is applied in SQL, and the ORM marks `updated_at` expired.
Reading it while serializing the response then triggered a synchronous lazy load, which in async
code raises `MissingGreenlet`.

On Windows with Python 3.12, `datetime.now()` advances about once a millisecond
(`GetSystemTimeAsFileTime`), so an upload followed at once by a share could hit this by chance:
`test_a_colleague_who_can_read_a_shared_document_cannot_change_or_delete_it` failed that way once
(2026-11-04). Here the clock is frozen to the stored value, so the collision happens every time,
on any platform.

Uses the five-person world of test_data_isolation.py against the migrated test database.
"""

# ruff: noqa: F811 -- the `world` and `client` fixtures are imported from test_data_isolation.py
# and requested by name, which pyflakes reads as a redefinition.

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import document_repository
from app.domain.models.document import Document

from .test_data_isolation import World, as_user, client, upload_id, world  # noqa: F401

pytestmark = pytest.mark.integration


async def _freeze_clock_at_the_stored_value(
    db_session: AsyncSession, document_id: str, monkeypatch: pytest.MonkeyPatch
) -> datetime:
    """Makes `datetime.now()` in the repository return exactly the document's current
    `updated_at`, which is what a coarse clock does within one tick."""
    document = await db_session.get(Document, uuid.UUID(document_id))
    assert document is not None
    stored = document.updated_at
    assert stored is not None

    class _SameTick(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return stored

    monkeypatch.setattr(document_repository, "datetime", _SameTick)
    return stored


async def test_sharing_within_the_same_clock_tick_still_returns_the_document(
    client: AsyncClient, world: World, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = await upload_id(client, world.alice)
    await _freeze_clock_at_the_stored_value(db_session, document_id, monkeypatch)
    # Records every refresh the repository makes (the request uses this same session), so the test
    # can prove the collision expired `updated_at` and the fix reloaded it.
    refreshed: list[tuple[object, tuple[str, ...] | None]] = []
    original_refresh = db_session.refresh

    async def recording_refresh(instance: object, attribute_names=None, **kwargs):  # type: ignore[no-untyped-def]
        refreshed.append(
            (getattr(instance, "id", None), tuple(attribute_names) if attribute_names else None)
        )
        return await original_refresh(instance, attribute_names=attribute_names, **kwargs)

    monkeypatch.setattr(db_session, "refresh", recording_refresh)

    response = await as_user(
        client,
        world.alice,
        "PATCH",
        f"/api/v1/documents/{document_id}/visibility",
        json={"visibility": "organization"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["visibility"] == "organization"
    returned = datetime.fromisoformat(body["updated_at"])
    # The value comes from the database (`now()` of the transaction) and is a real timestamp.
    document = await db_session.get(Document, uuid.UUID(document_id))
    assert document is not None
    assert "updated_at" not in sa_inspect(document).expired_attributes
    assert returned == document.updated_at
    assert returned.tzinfo is not None
    # The collision really expired `updated_at`, and the repository reloaded exactly that attribute
    # of this document (without the collision there would be no refresh at all).
    assert refreshed == [(uuid.UUID(document_id), ("updated_at",))]


async def test_making_private_within_the_same_clock_tick_still_returns_the_document(
    client: AsyncClient, world: World, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = await upload_id(client, world.alice)
    shared = await as_user(
        client,
        world.alice,
        "PATCH",
        f"/api/v1/documents/{document_id}/visibility",
        json={"visibility": "organization"},
    )
    assert shared.status_code == 200, shared.text
    await _freeze_clock_at_the_stored_value(db_session, document_id, monkeypatch)

    response = await as_user(
        client,
        world.alice,
        "PATCH",
        f"/api/v1/documents/{document_id}/visibility",
        json={"visibility": "private"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["visibility"] == "private"


async def test_the_collision_does_not_change_who_may_read_the_document(
    client: AsyncClient, world: World, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = await upload_id(client, world.alice)
    await _freeze_clock_at_the_stored_value(db_session, document_id, monkeypatch)
    shared = await as_user(
        client,
        world.alice,
        "PATCH",
        f"/api/v1/documents/{document_id}/visibility",
        json={"visibility": "organization"},
    )
    assert shared.status_code == 200, shared.text

    url = f"/api/v1/documents/{document_id}"
    for colleague in (world.alan, world.ada):
        assert (await as_user(client, colleague, "GET", url)).status_code == 200
    for outsider in (world.bob, world.bea):
        assert (await as_user(client, outsider, "GET", url)).status_code == 404
    # A colleague still cannot change it, even within the same tick.
    refused = await as_user(
        client, world.alan, "PATCH", f"{url}/visibility", json={"visibility": "private"}
    )
    assert refused.status_code == 404
