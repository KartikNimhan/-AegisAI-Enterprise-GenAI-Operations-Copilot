"""Tests for the main Copilot page (`app.py`).

No real backend/network/Groq is involved — `services.api.copilot
.run_multi_agent_workflow` is monkeypatched to return deterministic,
backend-shaped data (or raise `BackendError`), the same contract
`app.api.schemas.multi_agent.MultiAgentRunResponse` defines.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

import services.api.copilot as copilot_api
from services.api.client import BackendError
from services.api.copilot import AgentStatus, MultiAgentRunResult

_APP_PATH = str(Path(__file__).resolve().parents[1] / "app.py")


def _result(**overrides: object) -> MultiAgentRunResult:
    defaults: dict[str, Any] = {
        "workflow_id": "wf-1",
        "correlation_id": "corr-1",
        "status": "completed",
        "answer": "Hotels are reimbursed up to policy limits.",
        "agents_used": [
            AgentStatus(
                agent_name="research",
                capability="research",
                status="completed",
                error=None,
                duration_ms=12.5,
                retry_count=0,
            )
        ],
        "sources": [
            {
                "agent_name": "research",
                "filename": "Travel Policy.pdf",
                "page_number": 4,
                "similarity": 0.87,
                "document_id": "11111111-1111-1111-1111-111111111111",
            }
        ],
        "token_usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
        "duration_ms": 350.0,
    }
    defaults.update(overrides)
    return MultiAgentRunResult(**defaults)


def test_empty_state_shown_before_any_message() -> None:
    at = AppTest.from_file(_APP_PATH)
    at.run(timeout=30)

    assert at.exception.len == 0
    assert any("No messages yet" in i.value for i in at.info)
    assert len(at.chat_message) == 0


def test_accepts_a_message_and_renders_a_successful_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(copilot_api, "run_multi_agent_workflow", lambda message: _result())

    at = AppTest.from_file(_APP_PATH)
    at.run(timeout=30)
    at.chat_input[0].set_value("What does the travel policy say?").run(timeout=30)

    assert at.exception.len == 0
    roles = [cm.name for cm in at.chat_message]
    assert roles == ["user", "assistant"]
    assistant_markdown = " ".join(md.value for md in at.chat_message[1].markdown)
    assert "Hotels are reimbursed" in assistant_markdown


def test_renders_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(copilot_api, "run_multi_agent_workflow", lambda message: _result())

    at = AppTest.from_file(_APP_PATH)
    at.run(timeout=30)
    at.chat_input[0].set_value("What does the travel policy say?").run(timeout=30)

    assistant = at.chat_message[1]
    rendered = " ".join(md.value for md in assistant.markdown)
    assert "Travel Policy.pdf" in rendered
    assert "page 4" in rendered


def test_renders_agent_workflow_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(copilot_api, "run_multi_agent_workflow", lambda message: _result())

    at = AppTest.from_file(_APP_PATH)
    at.run(timeout=30)
    at.chat_input[0].set_value("What does the travel policy say?").run(timeout=30)

    assistant = at.chat_message[1]
    rendered = " ".join(md.value for md in assistant.markdown)
    assert "Research" in rendered
    assert "Completed" in rendered


def test_renders_partial_workflow_without_claiming_full_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    partial_result = _result(
        status="partial",
        answer="Found evidence, but one agent did not complete.",
        agents_used=[
            AgentStatus(
                agent_name="research",
                capability="research",
                status="completed",
                error=None,
                duration_ms=10.0,
                retry_count=0,
            ),
            AgentStatus(
                agent_name="document",
                capability="document_analysis",
                status="failed",
                error="Document not found",
                duration_ms=5.0,
                retry_count=0,
            ),
        ],
    )
    monkeypatch.setattr(copilot_api, "run_multi_agent_workflow", lambda message: partial_result)

    at = AppTest.from_file(_APP_PATH)
    at.run(timeout=30)
    at.chat_input[0].set_value("Compare the policy with a document").run(timeout=30)

    assistant = at.chat_message[1]
    rendered = " ".join(md.value for md in assistant.markdown)
    warnings = " ".join(w.value for w in assistant.warning)
    assert "Document" in rendered
    assert "Failed" in rendered
    assert "Partial" in warnings


def test_renders_failed_workflow_without_fabricating_an_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed_result = _result(status="failed", answer="", agents_used=[], sources=[])
    monkeypatch.setattr(copilot_api, "run_multi_agent_workflow", lambda message: failed_result)

    at = AppTest.from_file(_APP_PATH)
    at.run(timeout=30)
    at.chat_input[0].set_value("Research something unavailable").run(timeout=30)

    assistant = at.chat_message[1]
    errors = " ".join(e.value for e in assistant.error)
    assert "Failed" in errors
    assert "no answer was produced" in errors.lower()


def test_handles_a_backend_error_without_crashing(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(message: str) -> MultiAgentRunResult:
        raise BackendError("The backend did not respond in time. Please try again.", code="timeout")

    monkeypatch.setattr(copilot_api, "run_multi_agent_workflow", _raise)

    at = AppTest.from_file(_APP_PATH)
    at.run(timeout=30)
    at.chat_input[0].set_value("Research the travel policy").run(timeout=30)

    assert at.exception.len == 0
    assistant = at.chat_message[1]
    errors = " ".join(e.value for e in assistant.error)
    assert "did not respond in time" in errors


def test_e2e_happy_path_question_to_answer_sources_and_agent_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one focused happy-path test: enter a question, the backend
    returns a known, deterministic response (no real Groq/network), and
    the answer, its sources, and the agent/workflow status are all
    visible on the page. No separate E2E framework is introduced — the
    real `app.py` script, run end-to-end through `AppTest`, already
    covers "page loads, user types, backend responds, UI renders" without
    a browser."""
    monkeypatch.setattr(copilot_api, "run_multi_agent_workflow", lambda message: _result())

    at = AppTest.from_file(_APP_PATH)
    at.run(timeout=30)
    at.chat_input[0].set_value("What does our travel policy say about hotel reimbursement?")
    at.run(timeout=30)

    assert at.exception.len == 0
    assistant = at.chat_message[1]
    rendered = " ".join(md.value for md in assistant.markdown)
    assert "Hotels are reimbursed up to policy limits." in rendered  # answer
    assert "Travel Policy.pdf" in rendered  # sources
    assert "Research" in rendered and "Completed" in rendered  # agent status


def test_new_conversation_button_clears_history(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(copilot_api, "run_multi_agent_workflow", lambda message: _result())

    at = AppTest.from_file(_APP_PATH)
    at.run(timeout=30)
    at.chat_input[0].set_value("What does the travel policy say?").run(timeout=30)
    assert len(at.chat_message) == 2

    at.sidebar.button[0].click().run(timeout=30)

    assert len(at.chat_message) == 0
