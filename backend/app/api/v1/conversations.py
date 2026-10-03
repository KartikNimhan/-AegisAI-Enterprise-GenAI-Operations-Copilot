"""Conversation endpoints: list, retrieve (with ordered messages), delete.

Kept thin: all persistence lives behind
`app.services.conversation_service.ConversationService`. Never returns ORM
objects directly — always maps to `app.api.schemas.conversations` models.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.schemas.conversations import ConversationDetail, ConversationSummary
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
    conversation_id: uuid.UUID, conversation_service: ConversationServiceDep
) -> ConversationDetail:
    conversation = await conversation_service.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return ConversationDetail.model_validate(conversation)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID, conversation_service: ConversationServiceDep
) -> None:
    deleted = await conversation_service.delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Conversation not found")
