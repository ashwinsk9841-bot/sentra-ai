"""Agents & Fleet - Pairing, authorization state and fleet health."""

from __future__ import annotations

import streamlit as st

from sentinel.ui import components, frames
from sentinel.ui.state import (
    agent_status,
    create_pairing_code,
    fleet,
    read_controls,
    revoke_device,
    set_device_status,
)

components.section("Agents & Fleet", icon=":material/vpn_key:")
target, _window = read_controls()

status = agent_status(target) if target else {}
collection = status.get("collection") or {}
transport = status.get("transport") or {}

with st.container(border=True):
    st.markdown("**Collection policy**")
    st.caption("What the agent is allowed to collect. This list is enforced in code.")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Collected**")
        for item in collection.get("metrics", []) or []:
            st.markdown(f"- {item}")
    with c2:
        st.markdown("**Never collected**")
        for item in collection.get("excluded", []) or []:
            st.markdown(f"- {item}")
    st.caption(
        f"Interval {collection.get('interval_s', '—')}s · psutil available: "
        f"{collection.get('psutil_available')} · transport `{transport.get('mode', '—')}`"
    )

left, right = st.columns(2)

with left:
    with st.container(border=True):
        st.markdown("**Pairing**")
        st.caption(
            "Pairing codes are single-use and short-lived. Distribute only to an agent "
            "you are authorized to enroll."
        )
        ttl = st.slider("TTL (minutes)", 5, 120, 30)
        if st.button("Generate pairing code", icon=":material.add_link"):
            code = create_pairing_code(ttl_minutes=ttl)
            st.code(str(code.get("code") or ""), language="text")
            st.caption(f"Expires {code.get('expires_at')} · id `{code.get('id')}`")
        with st.expander("Agent run command"):
            st.code(
                "python -m sentinel.agent --url <ingest-url> --pair <code> --device-id <id>",
                language="bash",
            )

with right:
    with st.container(border=True):
        st.markdown("**Authorization**")
        if not target:
            components.empty_state("No device selected", "Pick a device in the sidebar.")
        else:
            st.write(f"Device: **{target}**")
            st.write(f"Current status: **{(fleet().query('device_id == @d').iloc[0]['status'] if not fleet().empty and (fleet()['device_id'] == target).any() else 'UNKNOWN')}**")
            c1, c2 = st.columns(2)
            if c1.button("Authorize", icon=":material/shield_check:", width="stretch"):
                set_device_status(target, "AUTHORIZED")
                st.rerun()
            if c2.button("Mark pending", icon=":material/hourglass_top:", width="stretch"):
                set_device_status(target, "PENDING")
                st.rerun()
            if st.button("Revoke", icon=":material/block:", width="stretch"):
                revoke_device(target)
                st.rerun()
            st.caption("Revoked devices cannot ingest telemetry; the API rejects their requests.")

with st.container(border=True):
    st.markdown("**Fleet**")
    fl = fleet()
    if fl.empty:
        components.empty_state("No devices", "No devices are registered yet.")
    else:
        components.kpi_row(
            [
                {"label": "Devices", "value": int(len(fl))},
                {
                    "label": "Online",
                    "value": int(fl["online"].sum()) if "online" in fl else "—",
                },
                {
                    "label": "Authorized",
                    "value": int((fl["status"].astype(str) == "AUTHORIZED").sum())
                    if "status" in fl
                    else "—",
                },
                {
                    "label": "At risk",
                    "value": int((pd_numeric(fl, "risk_score") >= 50).sum())
                    if "risk_score" in fl
                    else "—",
                },
            ]
        )
        table = frames.presentable(
            fl,
            [
                "device_id",
                "name",
                "status",
                "online",
                "last_seen",
                "last_seen_age_s",
                "os_name",
                "os_version",
                "arch",
                "agent_version",
                "cpu_percent",
                "memory_percent",
                "disk_percent",
                "risk_score",
                "agent_ip",
            ],
        )
        st.dataframe(table, hide_index=True, height=380)


def pd_numeric(frame, column: str):
    import pandas as pd

    return pd.to_numeric(frame[column], errors="coerce").fillna(0)
