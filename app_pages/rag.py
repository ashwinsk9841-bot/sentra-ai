"""RAG - Knowledge base, retrieval and grounded answers."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from sentinel.ui import components, frames
from sentinel.ui.state import (
    documents,
    rag_answer,
    rag_delete_document,
    rag_ingest_bytes,
    rag_overview,
    rag_retrieve,
    read_controls,
)

components.section("Knowledge Base (RAG)", icon=":material/auto_stories:")
target, window = read_controls(default="24h")

overview_payload = rag_overview()
stats = overview_payload.get("stats") or {}
usage = overview_payload.get("usage") or {}
history = overview_payload.get("history") or []
vector_store = stats.get("vector_store") or {}
embedder = stats.get("embedder") or {}

components.kpi_row(
    [
        {"label": "Documents", "value": int(stats.get("documents", 0) or 0)},
        {"label": "Chunks", "value": int(stats.get("chunks", 0) or 0)},
        {"label": "Vectors", "value": int(vector_store.get("vectors", 0) or 0)},
        {"label": "Embedder", "value": embedder.get("provider") or "—"},
        {
            "label": "Queries",
            "value": int(usage.get("queries", 0) or 0),
            "help": "Recorded RAG queries",
        },
        {
            "label": "Context chunks",
            "value": int(stats.get("context_chunks", 0) or 0),
        },
    ]
)

# RAG test lab
st.markdown("**RAG Test Lab**")
col1, col2 = st.columns([2, 1])

with col1:
    query = st.text_input("Query", placeholder="Ask a question about the system...")

with col2:
    if st.button("Run", type="primary"):
        if query:
            with st.spinner("Retrieving..."):
                retrieved = rag_retrieve(query, top_k=5)
                answer = rag_answer(query)
            
            st.markdown("**Retrieved Context**")
            for i, ctx in enumerate(retrieved.get("contexts", []), 1):
                st.caption(f"{i}. {ctx.get('source', '—')}: {ctx.get('excerpt', '—')[:200]}...")
            
            st.markdown("**AI Answer**")
            st.info(answer.get("answer", "—"))
            
            st.markdown("**Sources**")
            for src in answer.get("sources", []):
                st.caption(f"- {src}")

# Document management
st.markdown("**Document Management**")
documents_payload = documents()
doc_stats = documents_payload.get("stats") or {}

col1, col2 = st.columns([2, 1])
with col1:
    st.caption(f"Total documents: {int(doc_stats.get('documents', 0) or 0)}")
    st.caption(f"Total chunks: {int(doc_stats.get('chunks', 0) or 0)}")

with col2:
    st.caption(f"Vectors: {int(vector_store.get('vectors', 0) or 0)}")
    st.caption(f"Embedder: {embedder.get('provider') or '—'}")