"""Processes - Resource-heavy process snapshots."""

from __future__ import annotations

import streamlit as st

from sentinel.ui import charts, components, frames
from sentinel.ui.state import process_snapshots, read_controls

components.section("Processes", icon=":material/terminal:")
target, window = read_controls(default="1h")

if not target:
    components.empty_state(
        "No device registered",
        "Open **Demo Mode** to seed labelled synthetic data, or pair an authorized agent.",
    )
    st.stop()

proc = process_snapshots(target, limit=1000)

if proc.empty:
    components.empty_state(
        "No process snapshots",
        "The agent records process metadata (pid, owner, CPU, memory) on every cycle. "
        "Command lines and environment variables are never collected.",
    )
    st.stop()

components.kpi_row(
    [
        {"label": "Snapshots", "value": int(len(proc))},
        {
            "label": "Distinct processes",
            "value": int(proc["name"].nunique()) if "name" in proc else 0,
        },
        {
            "label": "Peak CPU %",
            "value": f"{float(proc['cpu_percent'].max()):.1f}"
            if "cpu_percent" in proc
            else "—",
        },
    ]
)

components.table(
    frame=proc,
    what="process snapshots",
    column_config={
        "name": st.column_config.TextColumn("Name"),
        "pid": st.column_config.NumberColumn("PID", format="%d"),
        "cpu_percent": st.column_config.ProgressColumn(
            "CPU %", format="%.1f", min_value=0, max_value=100
        ),
        "memory_percent": st.column_config.ProgressColumn(
            "RAM %", format="%.1f", min_value=0, max_value=100
        ),
        "owner": st.column_config.TextColumn("Owner"),
        "start_time": st.column_config.TextColumn("Started"),
    },
)