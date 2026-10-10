"""Unit tests for the `/api/v1/agents/research/tasks` endpoint's error
handling: an `LLMError` (e.g. missing/invalid GROQ_API_KEY) must surface a
clear, typed failure message, and an unexpected exception must be logged
with a real, readable traceback — not silently reduced to
`"error_type": "internal"` with no diagnostic information (see
app.core.logging._SHARED_PROCESSORS: `structlog.processors.format_exc_info`
renders `logger.exception(...)` into an actual `"exception"` string field).
"""

from __future__ import annotations

import structlog
from fastapi.testclient import TestClient

from app.a2a.research_agent import ResearchAgentService
from app.api.v1.research_agent import get_research_agent_service
from app.llm.exceptions import LLMAuthenticationError
from app.main import app


class _RaisingResearchAgentService(ResearchAgentService):
    def __init__(self, *, error: Exception) -> None:
        self._error = error

    async def research(self, *, question: str) -> None:  # type: ignore[override]
        raise self._error


def _override(service: ResearchAgentService) -> None:
    app.dependency_overrides[get_research_agent_service] = lambda: service


def test_llm_error_returns_a_clear_typed_failure_message() -> None:
    _override(_RaisingResearchAgentService(error=LLMAuthenticationError("no key", provider="groq")))
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/agents/research/tasks", json={"question": "hi"})
    finally:
        app.dependency_overrides.pop(get_research_agent_service, None)

    assert response.status_code == 200
    task = response.json()
    message_parts = task["status"]["message"]["parts"]
    assert any(
        "language model is unavailable" in part.get("text", "") for part in message_parts
    )


def test_unexpected_exception_returns_a_generic_failure_message() -> None:
    """An unexpected (non-`LLMError`) exception must still surface as a
    clean task failure to the caller, never a 500 or a raw traceback."""
    _override(_RaisingResearchAgentService(error=ValueError("boom: unexpected failure")))
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/agents/research/tasks", json={"question": "hi"})
    finally:
        app.dependency_overrides.pop(get_research_agent_service, None)

    assert response.status_code == 200
    task = response.json()
    message_parts = task["status"]["message"]["parts"]
    assert any("failed to complete the task" in part.get("text", "") for part in message_parts)


def test_configure_logging_processor_chain_includes_format_exc_info() -> None:
    """Direct, implementation-level guard against regressing the logging
    fix: without `structlog.processors.format_exc_info` in the shared
    processor chain, `exc_info=True`/`logger.exception(...)` is serialized
    as the literal JSON boolean `true` and the real traceback is lost (this
    is exactly the production bug: logs only showed `"error_type":
    "internal"` with no way to diagnose the underlying exception)."""
    from app.core.logging import _SHARED_PROCESSORS

    assert structlog.processors.format_exc_info in _SHARED_PROCESSORS


def test_format_exc_info_renders_a_real_traceback_string() -> None:
    """Exercises the actual fix mechanism in isolation: an event dict with
    `exc_info=True`, built inside a real exception context (as
    `logger.exception(...)` produces), must come out of
    `structlog.processors.format_exc_info` with an `"exception"` field
    containing the real exception type and message — not the literal
    boolean `True` that was previously serialized as-is and lost."""
    try:
        raise ValueError("boom: unexpected failure")
    except ValueError:
        event_dict = structlog.processors.format_exc_info(
            None, "error", {"event": "a2a.task_failed", "error_type": "internal", "exc_info": True}
        )

    assert "exc_info" not in event_dict
    assert "exception" in event_dict
    assert "ValueError" in event_dict["exception"]
    assert "boom: unexpected failure" in event_dict["exception"]
