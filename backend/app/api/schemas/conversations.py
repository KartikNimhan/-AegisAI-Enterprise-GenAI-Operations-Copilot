"""Request/response schemas for the conversation endpoints.

Built from, but distinct from, `app.domain.models` — routes must never
return ORM objects directly.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.citations import MessageCitationSummary
from app.domain.enums.message_role import MessageRole


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: MessageRole
    content: str
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    created_at: datetime
    # M10.4 T5: the sources this answer was grounded in, resolved against the caller's CURRENT
    # access. Empty for user messages, answers without sources and messages saved before M10.4.
    citations: list[MessageCitationSummary] = Field(default_factory=list)


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None = None
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationSummary):
    messages: list[MessageResponse] = []
