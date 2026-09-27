"""Logs - Redacted log stream with volume and level filtering."""

from __future__ import annotations

import streamlit as st

from sentinel.ui import charts, components, frames
from sentinel.ui.state import log_sources, logs, read_controls

components.section("Logs", icon=":material/description:")
target, window = read_controls(default="6h")

if not target:
    components.empty_state(
        "No device registered",
        "Open **Demo Mode** to seed labelled synthetic data, or pair an authorized agent.",
    )
    st.stop()

sources = log_sources(target) or []

filters_left, filters_mid, filters_right = st.columns([2, 2, 3])

with filters_left:
    source = st.selectbox("Source", ["all"] + [str(s) for s in sources])

with filters_mid:
    level = st.selectbox("Level", ["all", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])

with filters_right:
    search = st.text_input("Search message, logger or module", placeholder="substring match")

log_frame = logs(
    target,
    window,
    levels=(level,) if level != "all" else None,
    source=source if source != "all" else None,
    search=search or None,
    limit=2000,
)

if log_frame.empty:
    components.empty_state(
        "No logs recorded",
        "The agent records redacted application and system log records. No packet contents or "
        "personal data are ever collected.",
    )
else:
    components.table(
        frame=log_frame,
        what="log entries",
        column_config={
            "timestamp": st.column_config.TextColumn("Time"),
            "level": st.column_config.TextColumn("Level"),
            "logger": st.column_config.TextColumn("Logger"),
            "message": st.column_config.TextColumn("Message"),
        },
    )