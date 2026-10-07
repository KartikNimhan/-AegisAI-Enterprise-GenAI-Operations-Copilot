"""Unit tests for the MCP client/adapter boundary: the server-level and
tool-level allowlists, discovery, error categorization (connection,
discovery, timeout, execution), and that a discovered tool round-trips
into a working `ToolDefinition` — all against the real in-process MCP
server built from fakes, no real network or DB.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.mcp.client import (
    discover_mcp_tool_definitions,
    discover_mcp_tools,
    ensure_tool_trusted,
)
from app.mcp.exceptions import (
    MCPServerNotTrustedError,
    MCPTimeoutError,
    MCPToolDiscoveryError,
    MCPToolNotTrustedError,
)
from app.mcp.server import build_mcp_server
from app.rag.retrieval.service import RetrievalService

from ..rag.doubles import FakeRetrievalStrategy, make_result
from ..services.document_doubles import FakeDocumentRepository


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "rag_top_k": 5,
        "rag_max_results": 20,
        "rag_similarity_threshold": 0.3,
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _make_server(*, retrieval_results: list | None = None):
    documents = FakeDocumentRepository()
    retrieval = RetrievalService(
        strategy=FakeRetrievalStrategy(results=retrieval_results or []), settings=_settings()
    )
    return build_mcp_server(documents=documents, retrieval=retrieval)  # type: ignore[arg-type]


# -- Allowlist (ensure_tool_trusted) ----------------------------------------------


def test_ensure_tool_trusted_passes_for_a_trusted_tool() -> None:
    settings = _settings(trusted_mcp_tools=["calculator"])
    ensure_tool_trusted("calculator", settings=settings)  # must not raise


def test_ensure_tool_trusted_raises_for_an_untrusted_tool() -> None:
    settings = _settings(trusted_mcp_tools=["calculator"])
    with pytest.raises(MCPToolNotTrustedError):
        ensure_tool_trusted("delete_everything", settings=settings)


# -- discover_mcp_tools (raising) -------------------------------------------------


async def test_discover_mcp_tools_raises_when_server_not_trusted() -> None:
    server = _make_server()
    settings = _settings(trusted_mcp_servers=["some-other-server"])

    with pytest.raises(MCPServerNotTrustedError):
        await discover_mcp_tools(server=server, settings=settings)


async def test_discover_mcp_tools_returns_the_servers_tools() -> None:
    server = _make_server()
    settings = _settings(trusted_mcp_servers=["aegisai-internal"])

    tools = await discover_mcp_tools(server=server, settings=settings)

    assert {t.name for t in tools} == {
        "calculator",
        "get_document_metadata",
        "search_knowledge_base",
    }


async def test_discover_mcp_tools_wraps_connection_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.mcp.client as client_module

    class _BrokenClient:
        def __init__(self, server: object) -> None:
            pass

        async def __aenter__(self) -> _BrokenClient:
            raise ConnectionError("simulated transport failure")

        async def __aexit__(self, *exc: object) -> bool:
            return False

    monkeypatch.setattr(client_module, "Client", _BrokenClient)
    server = _make_server()
    settings = _settings(trusted_mcp_servers=["aegisai-internal"])

    with pytest.raises(MCPToolDiscoveryError):
        await discover_mcp_tools(server=server, settings=settings)


async def test_discover_mcp_tools_wraps_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patches the real `Client.list_tools` to hang, so the real
    `asyncio.wait_for` performs a genuine cancellation — monkeypatching
    `asyncio.wait_for` itself leaves the in-process session's task group in
    a broken state, since nothing then cancels the pending request."""
    from mcp.client import Client as RealClient

    async def _hangs(self: object) -> None:
        await asyncio.sleep(10)

    monkeypatch.setattr(RealClient, "list_tools", _hangs)
    server = _make_server()
    settings = _settings(trusted_mcp_servers=["aegisai-internal"], mcp_client_timeout_seconds=0.05)

    with pytest.raises(MCPTimeoutError):
        await discover_mcp_tools(server=server, settings=settings)


# -- discover_mcp_tool_definitions (resilient wrapper) ----------------------------


async def test_discover_tool_definitions_returns_empty_when_server_not_trusted() -> None:
    server = _make_server()
    settings = _settings(trusted_mcp_servers=["some-other-server"])

    definitions = await discover_mcp_tool_definitions(server=server, settings=settings)

    assert definitions == []


async def test_discover_tool_definitions_returns_empty_on_discovery_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.mcp.client as client_module

    class _BrokenClient:
        def __init__(self, server: object) -> None:
            pass

        async def __aenter__(self) -> _BrokenClient:
            raise ConnectionError("simulated transport failure")

        async def __aexit__(self, *exc: object) -> bool:
            return False

    monkeypatch.setattr(client_module, "Client", _BrokenClient)
    server = _make_server()
    settings = _settings(trusted_mcp_servers=["aegisai-internal"])

    definitions = await discover_mcp_tool_definitions(server=server, settings=settings)

    assert definitions == []


