"""Network - Aggregate interface counters only (no packet capture)."""

from __future__ import annotations

import streamlit as st

from sentinel.ui import charts, components, frames
from sentinel.ui.state import network_metrics, read_controls

components.section("Network", icon=":material/wifi:")
target, window = read_controls(default="1h")

if not target:
    components.empty_state(
        "No device registered",
        "Open **Demo Mode** to seed labelled synthetic data, or pair an authorized agent.",
    )
    st.stop()

net = network_metrics(target, window)

if net.empty:
    components.empty_state(
        "No network telemetry",
        "The agent reports per-interface byte and packet counters. Packet contents are "
        "never captured.",
    )
    st.stop()

interfaces = sorted(net["iface"].astype(str).unique()) if "iface" in net else []
selected = st.multiselect(
    "Interfaces",
    interfaces,
    default=interfaces[:4] if interfaces else [],
)

view = net[net["iface"].astype(str).isin(selected)] if selected and "iface" in net else net

components.kpi_row(
    [
        {"label": "Interfaces", "value": len(interfaces)},
        {
            "label": "Peak send",
            "value": f"{float(view['sent_mbps'].max()):.3f} Mbps"
            if "sent_mbps" in view
            else "—",
        },
        {
            "label": "Peak receive",
            "value": f"{float(view['recv_mbps'].max()):.3f} Mbps"
            if "recv_mbps" in view
            else "—",
        },
    ]
)

components.table(
    frame=view,
    what="network interfaces",
    column_config={
        "iface": st.column_config.TextColumn("Interface"),
        "sent_mbps": st.column_config.ProgressColumn(
            "Sent (Mbps)", format="%.3f", min_value=0, max_value=max(float(view['sent_mbps'].max()) if "sent_mbps" in view else 1, 1)
        ),
        "recv_mbps": st.column_config.ProgressColumn(
            "Received (Mbps)", format="%.3f", min_value=0, max_value=max(float(view['recv_mbps'].max()) if "recv_mbps" in view else 1, 1)
        ),
    },
)