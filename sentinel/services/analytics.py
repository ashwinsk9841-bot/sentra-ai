"""Analytics: derived views over the stored telemetry.

All numbers here are computed from the database. Nothing is random and nothing
is hard-coded, which is what makes the Analytics page trustworthy when Demo Mode
is off.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from ..config import Settings, get_settings
from ..constants import CORE_METRICS, METRIC_LABELS, METRIC_UNITS
from ..database.repository import SentinelRepository
from ..logger import get_logger
from .monitoring import MonitoringService

log = get_logger("services.analytics")

__all__ = ["AnalyticsService"]

WINDOWS = {
    "1h": 60,
    "6h": 360,
    "24h": 1440,
    "7d": 10080,
}


class AnalyticsService:
    """Aggregations for the Analytics page."""

    def __init__(
        self,
        repository: SentinelRepository | None = None,
        settings: Settings | None = None,
        *,
        service: MonitoringService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.service = service or MonitoringService(repository, self.settings)
        self.repo = self.service.repo

    # ------------------------------------------------------------------ #
    def summary(self, device_id: str | None = None, *, window: str = "24h") -> dict[str, Any]:
        """Headline statistics for the selected window."""
        target = self.service.resolve_device_id(device_id)
        minutes = WINDOWS.get(window, 1440)
        since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        metrics = self.repo.fetch_system_metrics(device_id=target, since=since, limit=20000)
        anomalies = self.repo.fetch_anomalies(device_id=target, since=since, limit=5000)
        alerts = self.repo.fetch_alerts(device_id=target, since=since, limit=5000)
        risk = self.repo.fetch_risk_events(device_id=target, since=since, limit=20000)

        stats: dict[str, dict[str, float]] = {}
        for metric in CORE_METRICS:
            if metrics.empty or metric not in metrics.columns:
                continue
            series = pd.to_numeric(metrics[metric], errors="coerce").dropna()
            if series.empty:
                continue
            stats[metric] = _describe(series)

        risk_series = pd.to_numeric(risk["risk_score"], errors="coerce").dropna() if not risk.empty else pd.Series(dtype=float)
        return {
            "window": window,
            "since": since.isoformat(),
            "samples": int(len(metrics)),
            "metrics": stats,
            "risk": _describe(risk_series) if not risk_series.empty else {},
            "anomalies": {
                "total": int(len(anomalies)),
                "acknowledged": int(anomalies["acknowledged"].sum()) if not anomalies.empty and "acknowledged" in anomalies.columns else 0,
                "by_severity": _value_counts(anomalies, "severity"),
                "by_metric": _value_counts(anomalies, "metric"),
            },
            "alerts": {
                "total": int(len(alerts)),
                "by_status": _value_counts(alerts, "status"),
                "by_severity": _value_counts(alerts, "severity"),
            },
            "device": (self.service.device(target) or {}).get("name"),
        }

    # ------------------------------------------------------------------ #
    def timeseries(self, device_id: str | None = None, *, window: str = "24h") -> dict[str, Any]:
        """Resampled series for charting."""
        target = self.service.resolve_device_id(device_id)
        minutes = WINDOWS.get(window, 1440)
        since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        metrics = self.repo.fetch_system_metrics(device_id=target, since=since, limit=20000)
        if metrics.empty:
            return {"ts": [], "series": {}, "rule": _resample_rule(minutes), "points": 0}

        indexed = metrics.set_index("ts").sort_index()
        # Bucket by how much data actually exists, not by the width of the
        # window: 30 minutes of telemetry asked for as "24h" would otherwise
        # collapse into a single point and hide the incident entirely.
        span_minutes = max(
            1.0, (indexed.index.max() - indexed.index.min()).total_seconds() / 60.0
        )
        rule = _resample_rule(minutes, span_minutes=span_minutes)
        buckets: dict[str, pd.DataFrame] = {}
        for metric in CORE_METRICS:
            if metric not in indexed.columns:
                continue
            numeric = pd.to_numeric(indexed[metric], errors="coerce")
            buckets[metric] = numeric.resample(rule).mean()

        frame = pd.DataFrame(buckets).dropna(how="all")
        return {
            "ts": list(frame.index),
            "series": {metric: _clean(frame[metric]) for metric in frame.columns},
            "rule": rule,
            "points": int(len(frame)),
            "span_minutes": round(span_minutes, 1),
        }

    # ------------------------------------------------------------------ #
    def metric_correlation(
        self, device_id: str | None = None, *, window: str = "6h"
    ) -> pd.DataFrame:
        """Correlation matrix across the core metrics."""
        target = self.service.resolve_device_id(device_id)
        since = datetime.now(timezone.utc) - timedelta(minutes=WINDOWS.get(window, 360))
        metrics = self.repo.fetch_system_metrics(device_id=target, since=since, limit=20000)
        if metrics.empty:
            return pd.DataFrame()
        available = [m for m in CORE_METRICS if m in metrics.columns]
        numeric = metrics[available].apply(pd.to_numeric, errors="coerce")
        numeric = numeric.dropna(axis=1, how="all")
        return numeric.corr(numeric_only=True).round(3)

    # ------------------------------------------------------------------ #
    def hourly_profile(self, device_id: str | None = None, *, window: str = "24h") -> pd.DataFrame:
        """Average metric value by hour of day (operational rhythm)."""
        target = self.service.resolve_device_id(device_id)
        since = datetime.now(timezone.utc) - timedelta(minutes=WINDOWS.get(window, 1440))
        metrics = self.repo.fetch_system_metrics(device_id=target, since=since, limit=50000)
        if metrics.empty or "ts" not in metrics.columns:
            return pd.DataFrame()
        frame = metrics.copy()
        frame["hour"] = pd.to_datetime(frame["ts"], utc=True).dt.hour
        available = [m for m in CORE_METRICS if m in frame.columns]
        grouped = frame.groupby("hour")[available].mean(numeric_only=True).round(2)
        return grouped.reset_index()

    # ------------------------------------------------------------------ #
    def reliability(
        self, device_id: str | None = None, *, window: str = "7d"
    ) -> dict[str, Any]:
        """Reporting coverage and risk profile over a window.

        ``coverage_pct`` is the honest availability number: how much of the
        telemetry the device was actually expected to send arrived. Counting
        "healthy" samples as availability (risk severity == LOW) would report
        0% for a device that is reporting perfectly but is under heavy load.
        """
        target = self.service.resolve_device_id(device_id)
        minutes = WINDOWS.get(window, 10080)
        since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        risk = self.repo.fetch_risk_events(device_id=target, since=since, limit=20000)
        alerts = self.repo.fetch_alerts(device_id=target, since=since, limit=20000)
        metrics = self.repo.fetch_system_metrics(
            device_id=target, since=since, limit=200000
        )
        device = self.service.device(target) or {}

        total = int(len(risk))
        healthy = 0
        if not risk.empty and "severity" in risk.columns:
            healthy = int(risk["severity"].isin(("LOW", "MEDIUM")).sum())

        interval_s = max(5, int(device.get("interval_s") or self.settings.agent_update_interval))
        # Coverage is measured across the period the device was actually
        # reporting. Dividing a 30-minute history by a 7-day window would report
        # 0.3% and look like a broken agent rather than "it has only been up for
        # half an hour".
        measured_minutes = float(minutes)
        if not metrics.empty and "ts" in metrics.columns:
            observed = metrics["ts"]
            span = (observed.max() - observed.min()).total_seconds() / 60.0
            if span > 0:
                measured_minutes = min(measured_minutes, span + interval_s / 60.0)
        expected = int(measured_minutes * 60 / interval_s)
        received = int(len(metrics))
        coverage = round(min(100.0, 100.0 * received / expected), 2) if expected else None

        return {
            "window": window,
            "risk_samples": total,
            "healthy_samples": healthy,
            "healthy_pct": round(100.0 * healthy / total, 2) if total else None,
            "coverage_pct": coverage,
            "expected_samples": expected,
            "received_samples": received,
            "measured_over_minutes": round(measured_minutes, 1),
            "sample_interval_s": interval_s,
            "mean_risk": round(float(pd.to_numeric(risk["risk_score"]).mean()), 1)
            if total
            else None,
            "max_risk": int(pd.to_numeric(risk["risk_score"]).max()) if total else None,
            "alerts_total": int(len(alerts)),
            "alerts_resolved": _count_where(alerts, "status", "RESOLVED"),
            "last_seen": _iso(device.get("last_seen")),
            "device_status": device.get("status"),
        }

    # ------------------------------------------------------------------ #
    def rag_usage(self, *, limit: int = 200) -> dict[str, Any]:
        """RAG query history summarised for the Analytics page."""
        queries = self.repo.fetch_rag_queries(limit=limit)
        if queries.empty:
            return {"queries": 0, "avg_latency_ms": None, "avg_hits": None, "recent": []}
        latency = pd.to_numeric(queries.get("latency_ms"), errors="coerce").dropna()
        hits = pd.to_numeric(queries.get("hit_count"), errors="coerce").dropna()
        recent = queries.head(10).to_dict("records")
        for record in recent:
            record["created_at"] = _iso(record.get("created_at"))
        return {
            "queries": int(len(queries)),
            "avg_latency_ms": round(float(latency.mean()), 1) if not latency.empty else None,
            "avg_hits": round(float(hits.mean()), 2) if not hits.empty else None,
            "by_provider": _value_counts(queries, "provider"),
            "recent": recent,
        }

    def investigation_history(self, *, limit: int = 50) -> list[dict[str, Any]]:
        frame = self.repo.fetch_investigations(limit=limit)
        if frame.empty:
            return []
        records = frame.head(limit).to_dict("records")
        for record in records:
            record["created_at"] = _iso(record.get("created_at"))
            record.pop("evidence", None)
        return records


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _describe(series: pd.Series) -> dict[str, float]:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return {}
    return {
        "min": round(float(values.min()), 3),
        "max": round(float(values.max()), 3),
        "mean": round(float(values.mean()), 3),
        "median": round(float(values.median()), 3),
        "std": round(float(values.std(ddof=0)), 3),
        "p95": round(float(values.quantile(0.95)), 3),
        "last": round(float(values.iloc[-1]), 3),
        "label": METRIC_LABELS.get(getattr(values, "name", "") or "", ""),
        "unit": METRIC_UNITS.get(getattr(values, "name", "") or "", ""),
    }


def _resample_rule(minutes: int, *, span_minutes: float | None = None) -> str:
    """Pick a bucket size that keeps a chart legible.

    ``span_minutes`` is the amount of data actually present. When it is much
    smaller than the requested window the finer rule is used, so a 30-minute
    incident inspected over a 24-hour window still renders as a curve instead
    of a single averaged point.
    """
    effective = float(span_minutes) if span_minutes else float(minutes)
    if effective <= 120:
        return "1min"
    if effective <= 720:
        return "5min"
    if effective <= 2880:
        return "30min"
    return "2h"


def _clean(series: pd.Series) -> list[float | None]:
    return [None if pd.isna(v) else round(float(v), 3) for v in series.tolist()]


def _value_counts(frame: pd.DataFrame, column: str) -> dict[str, int]:
    if frame.empty or column not in frame.columns:
        return {}
    return {str(k): int(v) for k, v in frame[column].value_counts().items()}


def _count_where(frame: pd.DataFrame, column: str, value: str) -> int:
    if frame.empty or column not in frame.columns:
        return 0
    return int((frame[column] == value).sum())


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value
