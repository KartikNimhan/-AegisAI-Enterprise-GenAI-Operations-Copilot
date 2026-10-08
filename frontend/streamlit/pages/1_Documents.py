"""Documents page — list, upload, and inspect ingested documents.

Uses Milestone 3's existing `/api/v1/documents` endpoints directly; this
page adds no new document-processing logic or backend route.
"""

from __future__ import annotations

import streamlit as st

from components.errors import friendly_message
from services.api.client import BackendError
from services.api.documents import (
    delete_document,
    get_document_chunks,
    get_embedding_status,
    list_documents,
    trigger_embeddings,
    upload_document,
)

st.set_page_config(page_title="Documents — AegisAI", page_icon=":open_file_folder:", layout="wide")
st.title("Documents")
st.caption(
    "Upload and inspect ingested documents. Copy a document's id into the "
    "Copilot chat to ask about it directly."
)

st.subheader("Upload")
uploaded_file = st.file_uploader("Choose a file", type=["pdf", "docx", "txt", "md"])
if uploaded_file is not None and st.button("Upload document"):
    try:
        record = upload_document(
            uploaded_file.name,
            uploaded_file.type or "application/octet-stream",
            uploaded_file.getvalue(),
        )
    except BackendError as exc:
        st.error(friendly_message(exc))
    else:
        if record.is_duplicate:
            st.info(f"Already uploaded — id: `{record.id}`")
        else:
            st.success(f"Uploaded — id: `{record.id}`")
        st.rerun()

st.divider()
st.subheader("Ingested documents")

try:
    documents, total = list_documents(limit=100)
except BackendError as exc:
    st.error(friendly_message(exc))
else:
    if not documents:
        st.info("No documents have been uploaded yet.")
    else:
        st.caption(f"{total} document(s)")
        _STATUS_ICON = {
            "uploaded": "📥",
            "processing": "⏳",
            "processed": "✅",
            "failed": "❌",
        }
        for document in documents:
            icon = _STATUS_ICON.get(document.status, "•")
            with st.container(border=True):
                header_cols = st.columns([3, 1, 2])
                header_cols[0].markdown(f"**{document.filename}**")
                header_cols[1].markdown(f"{icon} {document.status}")
                header_cols[2].markdown(f"`{document.id}`")

                with st.expander("Details"):
                    detail_cols = st.columns(2)
                    detail_cols[0].write(f"Type: {document.document_type}")
                    detail_cols[0].write(f"Uploaded: {document.created_at}")
                    if document.processed_at:
                        detail_cols[0].write(f"Processed: {document.processed_at}")
                    if document.page_count is not None:
                        detail_cols[1].write(f"Pages: {document.page_count}")
                    if document.character_count is not None:
                        detail_cols[1].write(f"Characters: {document.character_count}")
                    if document.error_message:
                        st.error(document.error_message)

                    action_cols = st.columns(3)
                    if action_cols[0].button("View chunks", key=f"chunks-{document.id}"):
                        try:
                            chunks, chunk_total = get_document_chunks(document.id, limit=10)
                        except BackendError as exc:
                            st.error(friendly_message(exc))
                        else:
                            if not chunks:
                                st.info("No chunks found for this document.")
                            else:
                                st.caption(f"Showing {len(chunks)} of {chunk_total} chunk(s)")
                                for chunk in chunks:
                                    st.text_area(
                                        f"Chunk {chunk.chunk_index}",
                                        chunk.content,
                                        height=100,
                                        key=f"chunk-{document.id}-{chunk.id}",
                                        disabled=True,
                                    )

                    if action_cols[1].button("Embedding status", key=f"embed-{document.id}"):
                        try:
                            status_record = get_embedding_status(document.id)
                        except BackendError as exc:
                            st.error(friendly_message(exc))
                        else:
                            st.write(
                                f"{status_record.embedded_chunks}/"
                                f"{status_record.total_chunks} chunks embedded "
                                f"({status_record.status})"
                            )

                    if action_cols[1].button("Generate embeddings", key=f"trigger-{document.id}"):
                        try:
                            trigger_embeddings(document.id)
                        except BackendError as exc:
                            st.error(friendly_message(exc))
                        else:
                            st.success("Embeddings generated.")
                            st.rerun()

                    if action_cols[2].button("Delete", key=f"delete-{document.id}"):
                        try:
                            delete_document(document.id)
                        except BackendError as exc:
                            st.error(friendly_message(exc))
                        else:
                            st.rerun()
