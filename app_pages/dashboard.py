"""Dashboard - Executive overview of risk, health and recent activity."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from sentinel.ui import charts, components, frames
from sentinel.ui.frames import metric_label
from sentinel.ui.state import overview, read_controls, timeseries, unread_count

# Runtime formatting helper - used by KPI rows
def _num(value: object) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    import pandas as pd
    return 0.0 if pd.isna(number) else number


components.section("Dashboard", icon=":material/dashboard:")
target, window = read_controls(default="24h")

if not target:
    components.empty_state(
        "No device registered",
        "Open **Demo Mode** to seed labelled synthetic data, or pair an authorized agent.",
    )
    st.stop()

ov = overview(target, window)
ts = timeseries(target, window)

risk = ov.get("risk") or {}
latest = ov.get("latest") or {}
series = ts.get("series") or {}
unread = unread_count(target)

components.risk_header(
    {
        "score": risk.get("score", 0),
        "severity": risk.get("severity", "LOW"),
        "trend": risk.get("trend"),
        "drivers": risk.get("drivers") or [],
        "devices_at_risk": 1 if (risk.get("score") or 0) >= 50 else 0,
    },
    device=target,
)

components.kpi_row(
    [
        {
            "label": "CPU",
            "value": f"{_num(latest.get('cpu_percent')):.1f}%",
            "spark": series.get("cpu_percent") or [],
            "help": "Most recent sample",
        },
        {
            "label": "Memory",
            "value": f"{_num(latest.get('memory_percent')):.1f}%",
            "spark": series.get("memory_percent") or [],
        },
        {
            "label": "Disk",
            "value": f"{_num(latest.get('disk_percent')):.1f}%",
            "spark": series.get("disk_percent") or [],
        },
        {
            "label": "Load (avg)",
            "value": f"{_num(latest.get('load_average')):.2f}",
            "spark": series.get("load_average") or [],
        },
        {
            "label": "Processes",
            "value": int(_num(latest.get("process_count"))),
            "spark": series.get("process_count") or [],
        },
        {
            "label": "Unread alerts",
            "value": unread,
            "delta_color": "off",
            "help": "Alerts waiting for acknowledgement",
        },
    ]
)

left, right = st.columns([2, 1])

with left:
    with st.container(border=True):
        st.markdown("**Resource trends**")
        chart = charts.metric_lines(
            frames.series_frame(ts), ["cpu_percent", "memory_percent", "disk_percent"], height=300
        )
        components.chart_or_empty(
            chart,
            what="telemetry samples",
            hint="No metrics recorded for this device in the selected window.",
        )

with right:
    with st.container(border=True):
        st.markdown("**Risk timeline**")
        chart = charts.risk_area(frames.risk_frame(risk), height=260)
        components.chart_or_empty(
            chart, what="risk events", hint="No risk events recorded yet."
        )

bottom_left, bottom_right = st.columns(2)

with bottom_left:
    with st.container(border=True):
        st.markdown("**Recent anomalies**")
        anomalies = ov.get("recent_anomalies") or []
        if anomalies:
            for anomaly in anomalies[:6]:
                components.alert_row(
                    {
                        "severity": anomaly.get("severity", "LOW"),
                        "title": f"{metric_label(anomaly.get('metric'))} anomaly",
                        "message": anomaly.get("explanation") or "",
                        "ts": anomaly.get("ts"),
                        "risk_score": anomaly.get("risk_score"),
                    }
                )
        else:
            components.empty_state(
                "No anomalies", "No anomalies detected in the last 24 hours."
            )

with bottom_right:
    with st.container(border=True):
        st.markdown("**Recent alerts**")
        alerts = ov.get("recent_alerts") or []
        if alerts:
            for alert in alerts[:6]:
                components.alert_row(alert)
        else:
            components.empty_state("No alerts", "No alerts for this device.")