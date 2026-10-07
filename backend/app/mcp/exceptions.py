"""Typed exceptions for the MCP client/discovery boundary.

These are caught inside `app.mcp.client` and converted into
`app.agents.tools.base.ToolResult`s before ever reaching the agent graph —
an MCP failure is never allowed to crash the agent, the same guarantee
`ToolRegistry.execute` already gives internal tools (see ADR 008).
"""

from __future__ import annotations


class MCPError(Exception):
    """Base class for MCP-specific errors."""


class MCPServerNotTrustedError(MCPError):
    """The server's identity is not in `Settings.trusted_mcp_servers`."""


class MCPToolNotTrustedError(MCPError):
    """A discovered tool's name is not in `Settings.trusted_mcp_tools` —
    it is dropped during discovery, never registered with the agent."""


class MCPToolDiscoveryError(MCPError):
    """Listing tools from the MCP server failed."""


class MCPTimeoutError(MCPError):
    """An MCP call exceeded `Settings.mcp_client_timeout_seconds`."""
