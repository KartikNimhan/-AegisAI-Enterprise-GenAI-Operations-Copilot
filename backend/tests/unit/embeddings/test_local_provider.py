"""Unit tests for LocalEmbeddingProvider.

Never downloads or loads the real Sentence Transformers model — `_get_model`
is monkeypatched to return a fake with a scripted `.encode()`. The opt-in
integration test (tests/integration/test_embedding_model_live.py) covers
the real model.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from app.config import Settings
from app.embeddings.exceptions import (
    EmbeddingDimensionMismatchError,
    EmbeddingProviderError,
    EmptyInputError,
)
from app.embeddings.providers.local import LocalEmbeddingProvider, get_local_embedding_provider


def make_settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = {
        "embedding_provider": "local",
        "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
        "embedding_model_version": "1",
        "embedding_dimension": 384,
        "embedding_normalize": True,
    }
    defaults.update(overrides)
    return Settings(**defaults)


class FakeModel:
    def __init__(self, *, vectors: list[list[float]] | None = None, error: Exception | None = None):
        self._vectors = vectors
        self._error = error
        self.encode_calls: list[dict[str, Any]] = []

    def encode(self, texts: list[str], **kwargs: Any) -> Any:
        self.encode_calls.append({"texts": texts, **kwargs})
        if self._error is not None:
            raise self._error
        vectors = self._vectors if self._vectors is not None else [[0.1] * 384 for _ in texts]
        return np.array(vectors)


def make_provider(settings: Settings | None = None) -> LocalEmbeddingProvider:
    return LocalEmbeddingProvider(settings or make_settings())


async def test_properties_reflect_settings() -> None:
    settings = make_settings(
        embedding_provider="local",
        embedding_model="sentence-transformers/all-MiniLM-L6-v2",
        embedding_model_version="2",
        embedding_dimension=384,
    )
    provider = make_provider(settings)

    assert provider.name == "local"
    assert provider.model_name == "sentence-transformers/all-MiniLM-L6-v2"
    assert provider.model_version == "2"
    assert provider.dimension == 384


async def test_embed_texts_returns_one_vector_per_text_in_order() -> None:
    provider = make_provider()
    fake_model = FakeModel(vectors=[[0.1] * 384, [0.2] * 384])
    provider._get_model = lambda: fake_model  # type: ignore[method-assign]

    vectors = await provider.embed_texts(["first", "second"])

    assert len(vectors) == 2
    assert vectors[0] == pytest.approx([0.1] * 384)
    assert vectors[1] == pytest.approx([0.2] * 384)
    assert fake_model.encode_calls[0]["texts"] == ["first", "second"]
    assert fake_model.encode_calls[0]["normalize_embeddings"] is True


async def test_embed_text_single_convenience_wrapper() -> None:
    provider = make_provider()
    fake_model = FakeModel(vectors=[[0.3] * 384])
    provider._get_model = lambda: fake_model  # type: ignore[method-assign]

    vector = await provider.embed_text("only one")

    assert vector == pytest.approx([0.3] * 384)


async def test_embed_texts_raises_on_empty_list() -> None:
    provider = make_provider()

    with pytest.raises(EmptyInputError):
        await provider.embed_texts([])


async def test_embed_texts_raises_on_whitespace_only_text_in_batch() -> None:
    provider = make_provider()

    with pytest.raises(EmptyInputError):
        await provider.embed_texts(["valid text", "   "])


async def test_embed_texts_raises_dimension_mismatch_when_model_returns_wrong_length() -> None:
    provider = make_provider(make_settings(embedding_dimension=384))
    fake_model = FakeModel(vectors=[[0.1] * 100])  # wrong dimension
    provider._get_model = lambda: fake_model  # type: ignore[method-assign]

    with pytest.raises(EmbeddingDimensionMismatchError):
        await provider.embed_texts(["text"])


async def test_embed_texts_wraps_encode_failure_as_provider_error() -> None:
    provider = make_provider()
    fake_model = FakeModel(error=RuntimeError("inference blew up"))
    provider._get_model = lambda: fake_model  # type: ignore[method-assign]

    with pytest.raises(EmbeddingProviderError):
        await provider.embed_texts(["text"])


async def test_model_load_failure_raises_provider_error() -> None:
    provider = make_provider()

    def _raise_load_error() -> Any:
        raise EmbeddingProviderError("Could not load embedding model 'x': boom")

    provider._get_model = _raise_load_error  # type: ignore[method-assign]

    with pytest.raises(EmbeddingProviderError):
        await provider.embed_texts(["text"])


def test_get_local_embedding_provider_returns_a_cached_singleton() -> None:
    get_local_embedding_provider.cache_clear()
    try:
        first = get_local_embedding_provider()
        second = get_local_embedding_provider()
        assert first is second
    finally:
        get_local_embedding_provider.cache_clear()
