"""The Documents API module — wraps Milestone 3's existing
`/api/v1/documents` endpoints. Field names mirror
`app.api.schemas.documents` read directly from the backend source, not
invented or guessed from memory.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .client import request_json


@dataclass(frozen=True)
class DocumentRecord:
    id: str
    filename: str
    content_type: str
    document_type: str
    file_size: int
    status: str
    error_message: str | None
    page_count: int | None
    character_count: int | None
    metadata: dict[str, Any] | None
    created_at: str
    updated_at: str
    processed_at: str | None


@dataclass(frozen=True)
class DocumentUploadRecord(DocumentRecord):
    is_duplicate: bool = False


@dataclass(frozen=True)
class DocumentChunkRecord:
    id: str
    chunk_index: int
    content: str
    character_count: int
    token_count: int | None
    metadata: dict[str, Any] | None
    created_at: str


@dataclass(frozen=True)
class EmbeddingStatus:
    document_id: str
    provider: str
    model: str
    model_version: str
    dimension: int
    total_chunks: int
    embedded_chunks: int
    status: str


def _document_from_payload(payload: dict[str, Any]) -> DocumentRecord:
    return DocumentRecord(
        id=payload["id"],
        filename=payload["filename"],
        content_type=payload["content_type"],
        document_type=payload["document_type"],
        file_size=payload["file_size"],
        status=payload["status"],
        error_message=payload.get("error_message"),
        page_count=payload.get("page_count"),
        character_count=payload.get("character_count"),
        metadata=payload.get("metadata"),
        created_at=payload["created_at"],
        updated_at=payload["updated_at"],
        processed_at=payload.get("processed_at"),
    )


def list_documents(*, limit: int = 100, offset: int = 0) -> tuple[list[DocumentRecord], int]:
    payload = request_json("GET", "/api/v1/documents", params={"limit": limit, "offset": offset})
    items = [_document_from_payload(item) for item in payload["items"]]
    return items, payload["total"]


def get_document(document_id: str) -> DocumentRecord:
    payload = request_json("GET", f"/api/v1/documents/{document_id}")
    return _document_from_payload(payload)


def get_document_chunks(
    document_id: str, *, limit: int = 50, offset: int = 0
) -> tuple[list[DocumentChunkRecord], int]:
    payload = request_json(
        "GET",
        f"/api/v1/documents/{document_id}/chunks",
        params={"limit": limit, "offset": offset},
    )
    items = [
        DocumentChunkRecord(
            id=chunk["id"],
            chunk_index=chunk["chunk_index"],
            content=chunk["content"],
            character_count=chunk["character_count"],
            token_count=chunk.get("token_count"),
            metadata=chunk.get("metadata"),
            created_at=chunk["created_at"],
        )
        for chunk in payload["items"]
    ]
    return items, payload["total"]


def upload_document(filename: str, content_type: str, content: bytes) -> DocumentUploadRecord:
    payload = request_json(
        "POST",
        "/api/v1/documents",
        files={"file": (filename, content, content_type)},
        ok_status_codes=(200, 201),
    )
    base = _document_from_payload(payload)
    return DocumentUploadRecord(**vars(base), is_duplicate=payload["is_duplicate"])


def delete_document(document_id: str) -> None:
    request_json("DELETE", f"/api/v1/documents/{document_id}", ok_status_codes=(204,))


def trigger_embeddings(document_id: str) -> dict[str, Any]:
    return request_json("POST", f"/api/v1/documents/{document_id}/embeddings")


def get_embedding_status(document_id: str) -> EmbeddingStatus:
    payload = request_json("GET", f"/api/v1/documents/{document_id}/embeddings")
    return EmbeddingStatus(
        document_id=payload["document_id"],
        provider=payload["provider"],
        model=payload["model"],
        model_version=payload["model_version"],
        dimension=payload["dimension"],
        total_chunks=payload["total_chunks"],
        embedded_chunks=payload["embedded_chunks"],
        status=payload["status"],
    )
