"""Feature engineering for anomaly detection.

Turns a raw telemetry frame (one row per sample, columns = ``CORE_METRICS``)
into a supervised-friendly design matrix. Three families of feature are derived
per metric so the models can distinguish *level*, *movement* and *deviation
from the local baseline*:

``<metric>``
    the raw observation, winsorised to a sane range.
``<metric>__delta``
    first difference - catches sudden spikes that sit inside the global range.
``<metric>__dev``
    robust deviation from the trailing baseline (median / MAD), which is
    resistant to the very spikes we are trying to detect.

Plus a small number of interaction and seasonality features.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

from ..constants import CORE_METRICS

#: Rolling window (in samples) used to establish the local baseline.
BASELINE_WINDOW: Final[int] = 60

#: Minimum samples before deviation features are considered meaningful.
MIN_BASELINE_SAMPLES: Final[int] = 12

_EPS: Final[float] = 1e-9

#: Metrics whose heavy tail makes a log transform worthwhile.
_LOG_METRICS: Final[frozenset[str]] = frozenset(
    {
        "disk_read_mbps",
        "disk_write_mbps",
        "net_sent_mbps",
        "net_recv_mbps",
        "context_switch_rate",
        "handle_count",
        "process_count",
        "thread_count",
    }
)

#: Hard bounds applied before scaling; values beyond these are almost always
#: collector artefacts rather than real measurements.
_CLIP_BOUNDS: Final[dict[str, tuple[float, float]]] = {
    "cpu_percent": (0.0, 100.0),
    "memory_percent": (0.0, 100.0),
    "disk_percent": (0.0, 100.0),
    "swap_percent": (0.0, 100.0),
    "load_average": (0.0, 4096.0),
    "process_count": (0.0, 200000.0),
    "thread_count": (0.0, 2000000.0),
    "handle_count": (0.0, 8000000.0),
    "disk_free_gb": (0.0, 1e7),
    "disk_read_mbps": (0.0, 1e5),
    "disk_write_mbps": (0.0, 1e5),
    "net_sent_mbps": (0.0, 1e5),
    "net_recv_mbps": (0.0, 1e5),
    "context_switch_rate": (0.0, 1e7),
    "temperature_c": (-20.0, 150.0),
}

_METRIC_SUFFIXES: Final[tuple[str, ...]] = ("", "__delta", "__dev")

GLOBAL_FEATURES: Final[tuple[str, ...]] = (
    "net_total_mbps",
    "disk_total_mbps",
    "cpu_mem_interaction",
    "hour_sin",
    "hour_cos",
)


def feature_names() -> tuple[str, ...]:
    """Deterministic ordered list of engineered feature names."""
    names: list[str] = []
    for metric in CORE_METRICS:
        for suffix in _METRIC_SUFFIXES:
            names.append(f"{metric}{suffix}")
    names.extend(GLOBAL_FEATURES)
    return tuple(names)


FEATURE_NAMES: Final[tuple[str, ...]] = feature_names()

#: Base metrics only - handy for per-metric reporting.
BASE_FEATURE_NAMES: Final[tuple[str, ...]] = CORE_METRICS


@dataclass(slots=True)
class FeatureMatrix:
    """Design matrix plus the raw values needed for human-readable reporting."""

    frame: pd.DataFrame
    """Engineered features, indexed by timestamp."""

    raw: pd.DataFrame
    """The cleaned base metrics, indexed by timestamp (same index as ``frame``)."""

    baseline: pd.DataFrame
    """Trailing median/MAD in *engineered* space, aligned to ``frame``."""

    report_baseline: pd.DataFrame
    """Trailing median/MAD of the *raw* metrics, for human-readable reporting.

    Several metrics are log-transformed before modelling, so the engineered
    baseline is not in the units an operator expects. This frame stays in the
    original units.
    """

    @property
    def empty(self) -> bool:
        return self.frame.empty

    @property
    def timestamps(self) -> pd.DatetimeIndex:
        return self.frame.index

    def latest_vector(self) -> np.ndarray:
        if self.frame.empty:
            return np.zeros(len(FEATURE_NAMES), dtype=float)
        return self.frame.iloc[-1].to_numpy(dtype=float)

    def vectors(self) -> np.ndarray:
        if self.frame.empty:
            return np.zeros((0, len(FEATURE_NAMES)), dtype=float)
        return self.frame.to_numpy(dtype=float)


def _ensure_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce the base metric columns to float, adding any that are missing."""
    out = pd.DataFrame(index=df.index)
    for metric in CORE_METRICS:
        if metric in df.columns:
            series = pd.to_numeric(df[metric], errors="coerce")
        else:
            series = pd.Series(np.nan, index=df.index, dtype="float64")
        low, high = _CLIP_BOUNDS.get(metric, (-1e12, 1e12))
        series = series.replace([np.inf, -np.inf], np.nan).clip(lower=low, upper=high)
        out[metric] = series.astype("float64")
    return out


def _robust_deviation(series: pd.Series, window: int) -> pd.DataFrame:
    """Signed deviation from the trailing median in MAD units."""
    baseline_median = series.rolling(window, min_periods=MIN_BASELINE_SAMPLES).median()
    deviation = series - baseline_median
    mad = deviation.abs().rolling(window, min_periods=MIN_BASELINE_SAMPLES).median()
    # 1.4826 * MAD approximates sigma for normally distributed data.
    robust_z = deviation / (1.4826 * mad + _EPS)
    return pd.DataFrame(
        {"median": baseline_median, "mad": mad, "dev": robust_z.astype("float64")}
    )


