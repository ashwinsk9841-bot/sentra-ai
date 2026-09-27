"""Frame helpers shared by the pages.

The service layer returns light payloads (lists of timestamps plus a metric
mapping) for the charting endpoints and DataFrames for the tabular endpoints.
These helpers normalise both into the frames the chart functions expect.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from ..constants import METRIC_LABELS

__all__ = [
    "humanize",
    "metric_label",
    "presentable",
    "risk_frame",
    "select_columns",
    "series_frame",
    "timestamp_column",
]


def series_frame(payload: Mapping[str, Any]) -> pd.DataFrame:
    """``{"ts": [...], "series": {"cpu_percent": [...]}}`` -> DataFrame."""
    stamps = payload.get("ts") or []
    if not stamps:
        return pd.DataFrame()
    frame = pd.DataFrame({"ts": pd.to_datetime(stamps, utc=True, errors="coerce")})
    for name, values in (payload.get("series") or {}).items():
        frame[name] = values
    return frame.dropna(subset=["ts"])


def risk_frame(risk: Mapping[str, Any]) -> pd.DataFrame:
    """Risk payload with ``ts`` and ``series`` -> ``ts``/``risk_score`` frame."""
    stamps = risk.get("ts") or []
    if not stamps:
        return pd.DataFrame()
    frame = pd.DataFrame(
        {
            "ts": pd.to_datetime(stamps, utc=True, errors="coerce"),
            "risk_score": risk.get("series") or [],
        }
    )
    return frame.dropna(subset=["ts"])


def select_columns(frame: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    """Keep only the requested columns that exist, preserving order."""
    if frame is None or frame.empty:
        return pd.DataFrame() if frame is None else frame
    return frame.reindex(columns=[c for c in columns if c in frame.columns])


def timestamp_column(frame: pd.DataFrame, column: str = "ts") -> pd.DataFrame:
    """Coerce a timestamp column to UTC-aware datetimes for display/sorting."""
    if frame is None or frame.empty or column not in frame.columns:
        return frame
    return frame.assign(**{column: pd.to_datetime(frame[column], utc=True, errors="coerce")})


def metric_label(metric: Any) -> str:
    key = str(metric or "")
    return METRIC_LABELS.get(key, key.replace("_", " "))


def humanize(column: Any) -> str:
    """``risk_score`` -> ``Risk score`` for table headers."""
    text = str(column or "").replace("_", " ").strip()
    return text[:1].upper() + text[1:] if text else ""


def presentable(frame: pd.DataFrame, columns: Iterable[str] | None = None) -> pd.DataFrame:
    """Drop internal keys, sort newest first and humanise the headers."""
    if frame is None or frame.empty:
        return pd.DataFrame() if frame is None else frame
    hidden = {
        "id",
        "device_id",
        "raw",
        "meta",
        "pairing_code",
        "features",
        "model_scores",
        "evidence",
        "attributes",
    }
    keep = [c for c in (columns or frame.columns) if c in frame.columns and c not in hidden]
    out = timestamp_column(frame)[keep]
    if "ts" in out.columns:
        out = out.sort_values("ts", ascending=False)
    out.columns = [humanize(c) for c in out.columns]
    return out
