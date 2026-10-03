"""Chat completion endpoints.

Kept thin: all orchestration (conversation lifecycle, prompt construction,
persistence) lives in `app.services.chat_service.ChatService`. The
dependency chain is API -> ChatService -> PromptBuilder/repositories ->
LLMGateway -> GroqProvider; this module must never import
`app.llm.providers`, `app.db.repositories`, or a provider SDK.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.schemas.chat import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionStreamChunk,
    ChatCompletionStreamError,
    ChatCompletionStreamErrorDetail,
)
from app.llm.exceptions import LLMError
from app.services.chat_service import ChatService, get_chat_service

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]


@router.post("/completions", response_model=ChatCompletionResponse)
async def create_chat_completion(
    request: ChatCompletionRequest, chat_service: ChatServiceDep
) -> ChatCompletionResponse:
    result = await chat_service.send_message(
        conversation_id=request.conversation_id,
        message=request.message,
        model_role=request.model_role,
    )
    return ChatCompletionResponse(
        conversation_id=result.conversation_id, **result.response.model_dump()
    )


@router.post("/completions/stream")
async def stream_chat_completion(
    request: ChatCompletionRequest, chat_service: ChatServiceDep
) -> StreamingResponse:
    async def event_source() -> AsyncIterator[str]:
        try:
            async for turn_chunk in chat_service.stream_message(
                conversation_id=request.conversation_id,
                message=request.message,
                model_role=request.model_role,
            ):
                event = ChatCompletionStreamChunk(
                    conversation_id=turn_chunk.conversation_id,
                    **turn_chunk.chunk.model_dump(),
                )
                yield f"data: {event.model_dump_json()}\n\n"
            yield "data: [DONE]\n\n"
        except LLMError as exc:
            # The HTTP status/headers are already committed once streaming
            # starts, so a mid-stream failure can't become a 4xx/5xx — emit
            # a terminal SSE error event instead of raising (which would
            # just truncate the connection). ChatService has already rolled
            # back any partial persistence for this turn before this is
            # reached, so letting this generator finish normally here is
            # safe: the request-scoped session will commit a no-op.
            logger.warning("llm_stream_error_event", error_type=type(exc).__name__)
            error_event = ChatCompletionStreamError(
                error=ChatCompletionStreamErrorDetail(code=type(exc).__name__, message=str(exc))
            )
            yield f"data: {error_event.model_dump_json()}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")
