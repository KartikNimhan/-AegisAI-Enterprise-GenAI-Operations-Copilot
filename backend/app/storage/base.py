"""The provider-neutral interface every storage backend must implement."""

from __future__ import annotations

from abc import ABC, abstractmethod


class DocumentStorage(ABC):
    """Stores and retrieves raw file bytes by an opaque key.

    `key` is always an internally generated, safe identifier (see
    `app.documents.validation.generate_storage_key`) — never a
    client-supplied filename. Implementations must never interpret `key` as
    anything other than an opaque string when deciding where to store it.
    """

    @abstractmethod
    async def save(self, *, key: str, content: bytes) -> None:
        raise NotImplementedError

    @abstractmethod
    async def read(self, *, key: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, *, key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def exists(self, *, key: str) -> bool:
        raise NotImplementedError
