"""Unit tests for the AegisAI MCP server: startup, the three exposed
tools, the document resource, and its error/safety behavior — all against
fakes, over the in-process MCP client/server transport (no real network,
no real DB).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from mcp.client import Client
from mcp.types import TextContent, TextResourceContents

from app.domain.enums.document_status import DocumentStatus
from app.domain.enums.document_type import DocumentType
from app.domain.models.document import Document
from app.mcp.server import MCP_SERVER_NAME, build_mcp_server
from app.rag.retrieval.service import RetrievalService

from ..rag.doubles import FakeRetrievalStrategy, make_result
from ..services.document_doubles import FakeDocumentRepository


def _text(content: list[Any]) -> str:
    """Narrows an MCP content/resource-contents list down to its text —
    mirrors `app.mcp.client._first_text`, duplicated here since pyright
    can't narrow `list[TextContent | ImageContent | ...]` otherwise."""
    for item in content:
        if isinstance(item, (TextContent, TextResourceContents)):
            return item.text
    raise AssertionError("expected a text content item")


def _settings():
    from app.config import Settings

    return Settings(rag_top_k=5, rag_max_results=20, rag_similarity_threshold=0.3)


def _make_document(**overrides: object) -> Document:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "filename": "internal-key.pdf",
        "original_filename": "Policy.pdf",
        "content_type": "application/pdf",
        "document_type": DocumentType.PDF,
        "file_size": 100,
        "checksum": "a" * 64,
        "status": DocumentStatus.PROCESSED,
        "page_count": 3,
        "character_count": 500,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return Document(**defaults)  # type: ignore[arg-type]


def _build_server(
    *, retrieval_results: list | None = None, documents: FakeDocumentRepository | None = None
):
    documents = documents or FakeDocumentRepository()
    retrieval = RetrievalService(
        strategy=FakeRetrievalStrategy(results=retrieval_results or []), settings=_settings()
    )
    return build_mcp_server(documents=documents, retrieval=retrieval), documents  # type: ignore[arg-type]


async def test_server_starts_and_lists_the_three_tools() -> None:
    server, _ = _build_server()

    async with Client(server) as client:
        result = await client.list_tools()

    names = {tool.name for tool in result.tools}
    assert names == {"calculator", "get_document_metadata", "search_knowledge_base"}


async def test_server_has_the_expected_name() -> None:
    assert MCP_SERVER_NAME == "aegisai-internal"


async def test_calculator_tool_discovery_schema_is_flat() -> None:
    server, _ = _build_server()

    async with Client(server) as client:
        result = await client.list_tools()

    calculator = next(t for t in result.tools if t.name == "calculator")
    assert "expression" in calculator.input_schema["properties"]
    assert "args" not in calculator.input_schema["properties"]


async def test_calculator_tool_call_succeeds() -> None:
    server, _ = _build_server()

    async with Client(server) as client:
        result = await client.call_tool("calculator", {"expression": "2 + 2"})

    assert result.is_error is not True
    payload = json.loads(_text(result.content))
    assert payload["result"] == 4


async def test_calculator_tool_call_with_invalid_expression_is_a_structured_error() -> None:
    server, _ = _build_server()

    async with Client(server) as client:
        result = await client.call_tool("calculator", {"expression": "__import__('os')"})

    assert result.is_error is True


async def test_get_document_metadata_tool_call_succeeds() -> None:
    document = _make_document()
    documents = FakeDocumentRepository()
    documents.documents[document.id] = document
    server, _ = _build_server(documents=documents)

    async with Client(server) as client:
        result = await client.call_tool("get_document_metadata", {"document_id": str(document.id)})

    assert result.is_error is not True
    payload = json.loads(_text(result.content))
    assert payload["filename"] == "Policy.pdf"
    assert "checksum" not in payload
    assert "metadata" in payload


async def test_get_document_metadata_tool_call_unknown_document_is_an_error() -> None:
    server, _ = _build_server()

    async with Client(server) as client:
        result = await client.call_tool("get_document_metadata", {"document_id": str(uuid.uuid4())})

    assert result.is_error is True


async def test_search_knowledge_base_tool_call_succeeds() -> None:
    server, _ = _build_server(retrieval_results=[make_result(content="relevant text")])

    async with Client(server) as client:
        result = await client.call_tool("search_knowledge_base", {"query": "policy"})

    assert result.is_error is not True
    payload = json.loads(_text(result.content))
    assert len(payload["results"]) == 1
    assert payload["results"][0]["content"] == "relevant text"


async def test_search_knowledge_base_tool_call_with_no_results() -> None:
    server, _ = _build_server(retrieval_results=[])

    async with Client(server) as client:
        result = await client.call_tool("search_knowledge_base", {"query": "nothing matches"})

    assert result.is_error is not True
    payload = json.loads(_text(result.content))
    assert payload["results"] == []


async def test_unknown_tool_name_is_a_structured_error_not_a_crash() -> None:
    server, _ = _build_server()

    async with Client(server) as client:
        result = await client.call_tool("delete_everything", {})

    assert result.is_error is True


async def test_document_resource_returns_safe_metadata_only() -> None:
    document = _make_document()
    documents = FakeDocumentRepository()
    documents.documents[document.id] = document
    server, _ = _build_server(documents=documents)

    async with Client(server) as client:
        result = await client.read_resource(f"document://{document.id}")

    payload = json.loads(_text(result.contents))
    assert payload["document_id"] == str(document.id)
    assert payload["filename"] == "Policy.pdf"
    for forbidden_key in ("checksum", "file_path", "embedding", "storage_key"):
        assert forbidden_key not in payload


async def test_document_resource_unknown_document_raises() -> None:
    server, _ = _build_server()

    try:
        async with Client(server) as client:
            await client.read_resource(f"document://{uuid.uuid4()}")
    except Exception:
        return
    raise AssertionError("expected reading an unknown document resource to raise")
