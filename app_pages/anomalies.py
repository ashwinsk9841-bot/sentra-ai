"""Anomalies & Alerts - Real detections with severity ordering and triage."""

from __future__ import annotations

import streamlit as st

from sentinel.ui import charts, components, frames
from sentinel.ui.state import (
    acknowledge_anomaly,
    alerts,
    anomalies,
    overview,
    read_controls,
    set_alert_status,
)

components.section("Anomalies & Alerts", icon=":material/notifications_unread:")
target, window = read_controls(default="24h")

if not target:
    components.empty_state(
        "No device registered",
        "Open **Demo Mode** to seed labelled synthetic data, or pair an authorized agent.",
    )
    st.stop()

ov = overview(target, window)
an = anomalies(target, window)
al = alerts(target, window)

counts = ov.get("counts") or {}
components.kpi_row(
    [
        {"label": "Anomalies (24h)", "value": counts.get("anomalies", 0)},
        {"label": "New alerts", "value": counts.get("alerts_new", 0)},
        {"label": "Acknowledged", "value": counts.get("alerts_acknowledged", 0)},
        {"label": "Resolved", "value": counts.get("alerts_resolved", 0)},
        {"label": "Errors logged", "value": counts.get("errors", 0)},
    ]
)

# Anomaly table
components.table(
    frame=an,
    what="anomalies",
    hint="No anomalies detected in the last 24 hours.",
    column_config={
        "event": st.column_config.TextColumn("Event"),
        "device": st.column_config.TextColumn("Device"),
        "severity": st.column_config.TextColumn("Severity"),
        "risk_score": st.column_config.NumberColumn("Risk", format="%d"),
        "ts": st.column_config.TextColumn("Time"),
        "status": st.column_config.TextColumn("Status"),
    },
)

# Alert table
components.table(
    frame=al,
    what="alerts",
    hint="No alerts recorded.",
    column_config={
        "title": st.column_config.TextColumn("Title"),
        "device": st.column_config.TextColumn("Device"),
        "severity": st.column_config.TextColumn("Severity"),
        "risk_score": st.column_config.NumberColumn("Risk", format="%d"),
        "ts": st.column_config.TextColumn("Time"),
        "status": st.column_config.TextColumn("Status"),
    },
)