def build_features(
    metrics: pd.DataFrame,
    *,
    baseline_window: int = BASELINE_WINDOW,
    ts_column: str = "ts",
) -> FeatureMatrix:
    """Engineer the anomaly-detection design matrix from raw telemetry.

    Parameters
    ----------
    metrics:
        Telemetry rows. Must contain a timestamp column (or a DatetimeIndex).
        Missing base metrics are tolerated and will be imputed downstream.
    baseline_window:
        Number of trailing samples used as the local baseline.
    """
    if metrics is None or len(metrics) == 0:
        empty_index = pd.DatetimeIndex([], tz="UTC", name=ts_column)
        empty_cols = list(CORE_METRICS)
        return FeatureMatrix(
            frame=pd.DataFrame(columns=list(FEATURE_NAMES), index=empty_index, dtype="float64"),
            raw=pd.DataFrame(columns=empty_cols, index=empty_index, dtype="float64"),
            baseline=pd.DataFrame(columns=empty_cols, index=empty_index, dtype="float64"),
            report_baseline=pd.DataFrame(columns=empty_cols, index=empty_index, dtype="float64"),
        )

    frame = metrics.copy()
    if ts_column in frame.columns:
        frame[ts_column] = pd.to_datetime(frame[ts_column], utc=True, errors="coerce")
        frame = frame.dropna(subset=[ts_column]).sort_values(ts_column, kind="stable")
        frame = frame.set_index(ts_column)
    elif not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.to_datetime(pd.Series(range(len(frame))), unit="s", utc=True)
    else:
        frame.index = pd.to_datetime(frame.index, utc=True)
    frame.index.name = ts_column

    # De-duplicate timestamps: the newest observation for a given instant wins.
    frame = frame[~frame.index.duplicated(keep="last")]

    raw = _ensure_numeric(frame)
    # Short gaps are common (agent restarts, network blips). A short forward
    # fill keeps delta features meaningful without inventing long trends.
    raw = raw.ffill(limit=3)

    engineered = pd.DataFrame(index=raw.index)
    baseline_cols: dict[str, pd.Series] = {}

    for metric in CORE_METRICS:
        series = raw[metric]
        if metric in _LOG_METRICS:
            series = np.log1p(series.clip(lower=0))
        engineered[metric] = series.astype("float64")
        engineered[f"{metric}__delta"] = series.diff().astype("float64")
        stats = _robust_deviation(series, baseline_window)
        engineered[f"{metric}__dev"] = stats["dev"]
        baseline_cols[metric] = stats["median"]
        baseline_cols[f"{metric}__mad"] = stats["mad"]

    engineered["net_total_mbps"] = (
        raw.get("net_sent_mbps", 0.0).fillna(0.0) + raw.get("net_recv_mbps", 0.0).fillna(0.0)
    )
    engineered["disk_total_mbps"] = (
        raw.get("disk_read_mbps", 0.0).fillna(0.0) + raw.get("disk_write_mbps", 0.0).fillna(0.0)
    )
    engineered["cpu_mem_interaction"] = (
        raw["cpu_percent"].fillna(0.0) * raw["memory_percent"].fillna(0.0) / 100.0
    )
    hours = raw.index.hour + raw.index.minute / 60.0
    engineered["hour_sin"] = np.sin(2 * np.pi * hours / 24.0)
    engineered["hour_cos"] = np.cos(2 * np.pi * hours / 24.0)

    # Reindex to the canonical order so downstream arrays are stable.
    engineered = engineered.reindex(columns=list(FEATURE_NAMES))

    infinite = engineered.replace([np.inf, -np.inf], np.nan)
    engineered = infinite.where(infinite.abs() < 1e12, np.nan)

    baseline = pd.DataFrame(baseline_cols).reindex(index=raw.index)

    # Reporting baseline stays in the original units (no log transform).
    report_cols: dict[str, pd.Series] = {}
    for metric in CORE_METRICS:
        stats = _robust_deviation(raw[metric], baseline_window)
        report_cols[metric] = stats["median"]
        report_cols[f"{metric}__mad"] = stats["mad"]
    report_baseline = pd.DataFrame(report_cols).reindex(index=raw.index)

    return FeatureMatrix(
        frame=engineered, raw=raw, baseline=baseline, report_baseline=report_baseline
    )


def describe_feature(name: str) -> str:
    """Human-readable label for a feature name."""
    if name in GLOBAL_FEATURES:
        return {
            "net_total_mbps": "Combined network throughput",
            "disk_total_mbps": "Combined disk throughput",
            "cpu_mem_interaction": "CPU/memory pressure interaction",
            "hour_sin": "Time-of-day (sine term)",
            "hour_cos": "Time-of-day (cosine term)",
        }[name]
    metric, _, suffix = name.partition("__")
    label = {
        "cpu_percent": "CPU utilisation",
        "memory_percent": "Memory utilisation",
        "disk_percent": "Disk utilisation",
        "disk_read_mbps": "Disk read throughput",
        "disk_write_mbps": "Disk write throughput",
        "net_sent_mbps": "Network sent",
        "net_recv_mbps": "Network received",
        "process_count": "Process count",
        "thread_count": "Thread count",
        "load_average": "Load average",
        "disk_free_gb": "Free disk space",
        "swap_percent": "Swap utilisation",
        "context_switch_rate": "Context switch rate",
        "handle_count": "Open handles",
    }.get(metric, metric)
    if suffix == "delta":
        return f"{label} (change)"
    if suffix == "dev":
        return f"{label} (deviation from baseline)"
    return label


__all__ = [
    "BASE_FEATURE_NAMES",
    "BASELINE_WINDOW",
    "CORE_METRICS",
    "FEATURE_NAMES",
    "GLOBAL_FEATURES",
    "FeatureMatrix",
    "build_features",
    "describe_feature",
    "feature_names",
]
