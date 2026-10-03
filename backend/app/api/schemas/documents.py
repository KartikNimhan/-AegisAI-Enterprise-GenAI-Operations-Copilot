"""Request/response schemas for the document ingestion endpoints.

Built from, but distinct from, `app.domain.models` — routes never return
ORM objects or raw filesystem paths directly. Built via explicit
`from_document`/`from_chunk` constructors rather than
`model_validate(..., from_attributes=True)`: both `Document` and
`DocumentChunk` store their JSON column as a Python attribute named
`metadata_` (trailing underscore — `metadata` is reserved on SQLAlchemy's
declarative base), and `Document.filename` is the internal storage key, not
the client-facing name. Blind attribute auto-mapping would silently return
`None` for metadata and leak the internal key as "filename".
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.domain.enums.document_status import DocumentStatus
from app.domain.enums.document_type import DocumentType
from app.domain.models.document import Document
from app.domain.models.document_chunk import DocumentChunk


class DocumentResponse(BaseModel):
    id: uuid.UUID
    filename: str
    content_type: str
    document_type: DocumentType
    file_size: int
    checksum: str
    status: DocumentStatus
    error_message: str | None = None
    page_count: int | None = None
    character_count: int | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime
    processed_at: datetime | None = None

    @classmethod
    def from_document(cls, document: Document) -> DocumentResponse:
        return cls(
            id=document.id,
            filename=document.original_filename,
            content_type=document.content_type,
            document_type=document.document_type,
            file_size=document.file_size,
            checksum=document.checksum,
            status=document.status,
            error_message=document.error_message,
            page_count=document.page_count,
            character_count=document.character_count,
            metadata=document.metadata_,
            created_at=document.created_at,
            updated_at=document.updated_at,
            processed_at=document.processed_at,
        )


class DocumentUploadResponse(DocumentResponse):
    is_duplicate: bool

    @classmethod
    def build(cls, document: Document, *, is_duplicate: bool) -> DocumentUploadResponse:
        base = DocumentResponse.from_document(document)
        return cls(is_duplicate=is_duplicate, **base.model_dump())


class DocumentChunkResponse(BaseModel):
    id: uuid.UUID
    chunk_index: int
    content: str
    character_count: int
    token_count: int | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime

    @classmethod
    def from_chunk(cls, chunk: DocumentChunk) -> DocumentChunkResponse:
        return cls(
            id=chunk.id,
            chunk_index=chunk.chunk_index,
            content=chunk.content,
            character_count=chunk.character_count,
            token_count=chunk.token_count,
            metadata=chunk.metadata_,
            created_at=chunk.created_at,
        )


class PaginatedDocuments(BaseModel):
    items: list[DocumentResponse]
    total: int
    limit: int
    offset: int


class PaginatedDocumentChunks(BaseModel):
    items: list[DocumentChunkResponse]
    total: int
    limit: int
    offset: int
