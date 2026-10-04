"""Builds the single `ToolRegistry` the agent graph is allowed to call
into. This is the one place all three Milestone 6 tools are assembled —
the explicit allowlist the brief requires: nothing joins the registry
without being added here.
"""

from __future__ import annotations

from app.agents.tools.base import ToolRegistry
from app.agents.tools.calculator import CALCULATOR_TOOL
from app.agents.tools.document_metadata import build_document_metadata_tool
from app.agents.tools.knowledge_base import build_knowledge_base_tool
from app.db.repositories.document_repository import DocumentRepository
from app.rag.retrieval.service import RetrievalService


def build_tool_registry(
    *, documents: DocumentRepository, retrieval: RetrievalService
) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(CALCULATOR_TOOL)
    registry.register(build_document_metadata_tool(documents))
    registry.register(build_knowledge_base_tool(retrieval))
    return registry
