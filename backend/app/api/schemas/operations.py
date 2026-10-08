"""Response schema for the operations summary endpoint (Milestone 9).

Only reports counts actually derivable from persisted data
(`documents` table status counts) — no request/workflow counts are
included, since no workflow history is persisted anywhere yet (the M8
multi-agent orchestrator is stateless by design — see
docs/architecture/decisions/010-multi-agent-architecture.md). Adding
that would be a genuine backend change beyond "the smallest necessary for
the UI," not a fabricated metric, so it is intentionally left out rather
than invented — see ADR 011.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.domain.enums.document_status import DocumentStatus


class OperationsSummaryResponse(BaseModel):
    total_documents: int
    documents_by_status: dict[DocumentStatus, int]

    @classmethod
    def from_counts(cls, counts: dict[DocumentStatus, int]) -> OperationsSummaryResponse:
        complete_counts = {status: counts.get(status, 0) for status in DocumentStatus}
        return cls(
            total_documents=sum(complete_counts.values()), documents_by_status=complete_counts
        )
