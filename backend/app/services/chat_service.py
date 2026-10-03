"""Chat orchestration.

This is the only layer the API is allowed to call into the LLM gateway and
conversation persistence through — `api/v1/chat.py` must depend on
`ChatService`, never on `app.llm` or `app.db.repositories` directly.

Flow: resolve/create the conversation -> load prior messages -> build the
prompt (system + history + new user message) via `PromptBuilder` -> call
`LLMGateway` -> persist both turns -> return a normalized result.

A chat turn is atomic: the user message and the assistant's reply are
persisted together, in the same database transaction. If the LLM call
fails, nothing is persisted for that turn (see `stream_message`'s explicit
rollback below, and `app.db.session.get_session` for the non-streaming
path, which rolls back automatically on any exception). This avoids
leaving an orphaned user message with no reply in conversation history —
the client can simply retry.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.repositories.conversation_repository import ConversationRepository
from app.db.repositories.message_repository import MessageRepository
from app.dependencies import DBSessionDep
from app.domain.enums.message_role import MessageRole
from app.domain.models.conversation import Conversation
from app.llm.exceptions import LLMError
from app.llm.gateway import LLMGateway, get_llm_gateway
from app.llm.schemas import CompletionResponse, ModelRole, StreamChunk
from app.prompts.builder import PromptBuilder

_TITLE_MAX_LENGTH = 80


@dataclass(frozen=True)
class ChatTurnResult:
    conversation_id: uuid.UUID
    response: CompletionResponse


@dataclass(frozen=True)
class StreamTurnChunk:
    conversation_id: uuid.UUID
    chunk: StreamChunk


class ChatService:
    def __init__(
        self,
        *,
        gateway: LLMGateway,
        session: AsyncSession,
        conversations: ConversationRepository,
        messages: MessageRepository,
        prompt_builder: PromptBuilder | None = None,
    ) -> None:
        self._gateway = gateway
        self._session = session
        self._conversations = conversations
        self._messages = messages
        self._prompt_builder = prompt_builder or PromptBuilder()

    async def send_message(
        self,
        *,
        conversation_id: uuid.UUID | None,
        message: str,
        model_role: ModelRole,
    ) -> ChatTurnResult:
        conversation = await self._get_or_create_conversation(conversation_id, message)
        history = await self._messages.list_by_conversation(conversation.id)
        prompt = self._prompt_builder.build(history=history, user_message=message)

        await self._messages.add(
            conversation_id=conversation.id, role=MessageRole.USER, content=message
        )

        completion = await self._gateway.chat_completion(model_role=model_role, messages=prompt)

        await self._messages.add(
            conversation_id=conversation.id,
            role=MessageRole.ASSISTANT,
            content=completion.content,
            model=completion.model,
            provider=completion.provider,
            finish_reason=completion.finish_reason,
            request_id=completion.request_id,
            input_tokens=completion.usage.input_tokens,
            output_tokens=completion.usage.output_tokens,
            total_tokens=completion.usage.total_tokens,
        )
        await self._conversations.touch(conversation)

        return ChatTurnResult(conversation_id=conversation.id, response=completion)

    async def stream_message(
        self,
        *,
        conversation_id: uuid.UUID | None,
        message: str,
        model_role: ModelRole,
    ) -> AsyncIterator[StreamTurnChunk]:
        conversation = await self._get_or_create_conversation(conversation_id, message)
        history = await self._messages.list_by_conversation(conversation.id)
        prompt = self._prompt_builder.build(history=history, user_message=message)

        await self._messages.add(
            conversation_id=conversation.id, role=MessageRole.USER, content=message
        )

        accumulated_content = ""
        final_model: str | None = None
        finish_reason: str | None = None
        request_id: str | None = None
        input_tokens: int | None = None
        output_tokens: int | None = None
        total_tokens: int | None = None

        try:
            async for chunk in self._gateway.stream_chat_completion(
                model_role=model_role, messages=prompt
            ):
                accumulated_content += chunk.delta
                final_model = chunk.model or final_model
                request_id = chunk.request_id or request_id
                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason
                if chunk.usage is not None:
                    input_tokens = chunk.usage.input_tokens
                    output_tokens = chunk.usage.output_tokens
                    total_tokens = chunk.usage.total_tokens
                yield StreamTurnChunk(conversation_id=conversation.id, chunk=chunk)
        except LLMError:
            # Keep the turn atomic. The API layer (api/v1/chat.py) catches
            # this to emit a clean terminal SSE error event instead of
            # re-raising, which means the request-scoped session (see
            # app.db.session.get_session) will see no exception and commit
            # — so without this explicit rollback, the user message flushed
            # above would be persisted despite the assistant never replying.
            await self._session.rollback()
            raise

        await self._messages.add(
            conversation_id=conversation.id,
            role=MessageRole.ASSISTANT,
            content=accumulated_content,
            model=final_model,
            provider=self._gateway.model_metadata().get("provider"),
            finish_reason=finish_reason,
            request_id=request_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )
        await self._conversations.touch(conversation)

    async def _get_or_create_conversation(
        self, conversation_id: uuid.UUID | None, first_message: str
    ) -> Conversation:
        if conversation_id is None:
            return await self._conversations.create(title=_derive_title(first_message))
        conversation = await self._conversations.get(conversation_id)
        if conversation is None:
            raise NotFoundError(f"Conversation {conversation_id} not found")
        return conversation


def _derive_title(message: str) -> str:
    stripped = message.strip()
    if len(stripped) <= _TITLE_MAX_LENGTH:
        return stripped
    return stripped[: _TITLE_MAX_LENGTH - 1].rstrip() + "…"


def get_chat_service(
    session: DBSessionDep,
    gateway: Annotated[LLMGateway, Depends(get_llm_gateway)],
) -> ChatService:
    return ChatService(
        gateway=gateway,
        session=session,
        conversations=ConversationRepository(session),
        messages=MessageRepository(session),
    )
