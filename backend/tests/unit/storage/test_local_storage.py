"""Unit tests for LocalFileStorage. Uses pytest's `tmp_path` — no real
project storage directory is touched."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.storage.local import LocalFileStorage


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileStorage:
    return LocalFileStorage(tmp_path / "uploads")


async def test_save_creates_the_storage_root_if_missing(tmp_path: Path) -> None:
    root = tmp_path / "does" / "not" / "exist" / "yet"
    storage = LocalFileStorage(root)

    await storage.save(key="a.txt", content=b"hello")

    assert root.is_dir()
    assert (root / "a.txt").read_bytes() == b"hello"


async def test_save_and_read_round_trip(storage: LocalFileStorage) -> None:
    await storage.save(key="doc.txt", content=b"some file content")

    result = await storage.read(key="doc.txt")

    assert result == b"some file content"


async def test_exists_reflects_actual_state(storage: LocalFileStorage) -> None:
    assert await storage.exists(key="missing.txt") is False

    await storage.save(key="present.txt", content=b"x")

    assert await storage.exists(key="present.txt") is True


async def test_delete_removes_the_file(storage: LocalFileStorage) -> None:
    await storage.save(key="to_delete.txt", content=b"x")

    await storage.delete(key="to_delete.txt")

    assert await storage.exists(key="to_delete.txt") is False


async def test_delete_of_missing_key_does_not_raise(storage: LocalFileStorage) -> None:
    await storage.delete(key="never_existed.txt")  # no raise


async def test_read_of_missing_key_raises(storage: LocalFileStorage) -> None:
    with pytest.raises(FileNotFoundError):
        await storage.read(key="missing.txt")


async def test_rejects_a_key_that_escapes_the_storage_root(storage: LocalFileStorage) -> None:
    with pytest.raises(ValueError, match="escapes"):
        await storage.save(key="../../outside.txt", content=b"x")


async def test_keys_are_opaque_and_may_contain_a_uuid_and_extension(
    storage: LocalFileStorage,
) -> None:
    key = "3fa85f64-5717-4562-b3fc-2c963f66afa6.pdf"

    await storage.save(key=key, content=b"%PDF-fake")

    assert await storage.read(key=key) == b"%PDF-fake"
