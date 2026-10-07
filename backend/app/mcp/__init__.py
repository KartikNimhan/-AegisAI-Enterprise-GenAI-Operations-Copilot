"""The AegisAI MCP (Model Context Protocol) server and client/adapter.

`server.py` builds an `MCPServer` exposing a subset of AegisAI's internal
tools (`calculator`, `get_document_metadata`, `search_knowledge_base`) and
one resource (`document://{document_id}`) over MCP — thin protocol
adapters over the same `ToolDefinition`s the internal agent registers, not
a second implementation. `client.py` discovers and validates those tools
against an explicit allowlist (`Settings.trusted_mcp_servers`/
`trusted_mcp_tools`) and wraps each approved one as a `ToolDefinition` the
agent's `ToolRegistry` can register alongside its internal and A2A tools.

Implemented in Milestone 7 — see
docs/architecture/decisions/009-mcp-a2a-architecture.md.
"""
