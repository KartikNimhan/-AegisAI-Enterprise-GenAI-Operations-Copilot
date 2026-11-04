"""Conversation endpoints: list, retrieve (with ordered messages), delete.

Kept thin: all persistence lives behind
`app.services.conversation_service.ConversationService`. Never returns ORM
objects directly — always maps to `app.api.schemas.conversations` models.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from app.api.schemas.citations import (
    CitationResponse,
    MessageCitationSummary,
    citation_response,
)
from app.api.schemas.conversations import ConversationDetail, ConversationSummary, MessageResponse
from app.core import audit
from app.core.security import PrincipalDep
from app.services.citation_service import MAX_NEIGHBORS, CitationServiceDep
from app.services.conversation_service import ConversationService, get_conversation_service

router = APIRouter(prefix="/conversations", tags=["conversations"])

ConversationServiceDep = Annotated[ConversationService, Depends(get_conversation_service)]


@router.get("", response_model=list[ConversationSummary])
async def list_conversations(
    conversation_service: ConversationServiceDep,
) -> list[ConversationSummary]:
    conversations = await conversation_service.list_conversations()
    return [ConversationSummary.model_validate(c) for c in conversations]


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID,
    conversation_service: ConversationServiceDep,
    citation_service: CitationServiceDep,
) -> ConversationDetail:
    conversation = await conversation_service.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    citations = await citation_service.for_conversation(conversation_id)
    detail = ConversationDetail.model_validate(conversation)
    detail.messages = [
        MessageResponse.model_validate(message).model_copy(
            update={
                "citations": [
                    MessageCitationSummary.from_view(view) for view in citations.get(message.id, [])
                ]
            }
        )
        for message in conversation.messages
    ]
    return detail


# The `S1`..`S999` ids the answer text uses (see app.domain.models.message_citation).
SourceIdPath = Annotated[str, Path(pattern=r"^S[1-9][0-9]{0,2}$", max_length=4)]


@router.get(
    "/{conversation_id}/messages/{message_id}/citations/{source_id}",
    response_model=CitationResponse,
)
async def get_citation(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    source_id: SourceIdPath,
    citation_service: CitationServiceDep,
    neighbors: Annotated[int, Query(ge=0, le=MAX_NEIGHBORS)] = 0,
) -> CitationResponse:
    """One source of a saved answer, checked against the caller's CURRENT access (M10.4 T6).
    A conversation, message or source id that is not the caller's is 404, like any other
    resource. A source the caller can no longer read is 200 with `status: "unavailable"` and no
    source details (decision 3)."""
    view = await citation_service.get(
        conversation_id=conversation_id,
        message_id=message_id,
        source_id=source_id,
        neighbors=neighbors,
    )
    return citation_response(view, neighbors_requested=neighbors > 0)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID,
    conversation_service: ConversationServiceDep,
    principal: PrincipalDep,
) -> None:
    deleted = await conversation_service.delete_conversation(conversation_id)
    audit.record(
        "conversation.deleted",
        actor=principal,
        resource_type="conversation",
        resource_id=conversation_id,
        outcome="success" if deleted else "not_found",
    )
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Conversation not found")
