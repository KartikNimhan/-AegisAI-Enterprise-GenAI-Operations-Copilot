"""Document ingestion orchestration.

Pipeline: validate -> checksum -> duplicate check -> store -> extract ->
normalize -> build metadata -> chunk -> persist -> PROCESSED (or FAILED).

Two explicit commits, not one — deliberately different from `ChatService`'s
single-transaction-per-request pattern (see
docs/architecture/decisions/005-document-ingestion.md):

1. After validation + storage, the `Document` row is committed with status
   `UPLOADED`. The file is already durably on disk by this point, so the
   database record must survive regardless of what happens next.
2. Processing (extract/normalize/chunk/persist) then runs against that same
   row, ending in a second commit with status `PROCESSED` or `FAILED`.

This split is also exactly the seam a future background worker would use:
step 1 (handle the upload) and step 2 (process it) can already be called
independently — `_process` takes only a `Document` already in `UPLOADED`.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.repositories.document_chunk_repository import DocumentChunkRepository
from app.db.repositories.document_repository import DocumentRepository
from app.dependencies import DBSessionDep
from app.documents.chunk_ids import compute_chunk_id
from app.documents.chunking.base import Chunker
from app.documents.chunking.recursive import RecursiveChunker
from app.documents.exceptions import ExtractionError
from app.documents.extractors import get_extractor
from app.documents.metadata import build_document_metadata
from app.documents.normalization import normalize_text
from app.documents.validation import (
    determine_document_type,
    generate_storage_key,
    sanitize_filename,
    validate_content_type,
    validate_magic_bytes,
    validate_size,
)
from app.domain.enums.document_status import DocumentStatus
from app.domain.enums.document_type import DocumentType
from app.domain.models.document import Document
from app.domain.models.document_chunk import DocumentChunk
from app.storage.base import DocumentStorage
from app.storage.local import get_document_storage

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class DocumentUploadResult:
    document: Document
    is_duplicate: bool


class DocumentService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        settings: Settings,
        documents: DocumentRepository,
        chunks: DocumentChunkRepository,
        storage: DocumentStorage,
        chunker: Chunker | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._documents = documents
        self._chunks = chunks
        self._storage = storage
        self._chunker = chunker or RecursiveChunker()

    # -- Upload -----------------------------------------------------------

    async def upload(
        self, *, filename: str, content_type: str, content: bytes
    ) -> DocumentUploadResult:
        safe_name = sanitize_filename(filename)
        document_type = determine_document_type(
            filename=safe_name, allowed_types=self._settings.document_allowed_types
        )
        validate_size(size=len(content), max_size=self._settings.document_max_upload_size_bytes)
        validate_content_type(document_type=document_type, content_type=content_type)
        validate_magic_bytes(document_type=document_type, content=content)

        checksum = _compute_checksum(content)

        existing = await self._documents.get_by_checksum(checksum)
        if existing is not None:
            logger.info(
                "document_duplicate_detected", document_id=str(existing.id), checksum=checksum
            )
            return DocumentUploadResult(document=existing, is_duplicate=True)

        document = await self._create_and_store(
            safe_name=safe_name,
            content_type=content_type,
            document_type=document_type,
            size=len(content),
            checksum=checksum,
            content=content,
        )
        await self._process(document)
        return DocumentUploadResult(document=document, is_duplicate=False)

    async def _create_and_store(
        self,
        *,
        safe_name: str,
        content_type: str,
        document_type: DocumentType,
        size: int,
        checksum: str,
        content: bytes,
    ) -> Document:
        document = self._documents.new(
            filename="",  # fixed below, once the id (needed for the key) exists
            original_filename=safe_name,
            content_type=content_type,
            document_type=document_type,
            file_size=size,
            checksum=checksum,
            status=DocumentStatus.UPLOADED,
        )
        await self._session.flush()  # assigns id + created_at; not committed yet

        storage_key = generate_storage_key(document_id=document.id, document_type=document_type)
        document.filename = storage_key
        try:
            await self._storage.save(key=storage_key, content=content)
        except Exception:
            await self._session.rollback()
            raise

        await self._session.commit()
        logger.info(
            "document_uploaded",
            document_id=str(document.id),
            document_type=document_type.value,
            file_size=size,
            checksum=checksum,
        )
        return document

    # -- Processing ---------------------------------------------------------

    async def _process(self, document: Document) -> None:
        document.status = DocumentStatus.PROCESSING
        start = time.perf_counter()
        try:
            chunk_models = await self._extract_normalize_and_chunk(document)

            async with self._session.begin_nested():
                await self._chunks.add_all(chunk_models)

            finished_at = datetime.now(UTC)
            document.status = DocumentStatus.PROCESSED
            document.error_message = None
            document.processed_at = finished_at
            document.updated_at = finished_at
            logger.info(
                "document_processed",
                document_id=str(document.id),
                document_type=document.document_type.value,
                chunk_count=len(chunk_models),
                character_count=document.character_count,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )
        except Exception as exc:
            finished_at = datetime.now(UTC)
            document.status = DocumentStatus.FAILED
            document.error_message = _safe_error_message(exc)
            document.processed_at = finished_at
            document.updated_at = finished_at
            logger.warning(
                "document_processing_failed",
                document_id=str(document.id),
                document_type=document.document_type.value,
                error_type=type(exc).__name__,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )

        await self._session.commit()

    async def _extract_normalize_and_chunk(self, document: Document) -> list[DocumentChunk]:
        extractor = get_extractor(document.document_type)
        raw_content = await self._storage.read(key=document.filename)
        # Extraction/chunking are CPU-bound sync code; offload so a large
        # document doesn't block the event loop.
        extraction = await asyncio.to_thread(extractor.extract, raw_content)

        if extraction.is_empty:
            raise ExtractionError("No extractable text content found in document")

        original_character_count = len(extraction.text)
        normalized_pages = [normalize_text(page) for page in extraction.pages]
        normalized_character_count = sum(len(page) for page in normalized_pages)

        chunks_data = await asyncio.to_thread(
            self._chunker.chunk,
            pages=normalized_pages,
            chunk_size=self._settings.document_chunk_size,
            chunk_overlap=self._settings.document_chunk_overlap,
        )

        document.character_count = normalized_character_count
        document.page_count = extraction.metadata.get("page_count")
        document.metadata_ = build_document_metadata(
            extraction_metadata=extraction.metadata,
            original_character_count=original_character_count,
            normalized_character_count=normalized_character_count,
        )

        return [
            DocumentChunk(
                id=compute_chunk_id(
                    document_checksum=document.checksum,
                    chunk_size=self._settings.document_chunk_size,
                    chunk_overlap=self._settings.document_chunk_overlap,
                    chunk_index=chunk.chunk_index,
                ),
                document_id=document.id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                character_count=chunk.character_count,
                metadata_=chunk.metadata or None,
            )
            for chunk in chunks_data
        ]

    # -- Read / delete ------------------------------------------------------

    async def list_documents(
        self, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[Document], int]:
        return await self._documents.list(limit=limit, offset=offset)

    async def get_document(self, document_id: uuid.UUID) -> Document | None:
        return await self._documents.get(document_id)

    async def get_document_chunks(
        self, document_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[DocumentChunk], int] | None:
        document = await self._documents.get(document_id)
        if document is None:
            return None
        return await self._chunks.list_by_document(document_id, limit=limit, offset=offset)

    async def delete_document(self, document_id: uuid.UUID) -> bool:
        document = await self._documents.get(document_id)
        if document is None:
            return False

        storage_key = document.filename
        deleted = await self._documents.delete(document_id)  # cascades chunks via FK
        if deleted:
            try:
                await self._storage.delete(key=storage_key)
            except Exception as exc:
                # The database record (the source of truth for the API) is
                # already gone; an orphaned file is a cleanup concern, not
                # a reason to report the delete itself as failed.
                logger.warning(
                    "document_file_delete_failed",
                    document_id=str(document_id),
                    error_type=type(exc).__name__,
                )
        return deleted


def _compute_checksum(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _safe_error_message(exc: Exception) -> str:
    if isinstance(exc, ExtractionError):
        return str(exc)
    return "Document processing failed due to an internal error"


def get_document_service(
    session: DBSessionDep,
    settings: Annotated[Settings, Depends(get_settings)],
    storage: Annotated[DocumentStorage, Depends(get_document_storage)],
) -> DocumentService:
    return DocumentService(
        session=session,
        settings=settings,
        documents=DocumentRepository(session),
        chunks=DocumentChunkRepository(session),
        storage=storage,
    )
