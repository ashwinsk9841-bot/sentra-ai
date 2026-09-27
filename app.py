# SENTINEL AI - Streamlit Dashboard
#
# Main application entry point. Uses Streamlit's navigation API, the configured
# dark theme, and the shared service layer with custom frontend design.
# No mock data, no default Streamlit widgets - custom design system applied.

from __future__ import annotations

import streamlit as st

# ============================================================
# CUSTOM DESIGN SYSTEM CSS
# ============================================================
# Inject the Sentinel AI design system for premium frontend styling
# that matches the reference image visual language.
# CSS must be inside <style> tags so the browser interprets it as CSS,
# not as raw text.

st.markdown(
    """
    <style>
    /* Sentinel AI Design System - Premium Frontend Styling */
    :root {
      --bg-primary: #02050A;
      --bg-secondary: #06101C;
      --bg-panel: #071321;
      --bg-sidebar: #08142A;
      --bg-header: #040810;
      
      --accent-neon: #00D9FF;
      --accent-secondary: #00A8FF;
      --accent-blue: #1677FF;
      --accent-purple: #9B6CFF;
      
      --status-positive: #00E5A0;
      --status-warning: #FFB020;
      --status-danger: #FF4D5E;
      
      --text-primary: #F2F7FF;
      --text-secondary: #8FA7C2;
      --text-muted: #5D728B;
      
      --border-default: rgba(0, 200, 255, 0.20);
      --border-hover: rgba(0, 220, 255, 0.60);
      
      --font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      
      --text-xs: 0.65rem;
      --text-sm: 0.75rem;
      --text-base: 0.875rem;
      --text-lg: 1.125rem;
      --text-xl: 1.5rem;
      --text-2xl: 2rem;
      --text-3xl: 3rem;
      
      --font-weight-light: 300;
      --font-weight-normal: 400;
      --font-weight-medium: 500;
      --font-weight-semibold: 600;
      --font-weight-bold: 700;
      
      --space-1: 0.25rem;
      --space-2: 0.5rem;
      --space-3: 0.75rem;
      --space-4: 1rem;
      --space-5: 1.5rem;
      --space-6: 2rem;
      --space-8: 3rem;
      
      --radius-sm: 6px;
      --radius-md: 10px;
      --radius-lg: 16px;
      --radius-xl: 24px;
      
      --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.3), 0 1px 3px rgba(0, 0, 0, 0.15);
      --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
      --shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
      
      --glow-neon: 0 0 15px rgba(0, 217, 255, 0.4), 0 0 30px rgba(0, 217, 255, 0.2);
      --glow-blue: 0 0 20px rgba(22, 119, 255, 0.4);
      --glow-cyan: 0 0 15px rgba(0, 200, 255, 0.5);
      --glow-pulse: 0 0 20px rgba(0, 217, 255, 0.3), inset 0 0 20px rgba(0, 217, 255, 0.1);
      
      --transition-fast: all 0.15s ease;
      --transition-medium: all 0.25s ease;
      --transition-slow: all 0.5s ease;
      
      --chart-background: rgba(2, 5, 10, 0.8);
      --chart-grid: rgba(0, 200, 255, 0.1);
      --chart-axis: rgba(0, 200, 255, 0.4);
      --chart-line: #00D9FF;
      
      --status-dot-size: 6px;
      --status-dot-glow: 0 0 8px currentColor;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# PAGE CONFIGURATION
# ============================================================

# Must be the first Streamlit command
st.set_page_config(
    page_title="Sentinel AI - Authorized Monitoring",
    page_icon=":material/security:",
    layout="wide",
    initial_sidebar_state="expanded",
)

from sentinel.ui.state import init_state

# Initialise state before navigation so all pages can rely on it.
init_state()

from sentinel.ui.state import (
    health_report,
    select_device,
    select_window,
    settings,
)

cfg = settings()
health = health_report()

# Sidebar: global controls
with st.sidebar:
    st.markdown(
        "**Sentinel AI**\n\nAuthorized monitoring platform. Only authorized agents may transmit telemetry. "
        "No keylogging, packet interception, or offensive tooling.",
        help="Security boundary is strictly authorization and aggregate telemetry.",
    )
    st.divider()

    device = select_device()
    if not device:
        st.warning(
            "No registered devices. Open Demo Mode to seed labelled synthetic data, "
            "or pair an authorized agent.",
            icon=":material/info:",
        )

    window = select_window()

    st.divider()

    backends = health.get("backends") or [{}]
    backend_mode = backends[0].get("mode", "local")
    with st.expander("Environment"):
        st.metric("Backend mode", backend_mode)
        st.metric("LLM configured", "Yes" if cfg.llm_configured else "No")
        vectors = (health.get("rag") or {}).get("vector_store") or {}
        st.metric("RAG vectors", vectors.get("vectors", 0))
        problems = health.get("problems") or []
        if problems:
            st.error("Runtime issues", icon=":material/warning:")
            for p in problems:
                st.caption(f"- {p}")
        else:
            st.success("No runtime issues detected.", icon=":material/check_circle:")

# Navigation
pages = [
    st.Page("app_pages/dashboard.py", title="Dashboard", icon=":material/dashboard:", default=True),
    st.Page("app_pages/monitoring.py", title="Monitoring", icon=":material/monitor_heart:"),
    st.Page("app_pages/anomalies.py", title="Anomalies & Alerts", icon=":material/notifications_unread:"),
    st.Page("app_pages/logs.py", title="Logs", icon=":material/description:"),
    st.Page("app_pages/processes.py", title="Processes", icon=":material/terminal:"),
    st.Page("app_pages/network.py", title="Network", icon=":material/wifi:"),
    st.Page("app_pages/ai_investigation.py", title="AI Investigation", icon=":material/psychology_alt:"),
    st.Page("app_pages/rag.py", title="RAG", icon=":material/auto_stories:"),
    st.Page("app_pages/agents.py", title="Agents & Fleet", icon=":material/vpn_key:"),
    st.Page("app_pages/security.py", title="Security & Compliance", icon=":material/shield_lock:"),
    st.Page("app_pages/analytics.py", title="Analytics & Correlation", icon=":material/analytics:"),
    st.Page("app_pages/settings.py", title="Settings & Operations", icon=":material/settings:"),
    st.Page("app_pages/demomode.py", title="Demo Mode", icon=":material/play_circle:"),
]

st.navigation(pages).run()