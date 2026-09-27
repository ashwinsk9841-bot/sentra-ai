"""Altair figures for the dashboard.

Every chart is built from real frames returned by the service layer. Functions
return ``None`` when there is nothing to draw so callers can show an honest
empty state instead of an empty axis.
"""

from __future__ import annotations

from typing import Any, Sequence

import altair as alt
import pandas as pd

from ..constants import METRIC_LABELS, METRIC_UNITS
from .theme import (
    ACCENT,
    MUTED,
    SEVERITY_COLORS,
    axis,
    base_config,
    metric_color,
    severity_domain,
    severity_color,
)

__all__ = [
    "anomaly_timeline",
    "correlation_heatmap",
    "hourly_profile",
    "log_volume",
    "metric_lines",
    "network_throughput",
    "process_bar",
    "risk_area",
    "risk_gauge",
    "scatter_metric_correlation",
    "severity_bar",
]


def _empty(columns: Sequence[str]) -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="float64") for c in columns})


# --------------------------------------------------------------------------- #
# Telemetry
# --------------------------------------------------------------------------- #
def metric_lines(
    frame: pd.DataFrame,
    metrics: Sequence[str],
    *,
    height: int = 280,
    show_points: bool = False,
) -> alt.Chart | None:
    """Multi-metric time series, one line per metric with its own fixed colour."""
    metrics = [m for m in metrics if m in (frame.columns if frame is not None else [])]
    if frame is None or frame.empty or not metrics or "ts" not in frame.columns:
        return None

    long = (
        frame[["ts", *metrics]]
        .melt(id_vars="ts", var_name="metric", value_name="value")
        .dropna(subset=["value"])
    )
    if long.empty:
        return None

    scale = alt.Scale(
        domain=list(metrics),
        range=[metric_color(m) for m in metrics],
    )
    mark = alt.Chart(long).mark_line(
        strokeWidth=2, point=alt.OverlayMarkDef(size=18 if show_points else 0, filled=True)
    )
    chart = (
        mark.encode(
            x=alt.X("ts:T", title=None, axis=axis(format="%H:%M", labelOverlap=True)),
            y=alt.Y("value:Q", title=None, axis=axis(grid=True)),
            color=alt.Color(
                "metric:N",
                title=None,
                scale=scale,
                legend=alt.Legend(orient="top", columns=4, labelLimit=140),
            ),
            tooltip=[
                alt.Tooltip("ts:T", title="Time", format="%Y-%m-%d %H:%M:%S"),
                alt.Tooltip("metric:N", title="Metric"),
                alt.Tooltip("value:Q", title="Value", format=".2f"),
            ],
        )
        .properties(height=height)
    )
    return chart.configure(**base_config())


def metric_area(
    frame: pd.DataFrame,
    metric: str,
    *,
    threshold: float | None = None,
    height: int = 240,
) -> alt.Chart | None:
    """Single metric as a filled area, optionally with a threshold rule."""
    if frame is None or frame.empty or metric not in frame.columns or "ts" not in frame.columns:
        return None
    data = frame[["ts", metric]].dropna()
    if data.empty:
        return None

    area = (
        alt.Chart(data)
        .mark_area(opacity=0.28, color=metric_color(metric))
        .encode(
            x=alt.X("ts:T", title=None, axis=axis(format="%H:%M")),
            y=alt.Y(f"{metric}:Q", title=_unit_label(metric), axis=axis()),
            tooltip=[
                alt.Tooltip("ts:T", title="Time", format="%Y-%m-%d %H:%M:%S"),
                alt.Tooltip(f"{metric}:Q", title=_unit_label(metric), format=".2f"),
            ],
        )
    )
    line = (
        alt.Chart(data)
        .mark_line(strokeWidth=2, color=metric_color(metric))
        .encode(
            x=alt.X("ts:T", title=None),
            y=alt.Y(f"{metric}:Q", title=None),
        )
    )
    layers: list[alt.Chart] = [area, line]
    if threshold is not None:
        rule = (
            alt.Chart(pd.DataFrame({"y": [threshold]}))
            .mark_rule(strokeDash=[5, 4], color=SEVERITY_COLORS["HIGH"], strokeWidth=1.5)
            .encode(y="y:Q")
        )
        layers.append(rule)
    chart = alt.layer(*layers).properties(height=height)
    return chart.configure(**base_config())


