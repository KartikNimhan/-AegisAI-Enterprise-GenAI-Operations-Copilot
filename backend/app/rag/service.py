"""RAG orchestration: retrieve -> (no-context short-circuit) -> assemble
context -> build prompt -> generate -> attach sources.

This is the only layer allowed to combine retrieval with generation —
`api/v1/rag.py` must depend on `RAGService`, never on `RetrievalService`,
`ContextAssembler`, or `LLMGateway` directly. Mirrors
`app.services.chat_service.ChatService`'s shape and atomicity (one commit
per request, relying on `app.db.session.get_session`'s ambient
commit/rollback — see there for why) but adds the retrieval and
no-context steps chat doesn't have.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

import structlog
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import NotFoundError
from app.db.repositories.conversation_repository import ConversationRepository
from app.db.repositories.document_repository import DocumentRepository
from app.db.repositories.message_repository import MessageRepository
from app.dependencies import DBSessionDep
from app.domain.enums.message_role import MessageRole
from app.domain.models.conversation import Conversation
from app.llm.exceptions import LLMError
from app.llm.gateway import LLMGateway, get_llm_gateway
from app.llm.schemas import ModelRole, StreamChunk
from app.rag.context.assembler import AssembledSource, ContextAssembler
from app.rag.prompts.builder import RAGPromptBuilder
from app.rag.retrieval.service import RetrievalService, get_retrieval_service
from app.rag.schemas import RAGAnswer, RAGRetrievalMetadata, RAGSource

logger = structlog.get_logger(__name__)

_TITLE_MAX_LENGTH = 80
NO_CONTEXT_RESPONSE = (
    "I don't have enough information in the available documents to answer that question."
)


class RAGService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        retrieval: RetrievalService,
        context_assembler: ContextAssembler,
        prompt_builder: RAGPromptBuilder,
        gateway: LLMGateway,
        conversations: ConversationRepository,
        messages: MessageRepository,
        documents: DocumentRepository,
    ) -> None:
        self._session = session
        self._retrieval = retrieval
        self._context_assembler = context_assembler
        self._prompt_builder = prompt_builder
        self._gateway = gateway
        self._conversations = conversations
        self._messages = messages
        self._documents = documents

    async def answer(
        self,
        *,
        conversation_id: uuid.UUID | None,
        message: str,
        model_role: ModelRole,
        top_k: int | None = None,
        document_id: uuid.UUID | None = None,
    ) -> RAGAnswer:
        conversation = await self._get_or_create_conversation(conversation_id, message)
        await self._validate_document_filter(document_id)
        history = await self._messages.list_by_conversation(conversation.id)

        start = time.perf_counter()
        outcome = await self._retrieval.retrieve(
            query=message, top_k=top_k, document_id=document_id
        )

        await self._messages.add(
            conversation_id=conversation.id, role=MessageRole.USER, content=message
        )

        if not outcome.results:
            logger.info(
                "rag_no_context",
                conversation_id=str(conversation.id),
                candidates_found=len(outcome.candidates),
                top_k=outcome.top_k,
                similarity_threshold=outcome.similarity_threshold,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )
            await self._messages.add(
                conversation_id=conversation.id,
                role=MessageRole.ASSISTANT,
                content=NO_CONTEXT_RESPONSE,
            )
            await self._conversations.touch(conversation)
            return RAGAnswer(
                conversation_id=conversation.id,
                answer=NO_CONTEXT_RESPONSE,
                has_context=False,
                sources=[],
                retrieval=RAGRetrievalMetadata(
                    top_k=outcome.top_k,
                    similarity_threshold=outcome.similarity_threshold,
                    candidates_found=len(outcome.candidates),
                    chunks_used=0,
                    context_truncated=False,
                    embedding_provider=outcome.embedding_provider,
                    embedding_model=outcome.embedding_model,
                    embedding_model_version=outcome.embedding_model_version,
                ),
            )

        assembled = self._context_assembler.assemble(outcome.results)
        prompt = self._prompt_builder.build(
            context_text=assembled.text, question=message, history=history
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

        logger.info(
            "rag_answer_generated",
            conversation_id=str(conversation.id),
            candidates_found=len(outcome.candidates),
            chunks_used=len(assembled.sources),
            top_k=outcome.top_k,
            similarity_threshold=outcome.similarity_threshold,
            context_truncated=assembled.truncated,
            embedding_model=outcome.embedding_model,
            llm_model=completion.model,
            total_tokens=completion.usage.total_tokens,
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )

        return RAGAnswer(
            conversation_id=conversation.id,
            answer=completion.content,
            has_context=True,
            sources=[_to_rag_source(source) for source in assembled.sources],
            retrieval=RAGRetrievalMetadata(
                top_k=outcome.top_k,
                similarity_threshold=outcome.similarity_threshold,
                candidates_found=len(outcome.candidates),
                chunks_used=len(assembled.sources),
                context_truncated=assembled.truncated,
                embedding_provider=outcome.embedding_provider,
                embedding_model=outcome.embedding_model,
                embedding_model_version=outcome.embedding_model_version,
            ),
            model=completion.model,
            provider=completion.provider,
            usage=completion.usage,
            finish_reason=completion.finish_reason,
            request_id=completion.request_id,
        )

    async def answer_stream(
        self,
        *,
        conversation_id: uuid.UUID | None,
        message: str,
        model_role: ModelRole,
        top_k: int | None = None,
        document_id: uuid.UUID | None = None,
    ) -> AsyncIterator[tuple[uuid.UUID, StreamChunk, list[RAGSource] | None]]:
        """Yields `(conversation_id, chunk, sources)` — `sources` is `None`
        on every chunk except the final one, mirroring how `StreamChunk.usage`
        is only populated on the final chunk. Sources come from retrieval,
        never from the LLM — the model is never asked to produce them.
        """
        conversation = await self._get_or_create_conversation(conversation_id, message)
        await self._validate_document_filter(document_id)
        history = await self._messages.list_by_conversation(conversation.id)

        outcome = await self._retrieval.retrieve(
            query=message, top_k=top_k, document_id=document_id
        )

        await self._messages.add(
            conversation_id=conversation.id, role=MessageRole.USER, content=message
        )

        if not outcome.results:
            logger.info(
                "rag_no_context",
                conversation_id=str(conversation.id),
                candidates_found=len(outcome.candidates),
                top_k=outcome.top_k,
                similarity_threshold=outcome.similarity_threshold,
            )
            await self._messages.add(
                conversation_id=conversation.id,
                role=MessageRole.ASSISTANT,
                content=NO_CONTEXT_RESPONSE,
            )
            await self._conversations.touch(conversation)
            yield (
                conversation.id,
                StreamChunk(delta=NO_CONTEXT_RESPONSE, is_final=True),
                [],
            )
            return

        assembled = self._context_assembler.assemble(outcome.results)
        prompt = self._prompt_builder.build(
            context_text=assembled.text, question=message, history=history
        )
        sources = [_to_rag_source(source) for source in assembled.sources]

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
                yield (
                    conversation.id,
                    chunk,
                    sources if chunk.is_final else None,
                )
        except LLMError:
            # Mirrors ChatService.stream_message: the API layer catches
            # LLMError to emit a clean terminal SSE event instead of
            # propagating, so the ambient session rollback (which only
            # fires on an exception reaching app.db.session.get_session)
            # never runs — roll back explicitly so the flushed user
            # message isn't persisted without a reply.
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

    async def _validate_document_filter(self, document_id: uuid.UUID | None) -> None:
        if document_id is None:
            return
        document = await self._documents.get(document_id)
        if document is None:
            raise NotFoundError(f"Document {document_id} not found")


def _derive_title(message: str) -> str:
    stripped = message.strip()
    if len(stripped) <= _TITLE_MAX_LENGTH:
        return stripped
    return stripped[: _TITLE_MAX_LENGTH - 1].rstrip() + "…"


def _to_rag_source(source: AssembledSource) -> RAGSource:
    return RAGSource(
        source_id=source.source_id,
        chunk_id=source.chunk_id,
        document_id=source.document_id,
        filename=source.filename,
        chunk_index=source.chunk_index,
        page_number=source.page_number,
        similarity=source.similarity,
    )


def get_rag_service(
    session: DBSessionDep,
    gateway: Annotated[LLMGateway, Depends(get_llm_gateway)],
    retrieval: Annotated[RetrievalService, Depends(get_retrieval_service)],
) -> RAGService:
    settings = get_settings()
    return RAGService(
        session=session,
        retrieval=retrieval,
        context_assembler=ContextAssembler(max_context_chars=settings.rag_max_context_chars),
        prompt_builder=RAGPromptBuilder(),
        gateway=gateway,
        conversations=ConversationRepository(session),
        messages=MessageRepository(session),
        documents=DocumentRepository(session),
    )
