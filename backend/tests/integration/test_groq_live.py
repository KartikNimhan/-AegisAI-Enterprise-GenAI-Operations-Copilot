"""Opt-in integration test against the real Groq API.

Skips automatically when GROQ_API_KEY is not set in the environment — a
real key is never required for a normal `pytest` run. Uses the FAST model
role (small/cheap model) to keep this quick when it does run.

Run explicitly with a real key via:
    GROQ_API_KEY=sk-... uv run pytest -m llm_integration -v
"""

from __future__ import annotations

import os

import pytest

from app.config import get_settings
from app.llm.gateway import LLMGateway
from app.llm.schemas import ChatMessage, ChatRole, ModelRole

pytestmark = [
    pytest.mark.llm_integration,
    pytest.mark.skipif(
        not os.environ.get("GROQ_API_KEY"),
        reason="GROQ_API_KEY is not set — skipping real Groq API test",
    ),
]

# The FAST model is a reasoning model: its hidden reasoning counts against `max_tokens` before any
# visible text, and a 20-token budget was spent entirely on reasoning (empty content,
# finish_reason "length"). This leaves room for both while keeping each call bounded.
_MAX_TOKENS = 512


async def test_real_groq_chat_completion_returns_content() -> None:
    gateway = LLMGateway(get_settings())

    result = await gateway.chat_completion(
        model_role=ModelRole.FAST,
        messages=[ChatMessage(role=ChatRole.USER, content="Reply with exactly one word: pong")],
        max_tokens=_MAX_TOKENS,
    )

    assert result.content.strip() != ""
    assert result.provider == "groq"
    assert result.model == get_settings().fast_llm_model
    assert result.usage.total_tokens is not None and result.usage.total_tokens > 0


async def test_real_groq_streaming_yields_chunks() -> None:
    gateway = LLMGateway(get_settings())

    chunks = [
        chunk
        async for chunk in gateway.stream_chat_completion(
            model_role=ModelRole.FAST,
            messages=[ChatMessage(role=ChatRole.USER, content="Count from 1 to 3.")],
            max_tokens=_MAX_TOKENS,
        )
    ]

    assert len(chunks) > 0
    full_text = "".join(chunk.delta for chunk in chunks)
    assert full_text.strip() != ""
    assert chunks[-1].is_final is True
    # Groq reports stream usage on the final chunk (`x_groq.usage`; no `stream_options` is sent).
    final_usage = chunks[-1].usage
    assert final_usage is not None
    assert final_usage.total_tokens is not None and final_usage.total_tokens > 0
