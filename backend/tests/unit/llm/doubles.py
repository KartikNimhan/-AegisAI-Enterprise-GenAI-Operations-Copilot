"""Test doubles shared across LLM gateway unit tests.

Not a test module itself (no `test_*` functions), so pytest won't collect it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.llm.base import LLMProvider
from app.llm.schemas import CompletionResponse, StreamChunk


class ScriptedProvider(LLMProvider):
    """A fake `LLMProvider` whose behavior is scripted call-by-call.

    Each item in `effects` is either an `Exception` to raise, a
    `CompletionResponse` to return from `complete`, or a `list[StreamChunk]`
    to yield from `stream_complete`.
    """

    name = "fake"

    def __init__(self, effects: list[Any]) -> None:
        self._effects = list(effects)
        self.calls: list[dict[str, Any]] = []

    async def complete(self, **kwargs: Any) -> CompletionResponse:
        self.calls.append(kwargs)
        effect = self._effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        assert isinstance(effect, CompletionResponse)
        return effect

    async def stream_complete(self, **kwargs: Any) -> AsyncIterator[StreamChunk]:
        self.calls.append(kwargs)
        effect = self._effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        assert isinstance(effect, list)
        for chunk in effect:
            yield chunk
