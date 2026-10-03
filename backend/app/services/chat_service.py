"""Chat orchestration.

This is the only layer the API is allowed to call into the LLM gateway
through — `api/v1/chat.py` must depend on `ChatService`, never on
`app.llm` directly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from app.llm.gateway import LLMGateway, get_llm_gateway
from app.llm.schemas import ChatMessage, ChatRole, CompletionResponse, ModelRole, StreamChunk


class ChatService:
    def __init__(self, gateway: LLMGateway) -> None:
        self._gateway = gateway

    async def complete(self, *, message: str, model_role: ModelRole) -> CompletionResponse:
        return await self._gateway.chat_completion(
            model_role=model_role,
            messages=[ChatMessage(role=ChatRole.USER, content=message)],
        )

    def stream(self, *, message: str, model_role: ModelRole) -> AsyncIterator[StreamChunk]:
        return self._gateway.stream_chat_completion(
            model_role=model_role,
            messages=[ChatMessage(role=ChatRole.USER, content=message)],
        )


@lru_cache
def get_chat_service() -> ChatService:
    return ChatService(get_llm_gateway())
