"""Operations dashboard — real data only.

Only `/api/v1/operations/summary` (document counts by status, derived
from persisted data) is shown. Copilot request/agent-execution counts
are deliberately **not** shown: the M8 multi-agent orchestrator does not
persist any workflow history (see
docs/architecture/decisions/010-multi-agent-architecture.md), so there is
no truthful source for those numbers yet — see
docs/architecture/decisions/011-copilot-ui-architecture.md, "Dashboard
data sources," for why this is an explicit omission, not an oversight.
"""

from __future__ import annotations

import streamlit as st

from components.errors import friendly_message
from services.api.client import BackendError
from services.api.operations import get_operations_summary

st.set_page_config(page_title="Operations — AegisAI", page_icon=":bar_chart:", layout="wide")
st.title("Operations")
st.caption("A summary of documents currently known to the system.")

try:
    summary = get_operations_summary()
except BackendError as exc:
    st.error(friendly_message(exc))
else:
    if summary.total_documents == 0:
        st.info("No operational history is available yet. Upload a document to get started.")
    else:
        cols = st.columns(4)
        cols[0].metric("Total documents", summary.total_documents)
        cols[1].metric("Processed", summary.documents_by_status.get("processed", 0))
        cols[2].metric("Processing", summary.documents_by_status.get("processing", 0))
        cols[3].metric("Failed", summary.documents_by_status.get("failed", 0))

        st.subheader("Documents by status")
        st.bar_chart(summary.documents_by_status)

st.divider()
st.caption(
    "Copilot request and agent-execution metrics are not shown here: the "
    "multi-agent orchestrator does not currently persist workflow "
    "history, so no truthful figure is available yet."
)
