"""Document Agent A2A endpoints.

Mirrors `app.api.v1.research_agent`'s shape exactly: `DocumentAgentService`
(reusing `DocumentRepository`) does the actual work; this module only
builds the Agent Card and the Task response around its result. Served
only at this versioned path — not `/.well-known/agent-card.json`, since
that path is a per-origin convention and the Research Agent already
serves it there (see ADR 010, "Agent Card").

Synchronous, same reasoning as the Research Agent (see
docs/architecture/decisions/009-mcp-a2a-architecture.md, "Why M7's A2A
task handling is synchronous").
"""

from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.a2a.agent_card import agent_card_to_json_dict, build_document_agent_card
from app.a2a.document_agent import DocumentAgentService
from app.a2a.schemas import DocumentAgentResult
from app.a2a.tasks import build_generic_task, task_to_dict
from app.config import get_settings
from app.db.repositories.document_repository import DocumentRepository
from app.dependencies import DBSessionDep

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/agents/document", tags=["a2a"])

DOCUMENT_RESULT_ARTIFACT_NAME = "document_result"


class DocumentTaskRequest(BaseModel):
    document_ids: list[uuid.UUID] = Field(min_length=1, description="Document ids to look up.")


def get_document_agent_service(session: DBSessionDep) -> DocumentAgentService:
    return DocumentAgentService(documents=DocumentRepository(session))


DocumentAgentServiceDep = Annotated[DocumentAgentService, Depends(get_document_agent_service)]


@router.get("/card")
async def get_document_agent_card(request: Request) -> JSONResponse:
    settings = get_settings()
    card = build_document_agent_card(settings, base_url=str(request.base_url).rstrip("/"))
    return JSONResponse(content=agent_card_to_json_dict(card))


@router.post("/tasks")
async def submit_document_task(
    request: DocumentTaskRequest, agent_service: DocumentAgentServiceDep
) -> JSONResponse:
    logger.info("a2a.task_started", document_count=len(request.document_ids))
    try:
        result = await agent_service.analyze(document_ids=request.document_ids)
    except Exception:
        logger.exception("a2a.task_failed", error_type="internal")
        result = DocumentAgentResult(
            status="failed", answer="", error="The document agent failed to complete the task"
        )
    else:
        logger.info("a2a.task_completed", status=result.status)

    payload = {
        "answer": result.answer,
        "documents": [
            {
                "document_id": str(doc.document_id),
                "filename": doc.filename,
                "document_type": doc.document_type,
                "status": doc.status,
                "page_count": doc.page_count,
                "character_count": doc.character_count,
            }
            for doc in result.documents
        ],
    }
    task = build_generic_task(
        request_text=", ".join(str(d) for d in request.document_ids),
        status=result.status,
        artifact_name=DOCUMENT_RESULT_ARTIFACT_NAME,
        payload=payload,
        error=result.error,
    )
    return JSONResponse(content=task_to_dict(task))
