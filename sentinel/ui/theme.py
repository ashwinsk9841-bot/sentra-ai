"""Shared visual language for the dashboard.

The dark palette itself lives in ``.streamlit/config.toml``. This module holds
the pieces Streamlit's theme tokens do not cover: the semantic colour mapping
for severities, the Altair base configuration, and small formatting helpers.

No CSS is injected anywhere in the app - the theme file is the single source of
truth for styling, which keeps the UI stable across Streamlit upgrades.
"""

from __future__ import annotations

from typing import Any, Final, Sequence

import altair as alt
import pandas as pd

__all__ = [
    "ACCENT",
    "ALT_THEME",
    "GRID",
    "MUTED",
    "SEVERITY_COLORS",
    "STATUS_COLORS",
    "TREND_COLORS",
    "axis",
    "base_config",
    "empty_frame_note",
    "fmt_bytes",
    "fmt_compact",
    "fmt_duration",
    "fmt_number",
    "fmt_percent",
    "fmt_timestamp",
    "severity_color",
]

#: Accent used for the primary series and focus elements.
ACCENT: Final[str] = "#4F8CFF"
#: De-emphasised text for axes, captions and empty states.
MUTED: Final[str] = "#7C8AA0"
#: Hairline colour for chart grids and axes.
GRID: Final[str] = "#233044"

SEVERITY_COLORS: Final[dict[str, str]] = {
    "CRITICAL": "#FF5C6C",
    "HIGH": "#FF9F45",
    "MEDIUM": "#F5D24B",
    "LOW": "#3DD68C",
    "INFO": "#4F8CFF",
}

STATUS_COLORS: Final[dict[str, str]] = {
    "AUTHORIZED": "#3DD68C",
    "ONLINE": "#3DD68C",
    "HEALTHY": "#3DD68C",
    "TRAINED": "#3DD68C",
    "OK": "#3DD68C",
    "PENDING": "#F5D24B",
    "DEGRADED": "#F5D24B",
    "WARNING": "#F5D24B",
    "PENDING_PAIRING": "#F5D24B",
    "REVOKED": "#FF5C6C",
    "FAILED": "#FF5C6C",
    "ERROR": "#FF5C6C",
    "UNHEALTHY": "#FF5C6C",
    "NOT_CONFIGURED": "#7C8AA0",
    "UNKNOWN": "#7C8AA0",
}

#: Fixed per-metric colours so a metric keeps its colour across every chart.
TREND_COLORS: Final[dict[str, str]] = {
    "cpu_percent": "#4F8CFF",
    "memory_percent": "#A78BFA",
    "disk_percent": "#F5D24B",
    "disk_read_mbps": "#22D3EE",
    "disk_write_mbps": "#38BDF8",
    "net_sent_mbps": "#3DD68C",
    "net_recv_mbps": "#4ADE80",
    "process_count": "#FF9F45",
    "thread_count": "#FB923C",
    "load_average": "#F472B6",
    "disk_free_gb": "#94A3B8",
    "swap_percent": "#FB7185",
    "context_switch_rate": "#C084FC",
    "handle_count": "#A3E635",
    "risk_score": "#FF5C6C",
}

_SEVERITY_ORDER: Final[tuple[str, ...]] = ("CRITICAL", "HIGH", "MEDIUM", "LOW")


def severity_color(severity: Any) -> str:
    return SEVERITY_COLORS.get(str(severity or "").upper(), MUTED)


def status_color(status: Any) -> str:
    return STATUS_COLORS.get(str(status or "").upper(), MUTED)


def axis(**kwargs: Any) -> alt.Axis:
    """A muted, low-contrast axis."""
    settings: dict[str, Any] = {
        "labelColor": MUTED,
        "titleColor": MUTED,
        "gridColor": GRID,
        "domainColor": GRID,
        "tickColor": GRID,
        "labelFontSize": 11,
        "titleFontSize": 12,
    }
    settings.update(kwargs)
    return alt.Axis(**settings)


def base_config(
    *,
    legend: alt.Legend | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Chart configuration shared by every figure so they look like one set.

    Size is set with ``.properties(...)`` (Altair 6 has no ``height`` config
    key) and tooltips are enabled per mark, so neither belongs here.
    """
    config: dict[str, Any] = {
        "background": "transparent",
        "font": "sans-serif",
        "view": {"stroke": "transparent"},
        "axis": {
            "labelColor": MUTED,
            "titleColor": MUTED,
            "gridColor": GRID,
            "domainColor": GRID,
            "tickColor": GRID,
        },
        "legend": {
            "labelColor": MUTED,
            "titleColor": MUTED,
            "orient": "top",
            "symbolType": "stroke",
            "labelFontSize": 11,
        },
    }
    if legend is not None:
        config["legend"] = legend
    return config


def fmt_number(value: Any, digits: int = 1) -> str:
    """Format a metric value, rendering missing data as an em dash."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if pd.isna(number):
        return "—"
    if abs(number) >= 1000:
        return f"{number:,.0f}"
    if abs(number) >= 100:
        return f"{number:,.{max(0, digits - 2)}f}"
    return f"{number:,.{digits}f}"


def fmt_compact(value: Any) -> str:
    """1.2k / 3.4M style formatting for counters."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if pd.isna(number):
        return "—"
    for limit, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(number) >= limit:
            return f"{number / limit:.1f}{suffix}"
    return f"{number:.0f}"


def fmt_percent(value: Any, digits: int = 1) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if pd.isna(number):
        return "—"
    return f"{number:.{digits}f}%"


def fmt_bytes(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if pd.isna(number):
        return "—"
    for limit, suffix in ((1024**4, "TB"), (1024**3, "GB"), (1024**2, "MB"), (1024, "KB")):
        if abs(number) >= limit:
            return f"{number / limit:.1f} {suffix}"
    return f"{number:.0f} B"


def fmt_duration(seconds: Any) -> str:
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return "—"
    if total < 60:
        return f"{total}s"
    minutes, rest = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {rest}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


def fmt_timestamp(value: Any, *, with_time: bool = True) -> str:
    """Render a timestamp in the viewer's local timezone."""
    if value is None or (isinstance(value, float) and value != value):
        return "—"
    stamp = pd.Timestamp(value)
    if stamp is pd.NaT or pd.isna(stamp):
        return "—"
    stamp = stamp.tz_convert("UTC").tz_convert(None) if stamp.tzinfo else stamp.tz_localize(None)
    return stamp.strftime("%Y-%m-%d %H:%M:%S" if with_time else "%Y-%m-%d")


def empty_frame_note(what: str, hint: str | None = None) -> str:
    """Honest empty-state copy - never a fake zero."""
    message = f"No {what} recorded yet."
    return f"{message} {hint}" if hint else message


def metric_color(metric: str) -> str:
    return TREND_COLORS.get(str(metric), ACCENT)


def severity_domain(values: Sequence[str]) -> list[str]:
    """Order severities worst-first, keeping only those present."""
    present = {str(v).upper() for v in values}
    ordered = [s for s in _SEVERITY_ORDER if s in present]
    return ordered or ["LOW"]
