"""Analytics & Correlation - Distribution stats, reliability and relationships."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from sentinel.ui import charts, components, frames
from sentinel.ui.state import (
    analytics_summary,
    correlation,
    hourly_profile,
    read_controls,
    reliability,
    system_metrics,
    timeseries,
)

components.section("Analytics & Correlation", icon=":material/analytics:")
target, window = read_controls(default="24h")

if not target:
    components.empty_state(
        "No device registered",
        "Open **Demo Mode** to seed labelled synthetic data, or pair an authorized agent.",
    )
    st.stop()

summary = analytics_summary(target, window)
rel = reliability(target, window)
telemetry = system_metrics(target, window)
hourly = hourly_profile(target, window)
corr = correlation(target, window)

components.kpi_row(
    [
        {"label": "Samples", "value": int(summary.get("samples", 0) or 0)},
        {
            "label": "Coverage",
            "value": f"{float(rel.get('coverage_pct') or 0.0):.1f}%",
            "help": f"{rel.get('received_samples', 0)} of {rel.get('expected_samples', 0)} expected samples",
        },
        {
            "label": "Healthy samples",
            "value": f"{float(rel['healthy_pct']):.1f}%"
            if rel.get("healthy_pct") is not None
            else "—",
        },
        {
            "label": "Mean risk",
            "value": f"{float(rel['mean_risk']):.1f}" if rel.get("mean_risk") is not None else "—",
        },
        {
            "label": "Max risk",
            "value": f"{float(rel['max_risk']):.0f}" if rel.get("max_risk") is not None else "—",
        },
        {
            "label": "Alerts",
            "value": f"{int(rel.get('alerts_resolved', 0) or 0)}/{int(rel.get('alerts_total', 0) or 0)}",
            "help": "Resolved / total",
        },
    ]
)

# Metric distribution table
with st.container(border=True):
    st.markdown("**Distribution**")
    metrics = summary.get("metrics") or {}
    if metrics:
        rows = []
        for name, stats in metrics.items():
            rows.append(
                {
                    "Metric": frames.metric_label(name),
                    "Unit": stats.get("unit") or "—",
                    "Min": stats.get("min"),
                    "Mean": stats.get("mean"),
                    "Median": stats.get("median"),
                    "Std": stats.get("std"),
                    "P95": stats.get("p95"),
                    "Max": stats.get("max"),
                    "Last": stats.get("last"),
                }
            )
        st.dataframe(pd.DataFrame(rows), hide_index=True, height=320)
    else:
        components.empty_state("No samples", "No telemetry in this window.")

# Hourly profile
with st.container(border=True):
    st.markdown("**Hour-of-day profile**")
    if hourly is not None and not hourly.empty and "hour" in hourly.columns:
        options = [
            c
            for c in hourly.columns
            if c not in {"hour"} and pd.api.types.is_numeric_dtype(hourly[c])
        ]
        if options:
            chosen = st.selectbox("Metric", options, format_func=frames.metric_label)
            chart = charts.hourly_profile(hourly, metric=chosen, height=260)
            components.chart_or_empty(chart, what="profile", hint="Not enough samples.")
        else:
            components.empty_state("No hourly data", "Not enough samples to build a profile.")
    else:
        components.empty_state("No hourly data", "Not enough samples to build a profile.")

# Correlation heatmap
left, right = st.columns([3, 2])

with left:
    with st.container(border=True):
        st.markdown("**Correlation**")
        matrix = frames.select_columns(
            corr, [c for c in corr.columns if c in telemetry.columns]
        )
        chart = charts.correlation_heatmap(matrix, height=430)
        components.chart_or_empty(
            chart, what="correlation", hint="Not enough samples for correlation."
        )

with right:
    with st.container(border=True):
        st.markdown("**Pairwise**")
        options = [
            c
            for c in telemetry.columns
            if c in {"cpu_percent", "memory_percent", "disk_percent", "load_average", "process_count", "thread_count", "handle_count", "context_switch_rate"}
        ]
        if len(options) >= 2:
            x = st.selectbox("X", options, index=0, format_func=frames.metric_label)
            y = st.selectbox("Y", options, index=min(1, len(options) - 1), format_func=frames.metric_label)
            chart = charts.scatter_metric_correlation(telemetry, x, y, height=300)
            components.chart_or_empty(chart, what="samples", hint="Not enough samples.")
        else:
            components.empty_state("Not enough metrics", "No comparable metrics in this window.")

with st.container(border=True):
    st.markdown("**Reliability detail**")
    st.json({k: v for k, v in rel.items() if k not in {"window"}})

st.caption(
    "Coverage measures received versus expected samples over the measured span; "
    "healthy percentage counts risk samples below the alert threshold."
)
