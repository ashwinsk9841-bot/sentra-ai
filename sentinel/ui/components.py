"""Reusable Streamlit building blocks.

Components stay declarative: no injected CSS, no placeholder art. When there is
no data the component says so instead of drawing an empty chart or a fake zero.
"""

from __future__ import annotations

from typing import Any, Sequence

import altair as alt
import pandas as pd
import streamlit as st

from .theme import (
    MUTED,
    SEVERITY_COLORS,
    fmt_number,
    fmt_percent,
    fmt_timestamp,
    severity_color,
)

__all__ = [
    "alert_row",
    "chart_or_empty",
    "dataframe_or_empty",
    "empty_state",
    "error_box",
    "kpi_row",
    "notice",
    "risk_header",
    "section",
    "severity_badge",
    "table",
]


def section(title: str, *, icon: str | None = None, help_text: str | None = None) -> None:
    """A section heading with consistent spacing."""
    st.subheader(title, icon=icon, help=help_text)


def notice(message: str, *, kind: str = "info", icon: str | None = None) -> None:
    """A one-line status message in a bordered card."""
    icons = {
        "info": ":material/info:",
        "success": ":material/check_circle:",
        "warning": ":material/warning:",
        "error": ":material/error:",
    }
    with st.container(border=True):
        st.markdown(f"{icons.get(kind, icons['info'])} {message}")


def error_box(message: str, *, detail: str | None = None) -> None:
    with st.container(border=True):
        st.error(message, icon=":material/error:")
        if detail:
            st.caption(detail)


def empty_state(what: str, hint: str, *, icon: str = ":material/inbox:") -> None:
    """Honest empty state: what is missing and exactly how to get it."""
    with st.container(border=True):
        st.markdown(f"{icon} **{what}**")
        st.caption(hint)


def severity_badge(severity: Any) -> str:
    """A coloured label using the theme's semantic colour tokens."""
    key = str(severity or "LOW").upper()
    color = severity_color(key)
    st.markdown(
        f":color-background[{color}20] :color[{color}]{key.title()}",
        help=None,
    )
    return key


def kpi_row(metrics: Sequence[dict[str, Any]]) -> None:
    """A responsive row of metric cards.

    Each entry accepts ``label``, ``value``, ``delta``, ``help`` and an optional
    ``spark`` list of evenly-spaced values.
    """
    entries = [m for m in metrics if m]
    if not entries:
        return
    with st.container(horizontal=True):
        for entry in entries:
            st.metric(
                entry.get("label", ""),
                entry.get("value"),
                delta=entry.get("delta"),
                delta_color=entry.get("delta_color", "normal"),
                help=entry.get("help"),
                border=True,
                chart_data=entry.get("spark"),
                chart_type=entry.get("chart_type", "line"),
            )


def risk_header(risk: dict[str, Any], *, device: str | None = None) -> None:
    """The risk banner every monitoring page opens with."""
    score = risk.get("score", 0)
    severity = str(risk.get("severity", "LOW")).upper()
    color = severity_color(severity)
    trend = risk.get("trend")
    delta = None
    if trend is not None:
        delta = f"{int(trend):+d} vs previous"

    left, right = st.columns([3, 2])
    with left:
        with st.container(border=True):
            kpi_row(
                [
                    {
                        "label": "Current risk",
                        "value": f"{int(score)} / 100",
                        "delta": delta,
                        "delta_color": "inverse",
                        "help": f"Severity: {severity}",
                    },
                    {
                        "label": "Devices at risk",
                        "value": risk.get("devices_at_risk", 0),
                        "help": "Devices scoring 50 or above.",
                    },
                ]
            )
            st.markdown(
                f":color[{color}]**{severity}** risk"
                + (f" · {device}" if device else "")
            )
    with right:
        with st.container(border=True):
            st.markdown("**Risk drivers**")
            drivers = risk.get("drivers") or []
            if drivers:
                for driver in drivers[:5]:
                    if isinstance(driver, dict):
                        name = str(driver.get("metric") or driver.get("name") or "signal")
                        value = driver.get("value")
                        contribution = driver.get("contribution")
                        weight = driver.get("weight")
                        text = f"{fmt_number(value)}" if value is not None else "—"
                        if contribution is not None:
                            text += f"  ·  contributes {fmt_number(contribution, 1)}"
                        if weight is not None:
                            text += f"  ·  weight {fmt_percent(weight, 0)}"
                        st.markdown(f"- **{name}** — {text}")
                    else:
                        st.markdown(f"- {driver}")
            else:
                st.caption("No risk drivers recorded yet.")
            summary = risk.get("summary")
            if summary:
                st.caption(str(summary))


def chart_or_empty(chart: alt.Chart | None, *, what: str, hint: str, key: str | None = None) -> None:
    """Render a chart, or an honest empty state when there is nothing to draw."""
    if chart is None:
        empty_state(what, hint)
        return
    st.altair_chart(chart, key=key) if key else st.altair_chart(chart)


def dataframe_or_empty(
    frame: pd.DataFrame,
    *,
    what: str,
    hint: str,
    height: int | None = None,
    column_config: dict[str, Any] | None = None,
    key: str | None = None,
) -> None:
    if frame is None or frame.empty:
        empty_state(what, hint)
        return
    st.dataframe(
        frame,
        hide_index=True,
        height=height,
        column_config=column_config,
        key=key,
    )


def table(frame: pd.DataFrame, *, what: str, hint: str, column_config: dict[str, Any] | None = None) -> None:
    if frame is None or frame.empty:
        empty_state(what, hint)
        return
    st.dataframe(frame, hide_index=True, column_config=column_config)


def alert_row(alert: dict[str, Any]) -> None:
    """One alert in a bordered card, with acknowledge/resolve actions."""
    severity = str(alert.get("severity") or "LOW").upper()
    color = SEVERITY_COLORS.get(severity, MUTED)
    with st.container(border=True):
        title, meta = st.columns([3, 2])
        with title:
            st.markdown(f":color[{color}]**{severity}** — {alert.get('title') or 'Alert'}")
            message = alert.get("message")
            if message:
                st.caption(message)
        with meta:
            st.caption(
                f"{fmt_timestamp(alert.get('ts'))} · risk {int(alert.get('risk_score') or 0)}"
            )
        actions = st.container(horizontal=True, horizontal_alignment="right")
        alert_id = alert.get("alert_id")
        if alert_id and actions.button(
            "Acknowledge", key=f"ack-{alert_id}", icon=":material/check:"
        ):
            from .state import notification_service, refresh_all

            notification_service().acknowledge(str(alert_id))
            refresh_all()
        if alert_id and actions.button(
            "Resolve", key=f"resolve-{alert_id}", icon=":material/task_alt:"
        ):
            from .state import notification_service, refresh_all

            notification_service().resolve(str(alert_id))
            refresh_all()
