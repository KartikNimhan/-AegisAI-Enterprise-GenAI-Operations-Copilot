"""Builds the single `ToolRegistry` the agent graph is allowed to call
into. This is the one place all tool categories are assembled — internal
(Milestone 6), MCP-discovered, and the A2A Research Agent delegation
(Milestone 7) — the explicit allowlist the brief requires: nothing joins
the registry without being added here.

Building the registry is `async` (unlike Milestone 6) because MCP tool
discovery requires an awaited round-trip to the MCP server — see
`app.mcp.client.discover_mcp_tool_definitions`, which never raises: MCP
being unavailable or misconfigured degrades to "no MCP tools" rather than
breaking agent construction.
"""

from __future__ import annotations

from app.agents.tools.base import ToolRegistry
from app.agents.tools.calculator import CALCULATOR_TOOL
from app.agents.tools.document_metadata import build_document_metadata_tool
from app.agents.tools.knowledge_base import build_knowledge_base_tool
from app.agents.tools.research_delegation import build_research_delegation_tool
from app.config import Settings
from app.db.repositories.document_repository import DocumentRepository
from app.mcp.client import discover_mcp_tool_definitions
from app.mcp.server import build_mcp_server
from app.rag.retrieval.service import RetrievalService


async def build_tool_registry(
    *, documents: DocumentRepository, retrieval: RetrievalService, settings: Settings
) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(CALCULATOR_TOOL)
    registry.register(build_document_metadata_tool(documents))
    registry.register(build_knowledge_base_tool(retrieval))
    registry.register(build_research_delegation_tool(settings))

    mcp_server = build_mcp_server(documents=documents, retrieval=retrieval)
    mcp_tools = await discover_mcp_tool_definitions(server=mcp_server, settings=settings)
    for tool in mcp_tools:
        registry.register(tool)

    return registry
