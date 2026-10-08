"""Operations summary endpoint (Milestone 9).

Kept thin and read-only: the only logic is a single grouped COUNT query
in `DocumentRepository.count_by_status`, reused as-is — this module adds
no new business logic.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.schemas.operations import OperationsSummaryResponse
from app.db.repositories.document_repository import DocumentRepository
from app.dependencies import DBSessionDep

router = APIRouter(prefix="/operations", tags=["operations"])


def get_operations_document_repository(session: DBSessionDep) -> DocumentRepository:
    return DocumentRepository(session)


OperationsDocumentRepositoryDep = Annotated[
    DocumentRepository, Depends(get_operations_document_repository)
]


@router.get("/summary", response_model=OperationsSummaryResponse)
async def get_operations_summary(
    documents: OperationsDocumentRepositoryDep,
) -> OperationsSummaryResponse:
    counts = await documents.count_by_status()
    return OperationsSummaryResponse.from_counts(counts)
