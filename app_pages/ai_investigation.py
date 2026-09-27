"""AI Investigation - Grounded answers over telemetry, detections and RAG."""

from __future__ import annotations

import streamlit as st

from sentinel.ui import components, frames
from sentinel.ui.state import (
    health_brief,
    investigate,
    investigate_anomaly,
    read_controls,
    window_report,
)

components.section("AI Investigation", icon=":material/psychology_alt:")
target, window = read_controls(default="24h")

if not target:
    components.empty_state(
        "No device registered",
        "Open **Demo Mode** to seed labelled synthetic data, or pair an authorized agent.",
    )
    st.stop()

st.caption(
    "Answers are grounded in retrieved documents and stored telemetry. When no LLM is "
    "configured the platform answers extractively and says so."
)

# Quick actions
actions = st.container(horizontal=True)
if actions.button("Health brief", icon=":material/health_and_safety:", type="primary"):
    with st.spinner("Building health brief..."):
        brief = health_brief(target)
    st.session_state["investigation_result"] = brief
    st.session_state["investigation_label"] = "Health brief"
if actions.button("Window report", icon=":material/description:"):
    with st.spinner(f"Building {window} report..."):
        report = window_report(target, f"the selected {window} window")