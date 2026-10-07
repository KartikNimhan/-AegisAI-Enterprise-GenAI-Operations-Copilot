"""The Document Agent's own logic: given one or more document ids, return
safe metadata for each.

Deliberately reuses `DocumentRepository` directly — the same repository
`DocumentService`/the M6 `get_document_metadata` tool/the MCP server's
`get_document_metadata` adapter already use. No new query logic, no new
persistence concern: this is a thin A2A-facing wrapper over an existing
read, the same "adapt, don't duplicate" rule MCP's server module follows.

Deterministic, no LLM call: a metadata lookup has no synthesis step of
its own (comparing/synthesizing across a document's metadata and another
agent's findings is the Analyst Agent's job — see
docs/architecture/decisions/010-multi-agent-architecture.md, "Specialized
agents").
"""

from __future__ import annotations

import uuid

from app.a2a.schemas import DocumentAgentResult, DocumentReference
from app.db.repositories.document_repository import DocumentRepository

NO_DOCUMENTS_FOUND_RESPONSE = "None of the requested documents could be found."


class DocumentAgentService:
    def __init__(self, *, documents: DocumentRepository) -> None:
        self._documents = documents

    async def analyze(self, *, document_ids: list[uuid.UUID]) -> DocumentAgentResult:
        found: list[DocumentReference] = []
        missing: list[str] = []

        for document_id in document_ids:
            document = await self._documents.get(document_id)
            if document is None:
                missing.append(str(document_id))
                continue
            found.append(
                DocumentReference(
                    document_id=document.id,
                    filename=document.original_filename,
                    document_type=document.document_type.value,
                    status=document.status.value,
                    page_count=document.page_count,
                    character_count=document.character_count,
                )
            )

        if not found:
            error = (
                f"No matching documents found for: {', '.join(missing)}"
                if missing
                else "No document ids were supplied"
            )
            return DocumentAgentResult(status="failed", answer="", error=error)

        answer = _summarize(found, missing)
        return DocumentAgentResult(status="completed", answer=answer, documents=found)


def _summarize(found: list[DocumentReference], missing: list[str]) -> str:
    lines = [
        f"{doc.filename} ({doc.document_type}, status={doc.status}, "
        f"{doc.page_count if doc.page_count is not None else '?'} pages)"
        for doc in found
    ]
    summary = "Found " + "; ".join(lines) + "."
    if missing:
        summary += f" Could not find: {', '.join(missing)}."
    return summary
