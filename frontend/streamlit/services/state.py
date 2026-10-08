"""Session-state helpers for the Copilot page's message history.

The M8 multi-agent endpoint is stateless (no `conversation_id`, no
server-side persistence — see
docs/architecture/decisions/010-multi-agent-architecture.md): history is
kept client-side, per browser session, so the conversation remains
visible across turns without inventing a backend conversation API that
doesn't exist for M8. This is intentionally the *only* state this
frontend keeps — see
docs/architecture/decisions/011-copilot-ui-architecture.md, "State
management."
"""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from services.api.copilot import MultiAgentRunResult

_HISTORY_KEY = "copilot_history"


@dataclass(frozen=True)
class ChatTurn:
    role: str  # "user" | "assistant"
    content: str
    result: MultiAgentRunResult | None = None
    error: str | None = None


def get_history() -> list[ChatTurn]:
    if _HISTORY_KEY not in st.session_state:
        st.session_state[_HISTORY_KEY] = []
    return st.session_state[_HISTORY_KEY]


def append_turn(turn: ChatTurn) -> None:
    get_history().append(turn)


def clear_history() -> None:
    st.session_state[_HISTORY_KEY] = []