def risk_area(frame: pd.DataFrame, *, height: int = 220) -> alt.Chart | None:
    """Risk score over time with severity bands behind it."""
    if frame is None or frame.empty or "risk_score" not in frame.columns:
        return None
    data = frame[[c for c in ("ts", "risk_score") if c in frame.columns]].dropna()
    if data.empty:
        return None

    bands = _risk_bands(data["risk_score"].max())
    background = (
        alt.Chart(pd.DataFrame(bands))
        .mark_rect()
        .encode(
            x=alt.X("ts:T", title=None, axis=axis(format="%H:%M")),
            y=alt.Y("risk_score:Q", title="Risk", axis=axis()),
            y2=alt.Y2("upper:Q"),
            color=alt.Color(
                "band:N",
                title=None,
                scale=alt.Scale(
                    domain=[b["band"] for b in bands],
                    range=[b["color"] for b in bands],
                ),
                legend=alt.Legend(orient="top"),
            ),
            order=alt.Order("lower:N"),
        )
    )
    line = (
        alt.Chart(data)
        .mark_line(strokeWidth=2.5, color=ACCENT)
        .encode(
            x="ts:T",
            y=alt.Y("risk_score:Q", title="Risk"),
            tooltip=[
                alt.Tooltip("ts:T", title="Time", format="%Y-%m-%d %H:%M:%S"),
                alt.Tooltip("risk_score:Q", title="Risk", format=".0f"),
            ],
        )
    )
    chart = alt.layer(background, line).properties(height=height)
    return chart.configure(**base_config())


def _risk_bands(max_score: float) -> list[dict[str, Any]]:
    top = max(100.0, float(max_score or 100.0))
    return [
        {"band": "Critical", "lower": 70, "upper": top, "color": "#2A1419"},
        {"band": "High", "lower": 50, "upper": 70, "color": "#2A1D10"},
        {"band": "Elevated", "lower": 25, "upper": 50, "color": "#272312"},
        {"band": "Normal", "lower": 0, "upper": 25, "color": "#0F2620"},
    ]


def risk_gauge(score: Any, severity: str, *, height: int = 170) -> alt.LayerChart:
    """Semicircular risk dial built from the real score.

    Bands are the platform's own severity thresholds, so the dial can never
    show a severity that disagrees with the one used for alerting.
    """
    try:
        value = float(score)
    except (TypeError, ValueError):
        value = 0.0
    value = max(0.0, min(100.0, value))
    key = str(severity or "LOW").upper()
    color = severity_color(key)

    bands = pd.DataFrame(
        [
            {"band": "Normal", "start": 0.0, "end": 25.0, "color": "#3DD68C"},
            {"band": "Elevated", "start": 25.0, "end": 50.0, "color": "#F5D24B"},
            {"band": "High", "start": 50.0, "end": 70.0, "color": "#FF9F45"},
            {"band": "Critical", "start": 70.0, "end": 100.0, "color": "#FF5C6C"},
        ]
    )
    value_arc = pd.DataFrame([{"band": key, "start": 0.0, "end": value, "color": color}])

    theta = alt.Theta(
        "end:Q",
        stack=True,
        sort=["start"],
        scale=alt.Scale(domain=[0, 100], range=[0, 180]),
    )
    track = (
        alt.Chart(bands)
        .mark_arc(innerRadius=62, outerRadius=88, cornerRadius=2, opacity=0.28)
        .encode(
            theta=theta,
            color=alt.Color("band:N", scale=None, legend=None),
        )
    )
    gauge = (
        alt.Chart(value_arc)
        .mark_arc(innerRadius=62, outerRadius=88, cornerRadius=2)
        .encode(
            theta=theta,
            color=alt.Color("band:N", scale=None, legend=None),
        )
    )
    readout = (
        alt.Chart(pd.DataFrame({"value": [f"{value:.0f}"], "severity": [key]}))
        .mark_text(align="center", baseline="middle")
        .encode(
            x=alt.value(1),
            y=alt.value(0.44),
            text="value:N",
            size=alt.value(34),
            color=alt.value(color),
        )
    )
    label = (
        alt.Chart(pd.DataFrame({"value": [f"{key} RISK"]}))
        .mark_text(align="center", baseline="middle", fontSize=11)
        .encode(
            x=alt.value(1),
            y=alt.value(0.16),
            text="value:N",
            color=alt.value(MUTED),
        )
    )
    return alt.layer(track, gauge, readout, label).properties(
        width=260, height=height
    )


