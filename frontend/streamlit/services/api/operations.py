"""The Operations API module — wraps Milestone 9's
`/api/v1/operations/summary`. Only reports counts the backend actually
derived from persisted data; see `app.api.schemas.operations`.
"""

from __future__ import annotations

from dataclasses import dataclass

from .client import request_json


@dataclass(frozen=True)
class OperationsSummary:
    total_documents: int
    documents_by_status: dict[str, int]


def get_operations_summary() -> OperationsSummary:
    payload = request_json("GET", "/api/v1/operations/summary")
    return OperationsSummary(
        total_documents=payload["total_documents"],
        documents_by_status=payload["documents_by_status"],
    )
