"""Security & Compliance - Health, boundaries and audit trail."""

from __future__ import annotations

import streamlit as st

from sentinel.ui import components, frames
from sentinel.ui.state import health_report, read_controls

components.section("Security & Compliance", icon=":material/shield_lock:")
target, _window = read_controls()

health = health_report()

status = "Healthy" if health.get("ok") else "Degraded"
components.kpi_row(
    [
        {"label": "Platform status", "value": status},
        {"label": "Checks passed", "value": f"{sum(1 for c in health.get('checks', []) if c.get('ok'))}/{len(health.get('checks', []))}"},
        {"label": "Runtime problems", "value": len(health.get("problems") or [])},
        {"label": "Devices", "value": int((health.get("counts") or {}).get("devices", 0) or 0)},
        {"label": "Stored logs", "value": int((health.get("counts") or {}).get("logs", 0) or 0)},
    ]
)

with st.container(border=True):
    st.markdown("**Component checks**")
    for check in health.get("checks", []):
        ok = bool(check.get("ok"))
        st.markdown(
            f":color-background[{'#00E5A020' if ok else '#FF4D5E20'}] :color-[#00E5A0 if ok else #FF4D5E]{'✓' if ok else '✗'} **{check.get('name')}** {check.get('detail', '')}",
            help=None,
        )

problems = health.get("problems") or []
if problems:
    with st.container(border=True):
        st.error("Runtime validation", icon=":material/gpp_maybe:")
        for problem in problems:
            st.markdown(f"- {problem}")