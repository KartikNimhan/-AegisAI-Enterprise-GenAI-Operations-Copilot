"""The `get_document_metadata` tool.

Reuses `DocumentRepository` directly (no new query logic) — the same
repository `DocumentService`/`RAGService` already use. Returns only the
fields Milestone 3's own API response (`DocumentResponse`) already
considers safe to expose: never the internal storage key (`filename` on
the ORM model — see `app.domain.models.document`'s own docstring on why
that's never client-facing), never a raw filesystem path, never the
checksum, never anything from `app.db`/connection configuration.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel

from app.agents.tools.base import ToolDefinition, ToolResult
from app.db.repositories.document_repository import DocumentRepository


class DocumentMetadataArgs(BaseModel):
    document_id: uuid.UUID


def _make_executor(documents: DocumentRepository) -> Any:
    async def _execute(args: BaseModel) -> ToolResult:
        assert isinstance(args, DocumentMetadataArgs)
        document = await documents.get(args.document_id)
        if document is None:
            return ToolResult(
                success=False,
                error=f"No document found with id {args.document_id}",
                error_code="not_found",
            )
        return ToolResult(
            success=True,
            data={
                "document_id": str(document.id),
                "filename": document.original_filename,
                "document_type": document.document_type.value,
                "status": document.status.value,
                "page_count": document.page_count,
                "character_count": document.character_count,
                "created_at": document.created_at.isoformat(),
                "processed_at": (
                    document.processed_at.isoformat() if document.processed_at else None
                ),
                "metadata": document.metadata_,
            },
        )

    return _execute


def build_document_metadata_tool(documents: DocumentRepository) -> ToolDefinition:
    return ToolDefinition(
        name="get_document_metadata",
        description=(
            "Look up safe metadata (filename, type, status, page/character counts, "
            "processing metadata) for a single document by its id. Does not return "
            "document content or embeddings — use search_knowledge_base for content."
        ),
        args_schema=DocumentMetadataArgs,
        executor=_make_executor(documents),
    )
