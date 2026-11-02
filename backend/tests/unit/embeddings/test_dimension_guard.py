"""The configured embedding dimension must equal what the vector column stores (at startup)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI

from app.config import Settings
from app.domain.models.chunk_embedding import EMBEDDING_DIMENSION, ChunkEmbedding
from app.main import create_app


def settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, debug=True, environment="local", **overrides)  # type: ignore[call-arg,arg-type]


def test_the_schema_constant_matches_the_actual_column() -> None:
    assert ChunkEmbedding.__table__.c.embedding.type.dim == EMBEDDING_DIMENSION  # type: ignore[attr-defined]


def test_the_default_configuration_matches_the_schema() -> None:
    assert settings().embedding_dimension == EMBEDDING_DIMENSION
    assert isinstance(create_app(settings()), FastAPI)


@pytest.mark.parametrize("dimension", [128, 768, 1536, EMBEDDING_DIMENSION + 1])
def test_a_mismatched_dimension_refuses_to_start_with_a_clear_message(dimension: int) -> None:
    with pytest.raises(ValueError, match="EMBEDDING_DIMENSION") as raised:
        create_app(settings(embedding_dimension=dimension))

    assert str(EMBEDDING_DIMENSION) in str(raised.value)
    assert "migration" in str(raised.value)
