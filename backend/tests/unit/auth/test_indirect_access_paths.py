"""Agent tools, MCP, A2A and background work reach data only through the caller's repositories.

MOCK-BASED. These tests prove structure and delegation: that the indirect paths cannot open
their own database session or build their own repository, and that they treat "the repository
says this document is not visible" as "not found". They do NOT prove that a real database
hides another user's rows; that is tests/integration/test_data_isolation.py, which needs
PostgreSQL and has not been run.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

import pytest
from mcp.client import Client
from mcp.types import TextContent

from app.a2a.document_agent import DocumentAgentService
from app.agents.tools.document_metadata import DocumentMetadataArgs, build_document_metadata_tool
from app.mcp.server import build_mcp_server
from app.rag.retrieval.service import RetrievalService

from ..rag.doubles import FakeRetrievalStrategy
from ..services.document_doubles import FakeDocumentRepository

APP_DIR = Path(__file__).resolve().parents[3] / "app"

REPOSITORY_CONSTRUCTION = re.compile(r"\b[A-Z][A-Za-z]*Repository\(")
SESSION_ACQUISITION = re.compile(
    r"AsyncSessionLocal|get_session\b|async_sessionmaker|create_async_engine"
)

# Packages that act for a caller (tools the model can call, protocol servers, agents) and so must
# be handed their data access, never open their own.
INDIRECT_PACKAGES = ["agents/tools", "mcp", "a2a", "multi_agent"]


def _python_files(package: str) -> list[Path]:
    return [p for p in (APP_DIR / package).rglob("*.py") if "__pycache__" not in p.parts]


@pytest.mark.parametrize("package", INDIRECT_PACKAGES)
def test_indirect_paths_never_build_a_repository_or_open_a_database_session(package: str) -> None:
    files = _python_files(package)
    assert files, f"no files found for {package}"
    offenders = []
    for path in files:
        text = path.read_text(encoding="utf8")
        for pattern in (REPOSITORY_CONSTRUCTION, SESSION_ACQUISITION):
            if pattern.search(text):
                offenders.append(f"{path.relative_to(APP_DIR).as_posix()}: {pattern.pattern}")
    assert not offenders, (
        f"these must receive scoped repositories, not create their own: {offenders}"
    )


def test_the_only_background_task_in_the_application_carries_no_user_data() -> None:
    """If a background job is ever added, it must be given an explicit, scoped identity: this
    fails so that decision is made deliberately instead of by accident."""
    spawners = {}
    for path in APP_DIR.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf8")
        for needle in (
            "create_task(",
            "BackgroundTasks",
            "ensure_future(",
            "celery",
            "run_in_executor",
        ):
            if needle in text:
                spawners.setdefault(path.relative_to(APP_DIR).as_posix(), set()).add(needle)

    assert spawners == {"main.py": {"create_task("}}, spawners
    main = (APP_DIR / "main.py").read_text(encoding="utf8")
    assert "_warm_up_embedding_model" in main  # loads the embedding model; touches no data


# -- delegation: a repository that sees nothing yields "not found" ----------------------


class DeniesEverything(FakeDocumentRepository):
    """Stands in for a scoped repository whose caller may not see the document."""

    async def get(self, document_id: uuid.UUID) -> None:  # type: ignore[override]
        return None


async def test_the_agent_document_tool_reports_not_found_when_the_repository_denies() -> None:
    tool = build_document_metadata_tool(DeniesEverything())  # type: ignore[arg-type]

    result = await tool.executor(DocumentMetadataArgs(document_id=uuid.uuid4()))

    assert result.success is False and result.error_code == "not_found"


async def test_the_mcp_document_tool_reports_an_error_when_the_repository_denies() -> None:
    from app.config import Settings

    retrieval = RetrievalService(
        strategy=FakeRetrievalStrategy(results=[]),
        settings=Settings(rag_top_k=5, rag_max_results=20, rag_similarity_threshold=0.3),
    )
    server = build_mcp_server(documents=DeniesEverything(), retrieval=retrieval)  # type: ignore[arg-type]

    async with Client(server) as client:
        result = await client.call_tool("get_document_metadata", {"document_id": str(uuid.uuid4())})

    assert result.is_error is True
    text = next(c.text for c in result.content if isinstance(c, TextContent))
    assert "checksum" not in text and "filename" not in text


async def test_the_a2a_document_agent_reports_denied_documents_as_missing_without_details() -> None:
    service = DocumentAgentService(documents=DeniesEverything())  # type: ignore[arg-type]
    wanted = [uuid.uuid4(), uuid.uuid4()]

    outcome: Any = await service.analyze(document_ids=wanted)

    assert outcome.status == "failed" and outcome.documents == []
    assert outcome.answer == ""  # nothing about any document is returned
    assert all(str(document_id) in outcome.error for document_id in wanted)
    assert "filename" not in outcome.error and "checksum" not in outcome.error
