"""Local embedding inference via Sentence Transformers.

This is the only module in the codebase allowed to import
`sentence_transformers`. The model is loaded lazily (on first use, not at
import/construction time) for the same reason `GroqProvider` builds its
client lazily (Milestone 1): constructing an `EmbeddingService` — and thus
the app starting up — must not require downloading/loading a ~90MB model
or depend on it being available.

Model loading and `.encode()` are both blocking, CPU-bound calls; both are
offloaded via `asyncio.to_thread` so they don't block the event loop,
consistent with how `app.documents.extractors`/`chunking` are called from
`DocumentService` in Milestone 3.
"""

from __future__ import annotations

import asyncio
import threading
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from app.config import Settings, get_settings
from app.embeddings.base import EmbeddingProvider
from app.embeddings.exceptions import (
    EmbeddingDimensionMismatchError,
    EmbeddingProviderError,
    EmptyInputError,
)

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


class LocalEmbeddingProvider(EmbeddingProvider):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model: SentenceTransformer | None = None
        # Guards lazy model construction against a race if two requests
        # both trigger the first embed_texts call concurrently.
        self._load_lock = threading.Lock()

    @property
    def name(self) -> str:
        return self._settings.embedding_provider

    @property
    def model_name(self) -> str:
        return self._settings.embedding_model

    @property
    def model_version(self) -> str:
        return self._settings.embedding_model_version

    @property
    def dimension(self) -> int:
        return self._settings.embedding_dimension

    def _get_model(self) -> SentenceTransformer:
        if self._model is None:
            with self._load_lock:
                if self._model is None:  # re-check: another thread may have won the race
                    try:
                        from sentence_transformers import SentenceTransformer

                        self._model = SentenceTransformer(
                            self._settings.embedding_model,
                            device=self._settings.embedding_device,
                        )
                    except Exception as exc:
                        raise EmbeddingProviderError(
                            f"Could not load embedding model "
                            f"{self._settings.embedding_model!r}: {exc}"
                        ) from exc
        return self._model

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            raise EmptyInputError("No texts provided to embed")
        if any(not text.strip() for text in texts):
            raise EmptyInputError("Cannot embed an empty or whitespace-only text")

        vectors = await asyncio.to_thread(self._encode, texts)

        for vector in vectors:
            if len(vector) != self.dimension:
                raise EmbeddingDimensionMismatchError(
                    f"Model {self.model_name!r} returned a vector of length "
                    f"{len(vector)}, expected {self.dimension}"
                )
        return vectors

    def _encode(self, texts: list[str]) -> list[list[float]]:
        model = self._get_model()
        try:
            embeddings: Any = model.encode(
                texts,
                normalize_embeddings=self._settings.embedding_normalize,
                convert_to_numpy=True,
            )
        except Exception as exc:
            raise EmbeddingProviderError(f"Embedding inference failed: {exc}") from exc
        return [vector.tolist() for vector in embeddings]


@lru_cache
def get_local_embedding_provider() -> LocalEmbeddingProvider:
    """One provider instance (and thus one lazily-loaded model) per
    process — loading the model is the expensive part; reusing it across
    requests is the whole point."""
    return LocalEmbeddingProvider(get_settings())