async def test_discover_tool_definitions_filters_out_untrusted_tool_names() -> None:
    server = _make_server()
    settings = _settings(
        trusted_mcp_servers=["aegisai-internal"],
        trusted_mcp_tools=["calculator"],
    )

    definitions = await discover_mcp_tool_definitions(server=server, settings=settings)

    assert [d.name for d in definitions] == ["mcp_calculator"]


async def test_discover_tool_definitions_prefixes_names_and_validates_arguments() -> None:
    server = _make_server()
    settings = _settings(
        trusted_mcp_servers=["aegisai-internal"],
        trusted_mcp_tools=["calculator", "get_document_metadata", "search_knowledge_base"],
    )

    definitions = await discover_mcp_tool_definitions(server=server, settings=settings)
    names = {d.name for d in definitions}
    assert names == {"mcp_calculator", "mcp_get_document_metadata", "mcp_search_knowledge_base"}

    calculator = next(d for d in definitions if d.name == "mcp_calculator")
    with pytest.raises(ValidationError):
        calculator.args_schema.model_validate({"expression": "2+2", "unexpected_field": 1})


async def test_discovered_calculator_tool_definition_executes_successfully() -> None:
    server = _make_server()
    settings = _settings(trusted_mcp_servers=["aegisai-internal"], trusted_mcp_tools=["calculator"])
    definitions = await discover_mcp_tool_definitions(server=server, settings=settings)
    calculator = definitions[0]

    args = calculator.args_schema.model_validate({"expression": "6 * 7"})
    result = await calculator.executor(args)

    assert result.success is True
    assert result.data is not None
    assert result.data["result"] == 42


async def test_discovered_calculator_tool_definition_surfaces_execution_failure() -> None:
    server = _make_server()
    settings = _settings(trusted_mcp_servers=["aegisai-internal"], trusted_mcp_tools=["calculator"])
    definitions = await discover_mcp_tool_definitions(server=server, settings=settings)
    calculator = definitions[0]

    args = calculator.args_schema.model_validate({"expression": "__import__('os')"})
    result = await calculator.executor(args)

    assert result.success is False
    assert result.error_code == "internal_error"


async def test_discovered_search_knowledge_base_tool_definition_executes_successfully() -> None:
    server = _make_server(retrieval_results=[make_result(content="relevant text")])
    settings = _settings(
        trusted_mcp_servers=["aegisai-internal"], trusted_mcp_tools=["search_knowledge_base"]
    )
    definitions = await discover_mcp_tool_definitions(server=server, settings=settings)
    search = definitions[0]

    args = search.args_schema.model_validate({"query": "policy"})
    result = await search.executor(args)

    assert result.success is True
    assert result.data is not None
    assert len(result.data["results"]) == 1


async def test_discovered_tool_definition_executor_handles_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _make_server()
    settings = _settings(
        trusted_mcp_servers=["aegisai-internal"],
        trusted_mcp_tools=["calculator"],
        mcp_client_timeout_seconds=0.05,
    )
    definitions = await discover_mcp_tool_definitions(server=server, settings=settings)
    calculator = definitions[0]

    from mcp.client import Client as RealClient

    async def _hangs(self: object, *args: object, **kwargs: object) -> None:
        await asyncio.sleep(10)

    monkeypatch.setattr(RealClient, "call_tool", _hangs)
    args = calculator.args_schema.model_validate({"expression": "1+1"})

    result = await calculator.executor(args)

    assert result.success is False
    assert result.error_code == "transient_error"
    assert "timed out" in (result.error or "").lower()


async def test_discovered_tool_definition_executor_handles_server_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.mcp.client as client_module

    server = _make_server()
    settings = _settings(trusted_mcp_servers=["aegisai-internal"], trusted_mcp_tools=["calculator"])
    definitions = await discover_mcp_tool_definitions(server=server, settings=settings)
    calculator = definitions[0]

    class _BrokenClient:
        def __init__(self, server: object) -> None:
            pass

        async def __aenter__(self) -> _BrokenClient:
            raise ConnectionError("simulated transport failure")

        async def __aexit__(self, *exc: object) -> bool:
            return False

    monkeypatch.setattr(client_module, "Client", _BrokenClient)
    args = calculator.args_schema.model_validate({"expression": "1+1"})

    result = await calculator.executor(args)

    assert result.success is False
    assert result.error_code == "transient_error"
    assert "unavailable" in (result.error or "").lower()
