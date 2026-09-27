"""Monitoring - Telemetry explorer, risk context and model status."""

from __future__ import annotations

import streamlit as st

from sentinel.ui import charts, components, frames
from sentinel.ui.state import (
    health_report,
    overview,
    read_controls,
    system_events,
    system_metrics,
    timeseries,
)

components.section("Monitoring", icon=":material/monitor_heart:")
target, window = read_controls(default="1h")

if not target:
    components.empty_state(
        "No device registered",
        "Open **Demo Mode** to seed labelled synthetic data, or pair an authorized agent.",
    )
    st.stop()

ov = overview(target, window)
ts = timeseries(target, window)
telemetry = system_metrics(target, window)
health = health_report()
risk = ov.get("risk") or {}
latest = ov.get("latest") or {}
model = ov.get("model") or {}
device = ov.get("device") or {}

components.risk_header(
    {
        "score": risk.get("score", 0),
        "severity": risk.get("severity", "LOW"),
        "trend": risk.get("trend"),
        "drivers": risk.get("drivers") or [],
        "devices_at_risk": 1 if (risk.get("score") or 0) >= 50 else 0,
    },
    device=device.get("device_id") or target,
)

components.kpi_row(
    [
        {"label": "CPU", "value": _pct(latest.get("cpu_percent"))},
        {"label": "Memory", "value": _pct(latest.get("memory_percent"))},
        {"label": "Disk", "value": _pct(latest.get("disk_percent"))},
        {"label": "Disk free", "value": f"{_num(latest.get('disk_free_gb')):.1f} GB"},
        {"label": "Load average", "value": f"{_num(latest.get('load_average')):.2f}"},
        {"label": "Context switches", "value": f"{_num(latest.get('context_switch_rate')):.0f}/s"},
    ]
)

left, right = st.columns([3, 2])

with left:
    with st.container(border=True):
        st.markdown("**Telemetry**")
        selected = st.multiselect(
            "Metrics",
            options=sorted(frames.select_columns(telemetry, list(ov.get("metric_labels", {}).keys())).columns),
            default=[
                m
                for m in ("cpu_percent", "memory_percent", "disk_percent", "process_count", "thread_count")
                if m in telemetry.columns
            ],
            format_func=frames.metric_label,
        )
        frame = frames.series_frame(ts) if selected else telemetry
        chart = charts.metric_lines(frame, selected, height=340, show_points=False)
        components.chart_or_empty(chart, what="telemetry", hint="No samples in this window.")
        st.caption(
            f"{ts.get('points', 0)} point(s) · resampled to `{ts.get('rule', 'n/a')}`"
            if ts
            else ""
        )

with right:
    with st.container(border=True):
        st.markdown("**Model**")
        if model.get("trained"):
            st.success(model.get("message") or "Model trained.", icon=":material/check_circle:")
        else:
            st.info(model.get("message") or "No model trained for this device yet.")
        components.kpi_row(
            [
                {"label": "Detectors", "value": len(model.get("models") or []) or "—"},
                {"label": "Samples", "value": model.get("samples") or 0},
                {"label": "Features", "value": model.get("features") or 0},
            ]
        )
        if model.get("models"):
            st.caption("Ensemble: " + ", ".join(str(m) for m in model["models"]))
        with st.expander("Device identity"):
            st.json(
                {
                    k: v
                    for k, v in device.items()
                    if k in {"device_id", "name", "status", "os_name", "os_version", "hostname", "agent_version", "last_seen"}
                }
            )

bottom_left, bottom_right = st.columns([2, 3])

with bottom_left:
    with st.container(border=True):
        st.markdown("**Resource pressure**")
        chart = charts.metric_area(
            frames.series_frame(ts), "cpu_percent", threshold=85.0, height=260
        )
        components.chart_or_empty(chart, what="CPU samples", hint="No CPU telemetry in this window.")

with bottom_right:
    with st.container(border=True):
        st.markdown("**Platform events**")
        events = system_events(limit=100)
        table = frames.presentable(
            events, ["ts", "level", "source", "message", "context"]
        )
        components.dataframe_or_empty(
            table,
            what="platform events",
            hint="No platform events recorded yet.",
            height=280,
        )

with st.expander("Runtime checks"):
    for check in health.get("checks", []):
        st.write(
            f"**{check.get('name')}** — "
            f"{'OK' if check.get('ok') else 'ISSUE'} · {check.get('detail', '')}"
        )