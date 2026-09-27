"""Demo Mode - Seed labelled synthetic telemetry and a baseline model."""

from __future__ import annotations

import streamlit as st

from sentinel.ui import components
from sentinel.ui.state import clear_demo, demo_service, read_controls, run_demo, settings

components.section("Demo Mode", icon=":material/play_circle:")
target, _window = read_controls()

st.info(
    "Demo data is synthetic and clearly labelled with the `SENTINEL-DEMO-` prefix. "
    "It is never mixed with real agent telemetry.",
    icon=":material/science:",
)

with st.container(border=True):
    st.markdown("**Seed**")
    st.caption(
        "Seeding clears any previous demo data, writes a clean baseline, trains the "
        "ensemble on it, then appends a genuine incident so detections are real."
    )

with st.container(border=True):
    st.markdown("**Configuration**")
    c1, c2, c3 = st.columns(3)
    samples = c1.slider("Baseline samples", 120, 1200, 480, 60)
    scenario_ids = [s["id"] for s in (demo_service().describe().get("scenarios") or [])] or [
        "mixed",
        "normal",
        "warning",
        "anomaly",
        "critical",
    ]
    descriptions = {
        s["id"]: s.get("description", "")
        for s in (demo_service().describe().get("scenarios") or [])
    }
    scenario = c2.selectbox(
        "Incident profile",
        scenario_ids,
    )

    c3.toggle("Train model", value=True)

if st.button("Run Demo", type="primary"):
    with st.spinner("Running demo..."):
        result = run_demo(samples=samples, scenario=scenario, seed=7)
    st.success(f"Demo completed: {result}")