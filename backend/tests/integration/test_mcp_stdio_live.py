"""Opt-in integration test against the real MCP stdio transport.

Spawns `scripts/mcp_stdio_server.py` as a real subprocess (not the
in-process `Client(server)` transport `app.mcp.client` and
tests/unit/mcp/ use) and talks to it exactly the way an external MCP
client (the MCP Inspector, Claude Desktop) would — proving the stdio
entrypoint actually works end-to-end, over a real OS process boundary,
against the real Postgres database.

Skips automatically unless both `RUN_MCP_STDIO_INTEGRATION` is set and
Postgres is reachable — a real DB and an extra subprocess are never
required for a normal `pytest` run.

Run explicitly via:
    RUN_MCP_STDIO_INTEGRATION=1 uv run pytest -m mcp_integration -v
"""

from __future__ import annotations

import os
import sys

import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

from app.db.session import check_database

pytestmark = [
    pytest.mark.mcp_integration,
    pytest.mark.skipif(
        not os.environ.get("RUN_MCP_STDIO_INTEGRATION"),
        reason="RUN_MCP_STDIO_INTEGRATION is not set — skipping the real MCP stdio transport test",
    ),
]


@pytest.fixture
async def stdio_params() -> StdioServerParameters:
    if not await check_database(timeout=2.0):
        pytest.skip("Postgres is not reachable — start it via `docker compose up -d postgres`")
    return StdioServerParameters(command=sys.executable, args=["scripts/mcp_stdio_server.py"])


async def test_stdio_server_lists_the_three_tools(stdio_params: StdioServerParameters) -> None:
    async with Client(stdio_params) as client:
        result = await client.list_tools()

    assert {t.name for t in result.tools} == {
        "calculator",
        "get_document_metadata",
        "search_knowledge_base",
    }


async def test_stdio_server_executes_the_calculator_tool(
    stdio_params: StdioServerParameters,
) -> None:
    async with Client(stdio_params) as client:
        result = await client.call_tool("calculator", {"expression": "7 * 6"})

    assert result.is_error is not True


@pytest.mark.skipif(
    not os.environ.get("RUN_EMBEDDING_INTEGRATION"),
    reason=(
        "RUN_EMBEDDING_INTEGRATION is not set — skipping the real embedding "
        "model call this tool makes (downloads/loads the real model on first run)"
    ),
)
async def test_stdio_server_executes_search_knowledge_base_against_real_postgres(
    stdio_params: StdioServerParameters,
) -> None:
    async with Client(stdio_params) as client:
        result = await client.call_tool(
            "search_knowledge_base", {"query": "a query unlikely to match anything real"}
        )

    # Asserts the real round trip to Postgres succeeded, not any particular
    # content — an empty knowledge base is a valid outcome in CI.
    assert result.is_error is not True
