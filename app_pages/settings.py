"""Settings & Operations - Detection control, environment, data lifecycle."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from sentinel.ui import components
from sentinel.ui.state import (
    channels,
    clear_caches,
    clear_demo,
    health_report,
    read_controls,
    refresh_all,
    run_cycle,
    settings,
    train_model,
    unread_count,
)

components.section("Settings & Operations", icon=":material/settings:")
target, _window = read_controls()

health = health_report()
cfg = settings()

# Detection control
with st.container(border=True):
    st.markdown("**Detection**")
    if not target:
        components.empty_state("No device", "Select a device to run detection.")
    else:
        st.caption(
            "A cycle scores the most recent samples, persists new anomalies and alerts, "
            "and updates the risk score. Retraining fits the ensemble on clean history."
        )
        c1, c2 = st.columns(2)
        if c1.button("Run detection cycle", icon=":material/refresh:", width="stretch"):
            with st.spinner("Running cycle..."):
                run_cycle(target)
        
        if c2.button("Retrain model", icon=":material/train:", width="stretch"):
            with st.spinner("Retraining model..."):
                train_model(target)
        
        if st.button("Refresh data", icon=":material/sync:", width="stretch"):
            with st.spinner("Refreshing..."):
                refresh_all()

# Environment
with st.expander("Environment"):
    st.metric("Backend mode", cfg.primary_backend)
    st.metric("LLM configured", "Yes" if cfg.llm_configured else "No")
    vectors = (health.get("rag") or {}).get("vector_store") or {}
    st.metric("RAG vectors", vectors.get("vectors", 0))
    problems = health.get("problems") or []
    if problems:
        st.error("Runtime issues", icon=":material/warning:")
        for p in problems:
            st.caption(f"- {p}")
    else:
        st.success("No runtime issues detected.", icon=":material/check_circle:")