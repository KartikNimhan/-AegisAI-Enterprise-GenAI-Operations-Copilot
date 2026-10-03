"""The provider-neutral interface every embedding provider must implement."""

from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """Turns text into vectors. Implementations own all model-specific
    logic (loading, batching mechanics, device placement) — callers only
    ever see `embed_texts` and the identifying properties below.

    `name`, `model_name`, `model_version`, and `dimension` are what
    `EmbeddingService` stamps onto every persisted `ChunkEmbedding` row —
    they must be stable for a given provider instance's lifetime.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """A short provider identifier, e.g. "local"."""
        raise NotImplementedError

    @property
    @abstractmethod
    def model_name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def model_version(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def dimension(self) -> int:
        raise NotImplementedError

    @abstractmethod
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embeds a batch of texts, returning one vector per input text in
        the same order. Must raise `EmbeddingDimensionMismatchError` rather
        than return a vector of the wrong length, and
        `EmbeddingProviderError` (never a raw provider/library exception)
        on any other failure.
        """
        raise NotImplementedError

    async def embed_text(self, text: str) -> list[float]:
        """Convenience wrapper for a single text. Prefer `embed_texts` for
        more than one input — batching is what makes local inference
        practical."""
        return (await self.embed_texts([text]))[0]
