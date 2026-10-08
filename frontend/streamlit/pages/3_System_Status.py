"""System status page — reuses existing health/readiness semantics.

`database`/`redis` are live connectivity checks (the same ones
`/health/ready` performs). `llm_configured`/`trusted_a2a_agents`/
`mcp_server` are configuration facts, not live probes — shown separately
and labeled as such, never presented as "healthy" just because the page
loaded (see `app.api.schemas.system`'s own docstring).
"""

from __future__ import annotations

import streamlit as st

from components.errors import friendly_message
from services.api.client import BackendError
from services.api.system import get_system_status

st.set_page_config(page_title="System Status — AegisAI", page_icon=":satellite:", layout="wide")
st.title("System Status")

try:
    status = get_system_status()
except BackendError as exc:
    st.error(friendly_message(exc))
    st.stop()

st.subheader("Live connectivity")
cols = st.columns(2)
checks = [("Database", status.database), ("Redis", status.redis)]
for col, (label, value) in zip(cols, checks, strict=True):
    if value == "ok":
        col.success(f"{label}: reachable")
    else:
        col.error(f"{label}: unavailable")

st.subheader("Configuration")
st.caption("These reflect configuration, not a live provider call.")
if status.llm_configured:
    st.success("LLM provider (Groq): API key configured")
else:
    st.warning("LLM provider (Groq): no API key configured — chat/agent requests will fail")

st.write(f"MCP server: `{status.mcp_server}` (in-process)")
if status.trusted_a2a_agents:
    st.write("Trusted A2A agents:")
    for agent_url in status.trusted_a2a_agents:
        st.markdown(f"- `{agent_url}`")
else:
    st.write("Trusted A2A agents: none configured")
