"""Agent endpoints.

Kept thin: all orchestration (LangGraph execution, tool calling,
persistence) lives in `app.agents.service.AgentService`. This module must
never import `app.agents.graph`, `app.agents.tools`, `app.llm`, or
`app.db.repositories` directly.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.agents.exceptions import AgentTimeoutError
from app.agents.service import AgentService, get_agent_service
from app.api.schemas.agents import AgentRunRequest, AgentRunResponse
from app.api.schemas.chat import ChatCompletionStreamError, ChatCompletionStreamErrorDetail
from app.llm.exceptions import LLMError

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])

AgentServiceDep = Annotated[AgentService, Depends(get_agent_service)]


@router.post("/run", response_model=AgentRunResponse)
async def run_agent(request: AgentRunRequest, agent_service: AgentServiceDep) -> AgentRunResponse:
    result = await agent_service.run(
        conversation_id=request.conversation_id,
        message=request.message,
        model_role=request.model_role,
    )
    return AgentRunResponse.from_result(result)


@router.post("/run/stream")
async def run_agent_stream(
    request: AgentRunRequest, agent_service: AgentServiceDep
) -> StreamingResponse:
    async def event_source() -> AsyncIterator[str]:
        try:
            async for _conversation_id, event in agent_service.run_stream(
                conversation_id=request.conversation_id,
                message=request.message,
                model_role=request.model_role,
            ):
                yield f"event: {event.event}\ndata: {json.dumps(event.data, default=str)}\n\n"
        except (LLMError, AgentTimeoutError) as exc:
            # Same reasoning as api/v1/chat.py and api/v1/rag.py: headers
            # are already committed once streaming starts, so a mid-stream
            # failure becomes a terminal SSE event, not an HTTP error status.
            logger.warning("agent_stream_error_event", error_type=type(exc).__name__)
            error_event = ChatCompletionStreamError(
                error=ChatCompletionStreamErrorDetail(code=type(exc).__name__, message=str(exc))
            )
            yield f"event: error\ndata: {error_event.model_dump_json()}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")
