"""Request/response schemas for the agent-memory endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums.memory_kind import MemoryKind, MemorySource


class MemoryCreateRequest(BaseModel):
    # The configured per-item limit (AGENT_MEMORY_MAX_ITEM_CHARS) is enforced by the service.
    content: str = Field(min_length=1, max_length=2000)
    kind: MemoryKind = MemoryKind.FACT


class MemoryUpdateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class MemoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: MemoryKind
    source: MemorySource
    content: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime


class MemoryClearResponse(BaseModel):
    deleted: int
