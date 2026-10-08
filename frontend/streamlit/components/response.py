"""Renders one Copilot response: the answer is primary; sources and
workflow/agent status are secondary, collapsed by default. Never renders
chain-of-thought, a system prompt, raw tool arguments, or a raw
correlation id outside the "Technical details" expander — see
docs/architecture/decisions/011-copilot-ui-architecture.md, "Security
boundaries."

Source shape is not fixed across agents (Research: chunk/document/page/
similarity; Document: document metadata; Analyst: a calculation, not
evidence) — this only ever renders fields the backend actually sent,
never inventing one.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from services.api.copilot import AgentStatus, MultiAgentRunResult

_WORKFLOW_STATUS = {
    "completed": ("✅", "Completed", "success"),
    "partial": ("⚠️", "Partial — some agents did not complete", "warning"),
    "failed": ("❌", "Failed", "error"),
    "timeout": ("⏱️", "Timed out", "warning"),
}

_AGENT_STATUS_ICON = {
    "completed": "✅",
    "failed": "❌",
    "timeout": "⏱️",
    "unauthorized": "🚫",
}


def render_response(result: MultiAgentRunResult) -> None:
    icon, label, kind = _WORKFLOW_STATUS.get(result.status, ("ℹ️", result.status.title(), "info"))

    if result.answer.strip():
        st.markdown(result.answer)
        if result.status != "completed":
            getattr(st, kind)(f"{icon} {label}")
    else:
        # Never invent an answer when the backend reported no usable result.
        getattr(st, kind)(f"{icon} {label} — no answer was produced for this request.")

    if result.sources:
        with st.expander(f"Sources ({len(result.sources)})"):
            for source in result.sources:
                _render_source(source)

    if result.agents_used:
        with st.expander("Workflow"):
            for agent in result.agents_used:
                _render_agent_status(agent)
            st.caption(f"Status: {label} · Duration: {result.duration_ms:.0f} ms")
            if result.token_usage:
                st.caption(
                    "Tokens — input: {input}, output: {output}, total: {total}".format(
                        input=result.token_usage.get("input_tokens", "—"),
                        output=result.token_usage.get("output_tokens", "—"),
                        total=result.token_usage.get("total_tokens", "—"),
                    )
                )
            st.caption(
                f"workflow id: `{result.workflow_id}` · correlation id: `{result.correlation_id}`"
            )


def _render_agent_status(agent: AgentStatus) -> None:
    icon = _AGENT_STATUS_ICON.get(agent.status, "•")
    line = f"{icon} **{agent.agent_name.title()}** — {agent.status.title()}"
    if agent.retry_count:
        line += f" (retried {agent.retry_count}x)"
    st.markdown(line)
    if agent.error:
        st.caption(agent.error)


def _render_source(source: dict[str, Any]) -> None:
    agent_name = source.get("agent_name", "")
    if "expression" in source:
        # An Analyst calculation — not a document/evidence source.
        status_icon = "✅" if source.get("success") else "❌"
        st.markdown(f"{status_icon} `{source['expression']}` = {source.get('result', '—')}")
        return

    filename = source.get("filename")
    line = f"📄 **{filename}**" if filename else "📄 Document"
    page = source.get("page_number")
    if page is not None:
        line += f" · page {page}"
    st.markdown(line)

    meta_bits = []
    similarity = source.get("similarity")
    if similarity is not None:
        meta_bits.append(f"similarity: {similarity:.2f}")
    document_id = source.get("document_id")
    if document_id:
        meta_bits.append(f"document id: `{document_id}`")
    if agent_name:
        meta_bits.append(f"via {agent_name}")
    if meta_bits:
        st.caption(" · ".join(meta_bits))
