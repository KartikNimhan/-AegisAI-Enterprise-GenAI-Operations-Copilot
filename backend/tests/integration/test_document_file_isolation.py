"""M10.6: downloading an original file against a real PostgreSQL database.

Uses the five-person world of test_data_isolation.py (alice, alan and admin ada in Acme; bob and
admin bea in Other) and real local file storage in a temporary directory.

STATUS: written offline, NOT RUN. The integration suite needs the test database at the code's
migration head (0009), and applying migrations needs the owner's approval.
"""

# ruff: noqa: F811 -- the `world` and `client` fixtures are imported from test_data_isolation.py
# and requested by name, which pyflakes reads as a redefinition.

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from ..document_fixtures import make_txt_bytes
from .test_data_isolation import World, as_user, client, error_of, upload, world  # noqa: F401

pytestmark = pytest.mark.integration


async def _upload(client: AsyncClient, world: World, content: bytes, name: str) -> str:
    response = await upload(client, world.alice, content, name=name)
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


async def test_the_owner_downloads_the_exact_bytes_as_an_attachment(
    client: AsyncClient, world: World
) -> None:
    content = make_txt_bytes()
    document_id = await _upload(client, world, content, "Quarterly report.txt")

    response = await as_user(client, world.alice, "GET", f"/api/v1/documents/{document_id}/file")

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert 'filename="Quarterly report.txt"' in response.headers["content-disposition"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "private, no-store"


async def test_a_private_original_is_404_for_everyone_else_like_a_guessed_id(
    client: AsyncClient, world: World
) -> None:
    document_id = await _upload(client, world, make_txt_bytes(), "private.txt")
    guessed = uuid.uuid4()

    for stranger in world.everyone_but(world.alice):
        real = await as_user(client, stranger, "GET", f"/api/v1/documents/{document_id}/file")
        fake = await as_user(client, stranger, "GET", f"/api/v1/documents/{guessed}/file")
        assert real.status_code == 404, stranger.email
        assert error_of(real)[:2] == error_of(fake)[:2], stranger.email
        assert "content-disposition" not in real.headers


async def test_sharing_opens_the_original_to_the_organization_only_and_revoking_closes_it(
    client: AsyncClient, world: World
) -> None:
    document_id = await _upload(client, world, make_txt_bytes(), "shared.txt")
    url = f"/api/v1/documents/{document_id}/file"

    shared = await as_user(
        client,
        world.alice,
        "PATCH",
        f"/api/v1/documents/{document_id}/visibility",
        json={"visibility": "organization"},
    )
    assert shared.status_code == 200
    for colleague in (world.alan, world.ada):
        assert (await as_user(client, colleague, "GET", url)).status_code == 200
    for outsider in (world.bob, world.bea):
        assert (await as_user(client, outsider, "GET", url)).status_code == 404

    revoked = await as_user(
        client,
        world.alice,
        "PATCH",
        f"/api/v1/documents/{document_id}/visibility",
        json={"visibility": "private"},
    )
    assert revoked.status_code == 200
    for former in (world.alan, world.ada):
        assert (await as_user(client, former, "GET", url)).status_code == 404


async def test_a_deleted_document_has_no_original(client: AsyncClient, world: World) -> None:
    document_id = await _upload(client, world, make_txt_bytes(), "deleted.txt")
    deleted = await as_user(client, world.alice, "DELETE", f"/api/v1/documents/{document_id}")
    assert deleted.status_code == 204

    response = await as_user(client, world.alice, "GET", f"/api/v1/documents/{document_id}/file")
    assert response.status_code == 404
