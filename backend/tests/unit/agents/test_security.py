"""Security tests: the agent's tool system has no path to arbitrary code
execution, shell access, raw SQL, or unrestricted HTTP — by construction,
not by convention.

Most of the depth here (no `eval`/`exec`, AST-only arithmetic, bounded
operand/exponent magnitudes) lives in test_calculator.py; this file
verifies the registry-level guarantee: only the explicitly registered
tools exist at all (internal, MCP-discovered, and the A2A delegation
tool), and none of them expose a dangerous capability.
"""

from __future__ import annotations

import inspect

from app.agents.tools.calculator import CALCULATOR_TOOL
from app.agents.tools.document_metadata import build_document_metadata_tool
from app.agents.tools.knowledge_base import build_knowledge_base_tool
from app.agents.tools.registry import build_tool_registry
from app.rag.retrieval.service import RetrievalService

from ..rag.doubles import FakeRetrievalStrategy
from ..services.document_doubles import FakeDocumentRepository


async def _make_registry():
    documents = FakeDocumentRepository()
    settings = _settings()
    retrieval = RetrievalService(strategy=FakeRetrievalStrategy(results=[]), settings=settings)
    return await build_tool_registry(
        documents=documents,  # type: ignore[arg-type]
        retrieval=retrieval,
        settings=settings,
    )


def _settings():
    from app.config import Settings

    return Settings(rag_top_k=5, rag_max_results=20, rag_similarity_threshold=0.3)


async def test_internal_mcp_and_a2a_tools_are_registered() -> None:
    registry = await _make_registry()
    names = {tool.name for tool in registry.list_tools()}
    assert names == {
        "calculator",
        "search_knowledge_base",
        "get_document_metadata",
        "delegate_to_research_agent",
        "mcp_calculator",
        "mcp_search_knowledge_base",
        "mcp_get_document_metadata",
    }


async def test_no_tool_name_suggests_arbitrary_execution() -> None:
    registry = await _make_registry()
    forbidden_substrings = (
        "exec",
        "eval",
        "shell",
        "sql",
        "python",
        "subprocess",
        "http",
        "file",
    )
    for tool in registry.list_tools():
        lowered = tool.name.lower()
        for forbidden in forbidden_substrings:
            assert forbidden not in lowered, f"Tool name {tool.name!r} suggests {forbidden!r}"


def test_calculator_tool_source_never_references_eval_exec_or_subprocess() -> None:
    import app.agents.tools.calculator as calculator_module

    source = inspect.getsource(calculator_module)
    for forbidden in ("eval(", "exec(", "subprocess", "os.system", "__import__"):
        assert forbidden not in source


def test_document_metadata_tool_never_issues_raw_sql() -> None:
    import app.agents.tools.document_metadata as module

    source = inspect.getsource(module)
    for forbidden in ("session.execute", "sqlalchemy.text(", "raw_connection", ".cursor("):
        assert forbidden not in source


def test_knowledge_base_tool_never_issues_raw_sql_or_http() -> None:
    import app.agents.tools.knowledge_base as module

    source = inspect.getsource(module)
    for forbidden in ("session.execute", "sqlalchemy.text(", "requests.", "httpx.", "urlopen"):
        assert forbidden not in source


async def test_calling_an_unregistered_tool_name_is_impossible() -> None:
    """There is no path from a model-provided string to any Python
    callable other than what was explicitly registered — proven by
    exercising the registry with names that would be dangerous if the
    lookup were ever implemented as `getattr`/`globals()`/`eval` instead
    of a plain dict."""
    registry = await _make_registry()

    for dangerous_name in ("eval", "exec", "os.system", "subprocess.run", "__import__"):
        result = await registry.execute(dangerous_name, "{}")
        assert result.success is False
        assert result.error_code == "not_found"


async def test_calculator_tool_is_the_shared_global_instance() -> None:
    """The registry registers the same `CALCULATOR_TOOL` object everywhere
    — not a per-request reconstruction that could diverge in behavior."""
    registry = await _make_registry()
    assert registry.get("calculator") is CALCULATOR_TOOL


def test_tool_factories_require_explicit_dependencies_not_global_state() -> None:
    """`build_document_metadata_tool`/`build_knowledge_base_tool` take
    their repository/service as an explicit argument — there is no module-
    level singleton a compromised prompt could redirect to a different
    database or retrieval backend."""
    assert "documents" in inspect.signature(build_document_metadata_tool).parameters
    assert "retrieval" in inspect.signature(build_knowledge_base_tool).parameters
