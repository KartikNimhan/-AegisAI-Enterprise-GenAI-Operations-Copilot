"""Document ingestion endpoints.

Kept thin: all orchestration (validation, storage, extraction,
normalization, chunking, persistence) lives in
`app.services.document_service.DocumentService`. This module must never
import `app.storage`, `app.documents.extractors`, or
`app.db.repositories` directly, and never returns a raw filesystem path.
"""

from __future__ import annotations

import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status

from app.api.schemas.documents import (
    DocumentChunkResponse,
    DocumentResponse,
    DocumentUploadResponse,
    DocumentVisibilityRequest,
    PaginatedDocumentChunks,
    PaginatedDocuments,
)
from app.api.schemas.embeddings import EmbeddingStatusResponse, EmbeddingTriggerResponse
from app.config import Settings, get_settings
from app.core import audit
from app.core.exceptions import DocumentShareForbiddenError, NotFoundError
from app.core.rate_limit import EMBEDDING_RATE_LIMIT, UPLOAD_RATE_LIMIT
from app.core.security import PrincipalDep
from app.embeddings.service import EmbeddingService, get_embedding_service
from app.services.document_service import DocumentService, get_document_service

router = APIRouter(prefix="/documents", tags=["documents"])

DocumentServiceDep = Annotated[DocumentService, Depends(get_document_service)]
EmbeddingServiceDep = Annotated[EmbeddingService, Depends(get_embedding_service)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.post(
    "",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[UPLOAD_RATE_LIMIT],
)
async def upload_document(
    document_service: DocumentServiceDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    response: Response,
    file: Annotated[UploadFile, File()],
) -> DocumentUploadResponse:
    # Bounded read: never buffer more than max_size + 1 bytes, regardless
    # of how large the client claims (or actually tries) to upload.
    max_size = settings.document_max_upload_size_bytes
    content = await file.read(max_size + 1)

    result = await document_service.upload(
        filename=file.filename or "upload",
        content_type=file.content_type or "application/octet-stream",
        content=content,
    )
    audit.record(
        "document.uploaded",
        actor=principal,
        resource_type="document",
        resource_id=result.document.id,
        duplicate=result.is_duplicate,
    )
    if result.is_duplicate:
        # Nothing new was created — 200, not the decorator's default 201.
        response.status_code = status.HTTP_200_OK
    return DocumentUploadResponse.build(result.document, is_duplicate=result.is_duplicate)


@router.get("", response_model=PaginatedDocuments)
async def list_documents(
    document_service: DocumentServiceDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedDocuments:
    documents, total = await document_service.list_documents(limit=limit, offset=offset)
    return PaginatedDocuments(
        items=[DocumentResponse.from_document(d) for d in documents],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: uuid.UUID, document_service: DocumentServiceDep
) -> DocumentResponse:
    document = await document_service.get_document(document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found")
    return DocumentResponse.from_document(document)


@router.get(
    "/{document_id}/file",
    response_class=Response,
    responses={200: {"description": "The original uploaded file, as an attachment."}},
)
async def download_document_file(
    document_id: uuid.UUID, document_service: DocumentServiceDep, principal: PrincipalDep
) -> Response:
    """The original uploaded file (M10.6), for a caller who can currently read the document.

    Always an attachment, never rendered inline by the browser: uploaded files are untrusted
    content. The media type comes from the validated document type, and the response may not be
    sniffed, cached, framed or run as a page (`sandbox`). Anything the caller cannot read is 404.
    """
    original = await document_service.get_original_file(document_id)
    audit.record(
        "document.downloaded",
        actor=principal,
        resource_type="document",
        resource_id=document_id,
        outcome="success" if original is not None else "not_found",
    )
    if original is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found")
    return Response(
        content=original.content,
        media_type=original.media_type,
        headers={
            "Content-Disposition": content_disposition(original.filename),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cross-Origin-Resource-Policy": "same-origin",
        },
    )


def content_disposition(filename: str) -> str:
    """`attachment` with an ASCII fallback name and the exact UTF-8 name (RFC 6266 / 5987).

    The fallback keeps only safe characters, so a quote, backslash, CR/LF or path separator in
    an uploaded name can never break out of the header or change the saved location."""
    fallback = "".join(
        c if c.isascii() and (c.isalnum() or c in " ._-()") else "_" for c in filename
    )
    fallback = fallback.strip(" .") or "document"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


@router.patch("/{document_id}/visibility", response_model=DocumentResponse)
async def set_document_visibility(
    document_id: uuid.UUID,
    request: DocumentVisibilityRequest,
    document_service: DocumentServiceDep,
    principal: PrincipalDep,
) -> DocumentResponse:
    """Share a document with the owner's organization (its owner only), or make it private again
    (its owner, or an administrator of its organization). An administrator who tries to share a
    member's document gets 403 and nothing changes; anyone else gets 404."""
    try:
        change = await document_service.set_visibility(document_id, request.visibility)
    except DocumentShareForbiddenError:
        audit.record(
            "document.visibility_changed",
            actor=principal,
            resource_type="document",
            resource_id=document_id,
            outcome="forbidden",
            visibility=request.visibility.value,
        )
        raise
    if change is None:
        audit.record(
            "document.visibility_changed",
            actor=principal,
            resource_type="document",
            resource_id=document_id,
            outcome="not_found",
            visibility=request.visibility.value,
        )
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found")
    # The actor both requested and authorized the change: only the owner may widen, so a change
    # made by someone else (`by_owner=False`) is always an administrator narrowing it.
    audit.record(
        "document.visibility_changed",
        actor=principal,
        resource_type="document",
        resource_id=document_id,
        outcome="success",
        previous_visibility=change.previous.value,
        visibility=request.visibility.value,
        by_owner=change.by_owner,
    )
    return DocumentResponse.from_document(change.document)


@router.get("/{document_id}/chunks", response_model=PaginatedDocumentChunks)
async def get_document_chunks(
    document_id: uuid.UUID,
    document_service: DocumentServiceDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedDocumentChunks:
    result = await document_service.get_document_chunks(document_id, limit=limit, offset=offset)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found")
    chunks, total = result
    return PaginatedDocumentChunks(
        items=[DocumentChunkResponse.from_chunk(c) for c in chunks],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID, document_service: DocumentServiceDep, principal: PrincipalDep
) -> None:
    deleted = await document_service.delete_document(document_id)
    audit.record(
        "document.deleted",
        actor=principal,
        resource_type="document",
        resource_id=document_id,
        outcome="success" if deleted else "not_found",
    )
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found")


@router.post(
    "/{document_id}/embeddings",
    response_model=EmbeddingTriggerResponse,
    dependencies=[EMBEDDING_RATE_LIMIT],
)
async def trigger_document_embeddings(
    document_id: uuid.UUID, embedding_service: EmbeddingServiceDep, principal: PrincipalDep
) -> EmbeddingTriggerResponse:
    # Synchronous for this milestone (no task queue yet — see
    # app.embeddings.service docstring). NotFoundError/DocumentNotReadyError
    # are mapped to HTTP responses by the handlers in app.core.exceptions.
    try:
        result = await embedding_service.embed_document(document_id)
    except NotFoundError:
        audit.record(
            "document.embedding_requested",
            actor=principal,
            resource_type="document",
            resource_id=document_id,
            outcome="not_found",
        )
        raise
    audit.record(
        "document.embedding_requested",
        actor=principal,
        resource_type="document",
        resource_id=document_id,
    )
    return EmbeddingTriggerResponse.from_result(result)


@router.get("/{document_id}/embeddings", response_model=EmbeddingStatusResponse)
async def get_document_embedding_status(
    document_id: uuid.UUID, embedding_service: EmbeddingServiceDep
) -> EmbeddingStatusResponse:
    status_obj = await embedding_service.get_embedding_status(document_id)
    return EmbeddingStatusResponse.from_status(status_obj)
