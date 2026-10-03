"""AegisAI Streamlit UI — foundation milestone.

This currently only verifies backend connectivity. Chat, document upload,
and agent interaction pages are reserved for future milestones (see
docs/architecture/decisions/) and are intentionally not implemented here.
"""

import streamlit as st

from services.api_client import check_backend_readiness

st.set_page_config(page_title="AegisAI Copilot", page_icon=":shield:")

st.title("AegisAI — Enterprise GenAI Operations Copilot")
st.caption(
    "Foundation milestone: this UI only verifies backend connectivity today. "
    "Chat, RAG, and agent features are not implemented yet."
)

if st.button("Check backend health"):
    try:
        status_code, payload = check_backend_readiness()
        if status_code == 200:
            st.success("Backend is ready")
        else:
            st.warning(f"Backend reported degraded status ({status_code})")
        st.json(payload)
    except Exception as exc:
        st.error(f"Could not reach backend: {exc}")
