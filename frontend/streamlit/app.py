"""AegisAI Copilot — the main user-facing page.

Calls Milestone 8's multi-agent orchestration endpoint
(`POST /api/v1/multi-agent/run`) directly. This page performs no
routing, agent selection, or orchestration of its own — all of that
lives in the backend
(`app.multi_agent.orchestrator.MultiAgentOrchestrator`, see
docs/architecture/decisions/010-multi-agent-architecture.md); this page
is a thin client over that one endpoint, matching
docs/architecture/decisions/011-copilot-ui-architecture.md, "Why the
frontend does not perform orchestration."
"""

from __future__ import annotations

import streamlit as st

from components.errors import friendly_message
from components.response import render_response
from services.api.client import BackendError
from services.api.copilot import run_multi_agent_workflow
from services.state import ChatTurn, append_turn, clear_history, get_history

st.set_page_config(page_title="AegisAI Copilot", page_icon=":shield:", layout="wide")

st.title("AegisAI")
st.caption("Enterprise GenAI Operations Copilot")

with st.sidebar:
    st.subheader("Copilot")
    st.caption(
        "Ask a question — the Copilot decides whether it needs the "
        "Research, Document, or Analyst agent to answer it."
    )
    if st.button("New conversation", use_container_width=True):
        clear_history()
        st.rerun()

history = get_history()

if not history:
    st.info(
        "No messages yet. Ask about a policy, a document (paste its id "
        "from the Documents page), or a calculation."
    )

for turn in history:
    with st.chat_message(turn.role):
        if turn.role == "user":
            st.markdown(turn.content)
        elif turn.result is not None:
            render_response(turn.result)
        else:
            st.error(turn.error or "This request could not be completed.")

message = st.chat_input("Ask the Copilot...")
if message:
    append_turn(ChatTurn(role="user", content=message))
    with st.chat_message("user"):
        st.markdown(message)

    with st.chat_message("assistant"), st.spinner("Routing to the right agent(s)..."):
        try:
            result = run_multi_agent_workflow(message)
        except BackendError as exc:
            error_message = friendly_message(exc)
            st.error(error_message)
            append_turn(ChatTurn(role="assistant", content="", error=error_message))
        else:
            render_response(result)
            append_turn(ChatTurn(role="assistant", content=result.answer, result=result))
