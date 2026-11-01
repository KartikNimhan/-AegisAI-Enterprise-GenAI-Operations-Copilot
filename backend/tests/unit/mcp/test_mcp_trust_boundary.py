"""The MCP server trust boundary (AIGSEC-013).

The allowlist used to compare a local constant with the settings, which says nothing about the
server actually connected to. Now the transport itself is restricted (only an in-process
`MCPServer` object this application builds), the server's own name must be allowlisted, and the
name it reports when the session starts must match. Anything else fails closed: the agent keeps
its internal tools and gets no MCP tools.
"""

from __future__ import annotations

from typing import Any

import pytest
from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from mcp.types import Implementation

from app.config import Settings
from app.mcp.client import (
    MCP_TOOL_NAME_PREFIX,
    discover_mcp_tool_definitions,
    discover_mcp_tools,
    ensure_reported_identity_matches,
)
from app.mcp.exceptions import MCPServerNotTrustedError
from app.mcp.server import MCP_SERVER_NAME, build_mcp_server
from app.rag.retrieval.service import RetrievalService

from ..rag.doubles import FakeRetrievalStrategy
from ..services.document_doubles import FakeDocumentRepository


def _server() -> MCPServer:
    settings = Settings()
    return build_mcp_server(
        documents=FakeDocumentRepository(),  # type: ignore[arg-type]
        retrieval=RetrievalService(strategy=FakeRetrievalStrategy(), settings=settings),
    )


@pytest.mark.parametrize(
    "not_a_server",
    ["https://mcp.attacker.example/sse", "python -m evil_server", {"url": "http://x"}, None],
)
async def test_only_the_in_process_transport_is_accepted(not_a_server: Any) -> None:
    with pytest.raises(MCPServerNotTrustedError, match="in-process"):
        await discover_mcp_tools(server=not_a_server, settings=Settings())

    assert await discover_mcp_tool_definitions(server=not_a_server, settings=Settings()) == []


async def test_a_server_with_another_name_is_refused_even_if_allowlisted() -> None:
    impostor = MCPServer("look-alike")
    settings = Settings(trusted_mcp_servers=[MCP_SERVER_NAME, "look-alike"])

    with pytest.raises(MCPServerNotTrustedError):
        await discover_mcp_tools(server=impostor, settings=settings)


async def test_the_real_server_is_refused_when_it_is_not_allowlisted() -> None:
    assert (
        await discover_mcp_tool_definitions(
            server=_server(), settings=Settings(trusted_mcp_servers=[])
        )
        == []
    )


async def test_a_mismatched_reported_identity_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        Client,
        "server_info",
        property(lambda self: Implementation(name="someone-else", version="1")),
    )

    with pytest.raises(MCPServerNotTrustedError, match="reported identity"):
        await discover_mcp_tools(server=_server(), settings=Settings())


def test_a_session_that_reports_no_identity_falls_back_to_the_checked_object() -> None:
    # Newer protocol versions may omit serverInfo; the in-process object was already checked.
    ensure_reported_identity_matches(None, expected=MCP_SERVER_NAME)
    with pytest.raises(MCPServerNotTrustedError):
        ensure_reported_identity_matches("other", expected=MCP_SERVER_NAME)


async def test_the_local_server_still_provides_only_allowlisted_prefixed_tools() -> None:
    settings = Settings()

    definitions = await discover_mcp_tool_definitions(server=_server(), settings=settings)

    assert definitions  # MCP still works
    for definition in definitions:
        assert definition.name.startswith(MCP_TOOL_NAME_PREFIX)
        assert definition.name.removeprefix(MCP_TOOL_NAME_PREFIX) in settings.trusted_mcp_tools
        # Arguments stay schema-validated with unknown fields refused.
        assert definition.args_schema.model_config.get("extra") == "forbid"