# --------------------------------------------------------------------------- #
# Network / processes / logs
# --------------------------------------------------------------------------- #
def network_throughput(frame: pd.DataFrame, *, height: int = 240) -> alt.Chart | None:
    """Sent/received throughput per interface."""
    if frame is None or frame.empty:
        return None
    columns = [c for c in ("ts", "iface", "sent_mbps", "recv_mbps") if c in frame.columns]
    if len(columns) < 4:
        return None
    data = frame[columns].dropna(subset=["sent_mbps", "recv_mbps"])
    if data.empty:
        return None

    long = data.melt(
        id_vars=["ts", "iface"], value_vars=["sent_mbps", "recv_mbps"],
        var_name="direction", value_name="mbps",
    )
    long["iface"] = long["iface"].astype(str)
    chart = (
        alt.Chart(long)
        .mark_line(strokeWidth=1.6)
        .encode(
            x=alt.X("ts:T", title=None, axis=axis(format="%H:%M")),
            y=alt.Y("mbps:Q", title="Throughput", axis=axis()),
            color=alt.Color(
                "direction:N",
                title=None,
                scale=alt.Scale(
                    domain=["sent_mbps", "recv_mbps"], range=["#3DD68C", "#4F8CFF"]
                ),
                legend=alt.Legend(orient="top", labelExpr="datum.value == 'sent_mbps' ? 'Sent' : 'Received'"),
            ),
            tooltip=[
                alt.Tooltip("ts:T", title="Time", format="%Y-%m-%d %H:%M:%S"),
                alt.Tooltip("iface:N", title="Interface"),
                alt.Tooltip("mbps:Q", title="Mbps", format=".3f"),
            ],
        )
        .properties(height=height)
    )
    return chart.configure(**base_config())


def process_bar(frame: pd.DataFrame, *, value: str = "cpu_percent", limit: int = 15, height: int = 320) -> alt.Chart | None:
    """Top processes by resource use, labelled and coloured by severity."""
    if frame is None or frame.empty or value not in frame.columns or "name" not in frame.columns:
        return None
    data = frame.copy()
    data["name"] = data["name"].astype(str)
    data[value] = pd.to_numeric(data[value], errors="coerce")
    data = data.dropna(subset=[value]).nlargest(limit, value)
    if data.empty:
        return None
    data["label"] = data["name"] + "  ·  pid " + data.get("pid", pd.Series([0] * len(data))).astype(str)

    chart = (
        alt.Chart(data)
        .mark_bar(cornerRadiusEnd=3)
        .encode(
            y=alt.Y("label:N", title=None, sort="-x", axis=axis(labelLimit=220)),
            x=alt.X(f"{value}:Q", title=_unit_label(value), axis=axis()),
            color=alt.Color(
                f"{value}:Q",
                title=None,
                scale=alt.Scale(
                    domain=[0, max(1.0, float(data[value].max()))],
                    range=["#4F8CFF", "#FF5C6C"],
                ),
                legend=None,
            ),
            tooltip=[
                alt.Tooltip("label:N", title="Process"),
                alt.Tooltip(f"{value}:Q", title=_unit_label(value), format=".2f"),
                alt.Tooltip("memory_percent:Q", title="Memory %", format=".1f"),
                alt.Tooltip("num_threads:Q", title="Threads", format=".0f"),
            ],
        )
        .properties(height=height)
    )
    return chart.configure(**base_config())


