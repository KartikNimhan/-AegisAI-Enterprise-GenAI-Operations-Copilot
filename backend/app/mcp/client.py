"""The MCP client/adapter boundary: discovers tools from the AegisAI MCP
server, validates them against an explicit allowlist, and wraps each
approved one as an `app.agents.tools.base.ToolDefinition` the agent's
`ToolRegistry` can register — the same abstraction internal tools use, so
the graph/registry/agent code needs no special case for "this tool came
from MCP."

Transport: the in-process `mcp.client.Client(server_instance)` connect
mode — a first-class, SDK-documented way to talk to an `MCPServer` object
directly via an in-memory stream pair, not a workaround. This project's
MCP server and the agent that calls it live in the same process (a
reference implementation demonstrating the MCP *boundary*, not a
deployment topology), so there is no real network hop to make; see
ADR 009, "MCP transport", for why this is the right choice here and what
an external MCP client (e.g. the MCP Inspector) would use instead
(`server.run_stdio_async()`, also implemented — see `scripts/mcp_stdio_server.py`).
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import structlog
from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from mcp.types import TextContent
from pydantic import BaseModel, ConfigDict, Field, create_model

from app.agents.tools.base import ToolDefinition, ToolResult
from app.config import Settings
from app.mcp.exceptions import (
    MCPError,
    MCPServerNotTrustedError,
    MCPTimeoutError,
    MCPToolDiscoveryError,
    MCPToolNotTrustedError,
)
from app.mcp.server import MCP_SERVER_NAME

logger = structlog.get_logger(__name__)

MCP_TOOL_NAME_PREFIX = "mcp_"

_JSON_SCHEMA_TYPES: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def ensure_tool_trusted(tool_name: str, *, settings: Settings) -> None:
    """Raises `MCPToolNotTrustedError` unless `tool_name` is explicitly
    allowlisted — a discovered tool is never registered just because the
    server returned it."""
    if tool_name not in settings.trusted_mcp_tools:
        raise MCPToolNotTrustedError(f"MCP tool {tool_name!r} is not in trusted_mcp_tools")


async def discover_mcp_tools(*, server: MCPServer, settings: Settings) -> list[Any]:
    """Connects to `server` and lists its tools, enforcing the server-level
    allowlist first. Raises a typed `MCPError` on any failure — callers
    that want the "MCP being unavailable must not break the agent"
    guarantee (i.e. `discover_mcp_tool_definitions` below) catch it; a unit
    test that wants to assert the failure mode directly can call this
    function itself instead.
    """
    if MCP_SERVER_NAME not in settings.trusted_mcp_servers:
        raise MCPServerNotTrustedError(
            f"MCP server {MCP_SERVER_NAME!r} is not in trusted_mcp_servers"
        )

    try:
        # `except*` (not plain `except`): cancelling `client.list_tools()` via
        # `wait_for` while still inside `Client`'s `async with` block means the
        # client session's internal anyio TaskGroup re-wraps the cancellation
        # as a `BaseExceptionGroup` during its own `__aexit__` — a plain
        # `except TimeoutError` would never match it, silently misreporting
        # every real timeout as a generic connection failure.
        async with Client(server) as client:
            result = await asyncio.wait_for(
                client.list_tools(), timeout=settings.mcp_client_timeout_seconds
            )
    except* TimeoutError as excgroup:
        raise MCPTimeoutError("MCP tool discovery timed out") from excgroup
    except* Exception as excgroup:
        raise MCPToolDiscoveryError(
            f"MCP tool discovery failed: {excgroup.exceptions[0]}"
        ) from excgroup

    return result.tools


async def discover_mcp_tool_definitions(
    *, server: MCPServer, settings: Settings
) -> list[ToolDefinition]:
    """The resilient wrapper `get_agent_service` actually uses: never
    raises, so the agent still has its internal tools even if MCP is
    unavailable or misconfigured (see ADR 008/009, "M6 must keep
    working") — only a tool that passes *both* the server and the
    tool-name allowlist is ever turned into a `ToolDefinition`.
    """
    try:
        discovered_tools = await discover_mcp_tools(server=server, settings=settings)
    except MCPServerNotTrustedError:
        logger.warning("mcp.server_not_trusted", server_name=MCP_SERVER_NAME)
        return []
    except MCPError:
        logger.exception("mcp.tool_discovery_failed", server_name=MCP_SERVER_NAME)
        return []

    definitions: list[ToolDefinition] = []
    for discovered in discovered_tools:
        try:
            ensure_tool_trusted(discovered.name, settings=settings)
        except MCPToolNotTrustedError:
            logger.warning(
                "mcp.tool_not_trusted",
                server_name=MCP_SERVER_NAME,
                tool_name=discovered.name,
            )
            continue
        try:
            definitions.append(_to_tool_definition(discovered, server=server, settings=settings))
            logger.info(
                "mcp.tool_discovered", server_name=MCP_SERVER_NAME, tool_name=discovered.name
            )
        except Exception:
            logger.exception(
                "mcp.tool_discovery_failed",
                server_name=MCP_SERVER_NAME,
                tool_name=discovered.name,
            )

    return definitions


def _to_tool_definition(
    discovered: Any, *, server: MCPServer, settings: Settings
) -> ToolDefinition:
    args_schema = _model_from_json_schema(discovered.name, discovered.input_schema)
    exposed_name = f"{MCP_TOOL_NAME_PREFIX}{discovered.name}"
    executor = _make_mcp_executor(
        server=server,
        tool_name=discovered.name,
        timeout_seconds=settings.mcp_client_timeout_seconds,
    )
    return ToolDefinition(
        name=exposed_name,
        description=f"(via MCP) {discovered.description or discovered.name}",
        args_schema=args_schema,
        executor=executor,
    )


def _model_from_json_schema(tool_name: str, schema: dict[str, Any]) -> type[BaseModel]:
    """Builds a Pydantic model from a *discovered* (not hand-written) flat
    JSON schema, so arguments are validated against what the server
    actually advertised — not a hardcoded assumption about which tool this
    is. Covers the common JSON Schema scalar/array/object types; anything
    unrecognized falls back to `Any` rather than rejecting the whole tool,
    since a stricter fallback would make discovery brittle against a
    server advertising a field type this small mapping doesn't know.
    """
    properties: dict[str, Any] = schema.get("properties", {})
    required: set[str] = set(schema.get("required", []))

    fields: dict[str, Any] = {}
    for field_name, field_schema in properties.items():
        python_type = _JSON_SCHEMA_TYPES.get(field_schema.get("type"), Any)
        if field_name in required:
            fields[field_name] = (python_type, Field(...))
        else:
            fields[field_name] = (python_type | None, Field(default=None))

    model = create_model(
        f"MCP{tool_name.title().replace('_', '')}Args",
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )
    return model


def _make_mcp_executor(*, server: MCPServer, tool_name: str, timeout_seconds: float):
    """Each call opens its own short-lived `Client(server)` connection —
    simpler than keeping one open for the lifetime of an `AgentService`
    instance, and cheap over the in-process transport (no real network
    handshake)."""

    async def _execute(args: BaseModel) -> ToolResult:
        arguments = args.model_dump(exclude_none=True)
        logger.info("mcp.tool_call", tool_name=tool_name)
        start = time.perf_counter()
        # `except*` can't itself `return` (Python disallows break/continue/
        # return inside an `except*` block), so each branch stores an
        # outcome here instead and the function returns it right after.
        failure: ToolResult | None = None
        try:
            # `except*` (not plain `except`): see the matching comment in
            # `discover_mcp_tools` — cancelling the call via `wait_for`
            # inside `Client`'s `async with` block re-wraps the
            # `TimeoutError` as a `BaseExceptionGroup`, which a plain
            # `except TimeoutError` would never match.
            async with Client(server) as client:
                result = await asyncio.wait_for(
                    client.call_tool(tool_name, arguments), timeout=timeout_seconds
                )
        except* TimeoutError:
            logger.warning(
                "mcp.tool_failed",
                tool_name=tool_name,
                error_category="timeout",
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )
            failure = ToolResult(
                success=False,
                error="The MCP tool call timed out",
                error_code="transient_error",
            )
        except* Exception:
            logger.exception(
                "mcp.tool_failed",
                tool_name=tool_name,
                error_category="connection",
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )
            failure = ToolResult(
                success=False,
                error="The MCP server is unavailable",
                error_code="transient_error",
            )

        if failure is not None:
            return failure

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        text = _first_text(result.content)
        if result.is_error:
            logger.warning(
                "mcp.tool_failed",
                tool_name=tool_name,
                error_category="execution",
                duration_ms=duration_ms,
            )
            return ToolResult(
                success=False, error=text or "MCP tool call failed", error_code="internal_error"
            )

        payload: dict[str, Any] = {}
        if text is not None:
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = {"result": text}

        logger.info("mcp.tool_completed", tool_name=tool_name, duration_ms=duration_ms)
        return ToolResult(success=True, data=payload)

    return _execute


def _first_text(content: list[Any]) -> str | None:
    for item in content:
        if isinstance(item, TextContent):
            return item.text
    return None
