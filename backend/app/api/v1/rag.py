"""RAG chat endpoints.

Kept thin: all orchestration (retrieval, context assembly, prompt
construction, generation, persistence) lives in
`app.rag.service.RAGService`. This module must never import
`app.rag.retrieval`, `app.rag.context`, `app.llm`, or `app.db.repositories`
directly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.schemas.chat import ChatCompletionStreamError, ChatCompletionStreamErrorDetail
from app.api.schemas.rag import (
    RAGChatRequest,
    RAGChatResponse,
    RAGChatStreamChunk,
    RAGSourceResponse,
)
from app.llm.exceptions import LLMError
from app.rag.service import RAGService, get_rag_service

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/rag", tags=["rag"])

RAGServiceDep = Annotated[RAGService, Depends(get_rag_service)]


@router.post("/chat", response_model=RAGChatResponse)
async def rag_chat(request: RAGChatRequest, rag_service: RAGServiceDep) -> RAGChatResponse:
    result = await rag_service.answer(
        conversation_id=request.conversation_id,
        message=request.message,
        model_role=request.model_role,
        top_k=request.top_k,
        document_id=request.document_id,
    )
    return RAGChatResponse.from_answer(result)


@router.post("/chat/stream")
async def rag_chat_stream(request: RAGChatRequest, rag_service: RAGServiceDep) -> StreamingResponse:
    async def event_source() -> AsyncIterator[str]:
        try:
            async for conversation_id, chunk, sources in rag_service.answer_stream(
                conversation_id=request.conversation_id,
                message=request.message,
                model_role=request.model_role,
                top_k=request.top_k,
                document_id=request.document_id,
            ):
                event = RAGChatStreamChunk(
                    conversation_id=conversation_id,
                    sources=(
                        [RAGSourceResponse.from_source(s) for s in sources]
                        if sources is not None
                        else None
                    ),
                    **chunk.model_dump(),
                )
                yield f"data: {event.model_dump_json()}\n\n"
            yield "data: [DONE]\n\n"
        except LLMError as exc:
            # Same reasoning as api/v1/chat.py: headers/status are already
            # committed once streaming starts, so a mid-stream failure
            # becomes a terminal SSE event, not an HTTP error status.
            logger.warning("rag_stream_error_event", error_type=type(exc).__name__)
            error_event = ChatCompletionStreamError(
                error=ChatCompletionStreamErrorDetail(code=type(exc).__name__, message=str(exc))
            )
            yield f"data: {error_event.model_dump_json()}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")
