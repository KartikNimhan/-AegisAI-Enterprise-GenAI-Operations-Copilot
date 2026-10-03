"""Local filesystem storage — the only backend implemented in this milestone.

File I/O is blocking; each call is offloaded via `asyncio.to_thread` rather
than pulling in an extra async-file-IO dependency, so it doesn't block the
event loop. Uploaded files for this project are small enough (see
`Settings.document_max_upload_size_bytes`) that this is not a bottleneck
in practice — see docs/architecture/decisions/005-document-ingestion.md
for the synchronous-processing tradeoff this is part of.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache
from pathlib import Path

from app.config import get_settings
from app.storage.base import DocumentStorage


class LocalFileStorage(DocumentStorage):
    def __init__(self, root_dir: str | Path) -> None:
        self._root = Path(root_dir).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        """Resolves `key` under the storage root, rejecting any attempt to
        escape it. Defense in depth: `key` is always internally generated
        (never client input) by the time it reaches here, but a storage
        backend should never trust its caller blindly either.
        """
        candidate = (self._root / key).resolve()
        if not candidate.is_relative_to(self._root):
            raise ValueError(f"Storage key escapes the storage root: {key!r}")
        return candidate

    async def save(self, *, key: str, content: bytes) -> None:
        path = self._resolve(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

        await asyncio.to_thread(_write)

    async def read(self, *, key: str) -> bytes:
        path = self._resolve(key)
        return await asyncio.to_thread(path.read_bytes)

    async def delete(self, *, key: str) -> None:
        path = self._resolve(key)

        def _delete() -> None:
            path.unlink(missing_ok=True)

        await asyncio.to_thread(_delete)

    async def exists(self, *, key: str) -> bool:
        path = self._resolve(key)
        return await asyncio.to_thread(path.is_file)


@lru_cache
def get_document_storage() -> DocumentStorage:
    return LocalFileStorage(get_settings().document_storage_dir)
