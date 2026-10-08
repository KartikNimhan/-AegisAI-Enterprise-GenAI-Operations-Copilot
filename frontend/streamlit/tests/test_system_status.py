"""Tests for the System Status page.

No real backend — `services.api.system.get_system_status` is
monkeypatched. Verifies the healthy/available and degraded/unavailable
states both render truthfully, and an API failure is handled gracefully.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import services.api.system as system_api
from services.api.client import BackendError
from services.api.system import SystemStatus

_PAGE_PATH = str(Path(__file__).resolve().parents[1] / "pages" / "3_System_Status.py")


def test_healthy_dependencies_render_as_available(monkeypatch: pytest.MonkeyPatch) -> None:
    status = SystemStatus(
        database="ok",
        redis="ok",
        llm_configured=True,
        trusted_a2a_agents=["http://localhost:8000"],
        mcp_server="aegisai-internal",
    )
    monkeypatch.setattr(system_api, "get_system_status", lambda: status)

    at = AppTest.from_file(_PAGE_PATH)
    at.run(timeout=30)

    assert at.exception.len == 0
    successes = " ".join(s.value for s in at.success)
    assert "Database" in successes
    assert "Redis" in successes
    assert "LLM provider" in successes


def test_degraded_dependencies_render_as_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    status = SystemStatus(
        database="unavailable",
        redis="unavailable",
        llm_configured=False,
        trusted_a2a_agents=[],
        mcp_server="aegisai-internal",
    )
    monkeypatch.setattr(system_api, "get_system_status", lambda: status)

    at = AppTest.from_file(_PAGE_PATH)
    at.run(timeout=30)

    assert at.exception.len == 0
    errors = " ".join(e.value for e in at.error)
    assert "Database" in errors
    assert "unavailable" in errors
    warnings = " ".join(w.value for w in at.warning)
    assert "no API key configured" in warnings


def test_api_failure_is_shown_as_an_error_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise():
        raise BackendError("Could not reach the backend.", code="network_error")

    monkeypatch.setattr(system_api, "get_system_status", _raise)

    at = AppTest.from_file(_PAGE_PATH)
    at.run(timeout=30)

    assert at.exception.len == 0
    assert any("Unable to reach the backend" in e.value for e in at.error)


def test_never_claims_healthy_without_a_real_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """The page must never render a blanket "healthy" claim — only the
    per-dependency statuses the backend actually reported."""
    status = SystemStatus(
        database="ok", redis="ok", llm_configured=True, trusted_a2a_agents=[], mcp_server="x"
    )
    monkeypatch.setattr(system_api, "get_system_status", lambda: status)

    at = AppTest.from_file(_PAGE_PATH)
    at.run(timeout=30)

    all_text = " ".join(
        t.value for group in (at.success, at.error, at.warning, at.markdown) for t in group
    )
    assert "all systems healthy" not in all_text.lower()
    assert "99.9%" not in all_text
