"""Builds the AegisAI MCP server.

The MCP server does not duplicate business logic: each tool adapter
reconstructs the exact same Pydantic `args_schema` and calls the exact
same `executor` that `app.agents.tools.registry.build_tool_registry`
registers for the internal agent — the MCP boundary is a thin protocol
adapter over the same `ToolDefinition`s, not a second implementation.

One MCP-SDK-level constraint shapes this: a tool function whose single
parameter is a Pydantic model gets a *nested* JSON schema (`{"args": {...}}`)
from the installed `mcp` SDK (verified empirically — see ADR 009), which
would not match the flat schema the LLM already expects from the internal
tool. Each adapter below therefore takes the same fields as plain,
individually-typed parameters, reconstructs the shared `args_schema`
internally, and calls the shared `executor` — so arguments are validated
by the *same* Pydantic model either way, just assembled from flat kwargs
instead of a single model argument.
"""

from __future__ import annotations

import uuid

import structlog
from mcp.server.mcpserver import MCPServer

from app.agents.tools.base import ToolResult
from app.agents.tools.calculator import CALCULATOR_TOOL, CalculatorArgs
from app.agents.tools.document_metadata import DocumentMetadataArgs, build_document_metadata_tool
from app.agents.tools.knowledge_base import KnowledgeBaseSearchArgs, build_knowledge_base_tool
from app.db.repositories.document_repository import DocumentRepository
from app.rag.retrieval.service import RetrievalService

MCP_SERVER_NAME = "aegisai-internal"

logger = structlog.get_logger(__name__)


def build_mcp_server(*, documents: DocumentRepository, retrieval: RetrievalService) -> MCPServer:
    server = MCPServer(
        name=MCP_SERVER_NAME,
        version="1.0.0",
        instructions=(
            "Exposes a subset of AegisAI's internal capabilities "
            "(knowledge-base search, a safe calculator, document metadata "
            "lookup) over the Model Context Protocol."
        ),
    )
    logger.info("mcp.server_started", server_name=MCP_SERVER_NAME)

    metadata_tool = build_document_metadata_tool(documents)
    knowledge_base_tool = build_knowledge_base_tool(retrieval)

    @server.tool(name="calculator", description=CALCULATOR_TOOL.description)
    async def calculator(expression: str) -> dict:
        result = await CALCULATOR_TOOL.executor(CalculatorArgs(expression=expression))
        return _tool_result_to_dict(result)

    @server.tool(name="get_document_metadata", description=metadata_tool.description)
    async def get_document_metadata(document_id: str) -> dict:
        result = await metadata_tool.executor(
            DocumentMetadataArgs(document_id=uuid.UUID(document_id))
        )
        return _tool_result_to_dict(result)

    @server.tool(name="search_knowledge_base", description=knowledge_base_tool.description)
    async def search_knowledge_base(
        query: str, document_id: str | None = None, top_k: int | None = None
    ) -> dict:
        result = await knowledge_base_tool.executor(
            KnowledgeBaseSearchArgs(
                query=query,
                document_id=uuid.UUID(document_id) if document_id else None,
                top_k=top_k,
            )
        )
        return _tool_result_to_dict(result)

    _register_document_resource(server, documents)

    return server


def _tool_result_to_dict(result: ToolResult) -> dict:
    """Converts a `ToolResult` into the plain dict an MCP tool function
    returns. Successes carry `data` flattened to the top level (so the
    MCP client sees the same shape the internal tool's `ToolResult.data`
    already has); failures raise, so the MCP SDK's own error path (a safe,
    generic `is_error=True` result — see ADR 009) handles them, rather
    than this module inventing a second error envelope."""
    if not result.success:
        raise RuntimeError(result.error or "Tool execution failed")
    return result.data or {}


def _register_document_resource(server: MCPServer, documents: DocumentRepository) -> None:
    """Exposes `document://{document_id}` — safe document metadata only
    (never raw embeddings, filesystem paths, or internal configuration),
    reusing the exact same repository call the `get_document_metadata`
    tool and Milestone 3's own API already make."""

    @server.resource(
        "document://{document_id}",
        name="document_metadata",
        description="Safe metadata for one ingested document, by id.",
        mime_type="application/json",
    )
    async def document_resource(document_id: str) -> dict:
        document = await documents.get(uuid.UUID(document_id))
        if document is None:
            raise ValueError(f"No document found with id {document_id}")
        return {
            "document_id": str(document.id),
            "filename": document.original_filename,
            "document_type": document.document_type.value,
            "status": document.status.value,
            "page_count": document.page_count,
            "character_count": document.character_count,
            "created_at": document.created_at.isoformat(),
        }