def log_volume(frame: pd.DataFrame, *, height: int = 220) -> alt.Chart | None:
    """Log volume stacked by level - shows error storms directly."""
    if frame is None or frame.empty or "level" not in frame.columns or "ts" not in frame.columns:
        return None
    data = frame.copy()
    data["level"] = data["level"].astype(str).str.upper()
    counts = (
        data.groupby([pd.Grouper(key="ts", freq="1min"), "level"], dropna=True)
        .size()
        .reset_index(name="lines")
    )
    if counts.empty or counts["lines"].sum() == 0:
        return None
    levels = [level for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL") if level in set(counts["level"])]
    chart = (
        alt.Chart(counts)
        .mark_bar()
        .encode(
            x=alt.X("ts:T", title=None, axis=axis(format="%H:%M")),
            y=alt.Y("lines:Q", title="Log lines", axis=axis()),
            color=alt.Color(
                "level:N",
                title=None,
                scale=alt.Scale(
                    domain=levels or sorted(counts["level"].unique()),
                    range=[
                        SEVERITY_COLORS.get(level, MUTED)
                        for level in (levels or sorted(counts["level"].unique()))
                    ],
                ),
                legend=alt.Legend(orient="top"),
            ),
            order=alt.Order("level:N", sort="descending"),
            tooltip=[
                alt.Tooltip("ts:T", title="Minute", format="%Y-%m-%d %H:%M"),
                alt.Tooltip("level:N", title="Level"),
                alt.Tooltip("lines:Q", title="Lines", format=".0f"),
            ],
        )
        .properties(height=height)
    )
    return chart.configure(**base_config())


def hourly_profile(frame: pd.DataFrame, metric: str = "cpu_percent", *, height: int = 220) -> alt.Chart | None:
    """Mean and spread of a metric by hour of day.

    Accepts raw samples with a ``ts`` column or the pre-aggregated frame from
    ``AnalyticsService.hourly_profile`` (one mean per ``hour``).
    """
    if frame is None or frame.empty or metric not in frame.columns:
        return None

    if "hour" not in frame.columns:
        if "ts" not in frame.columns:
            return None
        data = frame.copy()
        data["hour"] = pd.to_datetime(data["ts"], errors="coerce", utc=True).dt.hour
        grouped = (
            data.dropna(subset=["hour", metric])
            .groupby("hour")[metric]
            .agg(
                mean="mean",
                p95=lambda s: float(s.quantile(0.95)),
                low="min",
                high="max",
            )
            .reset_index()
        )
    else:
        grouped = frame[["hour", metric]].copy().rename(columns={metric: "mean"})
        grouped["p95"] = grouped["mean"]
        grouped["low"] = grouped["mean"]
        grouped["high"] = grouped["mean"]

    if grouped.empty or grouped["mean"].notna().sum() == 0:
        return None
    grouped["hour"] = grouped["hour"].astype(int)
    grouped["hour_label"] = grouped["hour"].map(lambda h: f"{h:02d}:00")
    order = sorted(grouped["hour_label"].unique())

    band = (
        alt.Chart(grouped)
        .mark_area(opacity=0.16, color=metric_color(metric))
        .encode(
            x=alt.X("hour_label:N", title="Hour of day", sort=order, axis=axis(labelAngle=0)),
            y=alt.Y("low:Q", title=_unit_label(metric)),
            y2="high:Q",
        )
    )
    mean_line = (
        alt.Chart(grouped)
        .mark_line(strokeWidth=2, color=metric_color(metric))
        .encode(
            x=alt.X("hour_label:N", title=None, sort=order, axis=axis(labelAngle=0)),
            y=alt.Y("mean:Q", title=None),
            tooltip=[
                alt.Tooltip("hour_label:N", title="Hour"),
                alt.Tooltip("mean:Q", title="Mean", format=".2f"),
                alt.Tooltip("p95:Q", title="p95", format=".2f"),
                alt.Tooltip("low:Q", title="Min", format=".2f"),
                alt.Tooltip("high:Q", title="Max", format=".2f"),
            ],
        )
    )
    points = (
        alt.Chart(grouped)
        .mark_circle(size=26, color=metric_color(metric))
        .encode(x=alt.X("hour_label:N", title=None, sort=order), y=alt.Y("mean:Q", title=None))
    )
    chart = alt.layer(band, mean_line, points).properties(height=height)
    return chart.configure(**base_config())


# --------------------------------------------------------------------------- #
# Anomalies / analytics
# --------------------------------------------------------------------------- #
def anomaly_timeline(frame: pd.DataFrame, *, height: int = 280) -> alt.Chart | None:
    """Detected anomalies over time, sized by risk and coloured by severity."""
    if frame is None or frame.empty or "ts" not in frame.columns:
        return None
    data = frame.copy()
    if "metric" not in data.columns:
        return None
    data["ts"] = pd.to_datetime(data["ts"], errors="coerce", utc=True)
    data = data.dropna(subset=["ts"])
    if data.empty:
        return None
    if "risk_score" not in data.columns:
        data["risk_score"] = 0
    data["risk_score"] = pd.to_numeric(data["risk_score"], errors="coerce").fillna(0)
    data["severity"] = data.get("severity", "LOW").astype(str).str.upper()

    domain = severity_domain(data["severity"])
    chart = (
        alt.Chart(data)
        .mark_circle(opacity=0.85, stroke="#0B0F17", strokeWidth=0.6)
        .encode(
            x=alt.X("ts:T", title=None, axis=axis(format="%H:%M")),
            y=alt.Y("metric:N", title=None, axis=axis(labelLimit=160)),
            size=alt.Size(
                "risk_score:Q",
                title=None,
                scale=alt.Scale(range=[40, 700]),
                legend=None,
            ),
            color=alt.Color(
                "severity:N",
                title=None,
                scale=alt.Scale(
                    domain=domain, range=[SEVERITY_COLORS.get(s, MUTED) for s in domain]
                ),
                legend=alt.Legend(orient="top"),
            ),
            tooltip=[
                alt.Tooltip("ts:T", title="Time", format="%Y-%m-%d %H:%M:%S"),
                alt.Tooltip("metric:N", title="Metric"),
                alt.Tooltip("severity:N", title="Severity"),
                alt.Tooltip("risk_score:Q", title="Risk", format=".0f"),
                alt.Tooltip("anomaly_score:Q", title="Score", format=".3f"),
            ],
        )
        .properties(height=height)
    )
    return chart.configure(**base_config())


def severity_bar(counts: dict[str, int], *, height: int = 200) -> alt.Chart | None:
    """Severity distribution as a horizontal bar chart."""
    if not counts:
        return None
    data = pd.DataFrame(
        {"severity": list(counts.keys()), "count": list(counts.values())}
    )
    if data["count"].sum() == 0:
        return None
    order = severity_domain(data["severity"])
    chart = (
        alt.Chart(data)
        .mark_bar(cornerRadiusEnd=4)
        .encode(
            y=alt.Y("severity:N", title=None, sort=order, axis=axis()),
            x=alt.X("count:Q", title="Count", axis=axis()),
            color=alt.Color(
                "severity:N",
                title=None,
                scale=alt.Scale(domain=order, range=[SEVERITY_COLORS.get(s, MUTED) for s in order]),
                legend=None,
            ),
            tooltip=[alt.Tooltip("severity:N"), alt.Tooltip("count:Q", format=".0f")],
        )
        .properties(height=height)
    )
    return chart.configure(**base_config())


def correlation_heatmap(matrix: pd.DataFrame, *, height: int = 380) -> alt.LayerChart | None:
    """Correlation matrix as a diverging heatmap with in-cell coefficients."""
    if matrix is None or matrix.empty:
        return None
    matrix = matrix.rename_axis("metric").reset_index()
    value_columns = [c for c in matrix.columns if c != "metric"]
    if not value_columns:
        return None

    long = matrix.melt(
        id_vars="metric", value_vars=value_columns, var_name="other", value_name="corr"
    )
    long["metric"] = long["metric"].astype(str)
    long["other"] = long["other"].astype(str)
    long["corr"] = pd.to_numeric(long["corr"], errors="coerce")
    if long["corr"].notna().sum() == 0:
        return None

    order = [METRIC_LABELS.get(column, column) for column in value_columns]
    long["metric_label"] = long["metric"].map(lambda c: METRIC_LABELS.get(c, c))
    long["other_label"] = long["other"].map(lambda c: METRIC_LABELS.get(c, c))

    text = long.copy()
    text["corr_text"] = text["corr"].map(lambda v: "" if pd.isna(v) else f"{v:.2f}")
    text["abs_corr"] = text["corr"].abs()

    cells = (
        alt.Chart(long)
        .mark_rect(cornerRadius=2)
        .encode(
            x=alt.X("other_label:N", title=None, sort=order, axis=axis(labelAngle=-40)),
            y=alt.Y("metric_label:N", title=None, sort=order),
            color=alt.Color(
                "corr:Q",
                title="Correlation",
                scale=alt.Scale(domain=[-1, 0, 1], range=["#4F8CFF", "#1B2230", "#FF9F45"]),
                legend=alt.Legend(orient="top", direction="horizontal"),
            ),
            tooltip=[
                alt.Tooltip("metric_label:N", title="Metric"),
                alt.Tooltip("other_label:N", title="Correlates with"),
                alt.Tooltip("corr:Q", title="r", format=".3f"),
            ],
        )
    )
    labels_layer = (
        alt.Chart(text)
        .mark_text(fontSize=10)
        .encode(
            x=alt.X("other_label:N", title=None, sort=order),
            y=alt.Y("metric_label:N", title=None, sort=order),
            text="corr_text:N",
            color=alt.condition(
                alt.datum.abs_corr > 0.55, alt.value("#E6EDF7"), alt.value("#7C8AA0")
            ),
        )
    )
    chart = alt.layer(cells, labels_layer).properties(height=height)
    return chart.configure(**base_config())


def scatter_metric_correlation(
    frame: pd.DataFrame, x: str, y: str, *, height: int = 300
) -> alt.LayerChart | None:
    """Two metrics against each other with the least-squares trend drawn in."""
    if frame is None or frame.empty or x not in frame.columns or y not in frame.columns:
        return None
    data = frame[[x, y]].apply(pd.to_numeric, errors="coerce").dropna()
    if len(data) < 3:
        return None
    correlation = float(data[x].corr(data[y]))
    color = "#FF9F45" if correlation > 0.6 else ("#4F8CFF" if correlation > 0.2 else MUTED)

    points = (
        alt.Chart(data)
        .mark_circle(size=42, opacity=0.55, color=color)
        .encode(
            x=alt.X(f"{x}:Q", title=_unit_label(x), axis=axis()),
            y=alt.Y(f"{y}:Q", title=_unit_label(y), axis=axis()),
            tooltip=[
                alt.Tooltip(f"{x}:Q", title=_unit_label(x), format=".2f"),
                alt.Tooltip(f"{y}:Q", title=_unit_label(y), format=".2f"),
            ],
        )
    )
    trend = (
        alt.Chart(data)
        .transform_regression(x, y)
        .mark_line(strokeWidth=2, color="#E6EDF7", strokeDash=[6, 4])
        .encode(
            x=alt.X(f"{x}:Q", title=None),
            y=alt.Y(f"{y}:Q", title=None),
            tooltip=[
                alt.Tooltip(f"{x}:Q", title=_unit_label(x), format=".2f"),
                alt.Tooltip(f"{y}:Q", title=f"{_unit_label(y)} (trend)", format=".2f"),
            ],
        )
    )
    chart = alt.layer(points, trend).properties(height=height)
    return chart.configure(**base_config())


def _unit_label(metric: str) -> str:
    label = METRIC_LABELS.get(metric, metric.replace("_", " ").title())
    unit = METRIC_UNITS.get(metric)
    return f"{label} ({unit})" if unit else label
