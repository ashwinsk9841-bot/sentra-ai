"""Monitoring service: the orchestration the dashboard pages call.

This is the layer that keeps page code thin and testable. It owns the
repository, the ML pipeline, the RAG pipeline and the investigator, and exposes
intent-shaped methods (``overview``, ``anomalies``, ``health``, ...) that return
plain dictionaries and DataFrames.

No page in the UI talks to the database directly.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

import pandas as pd

from ..ai.investigator import Investigator
from ..config import Settings, get_settings
from ..constants import CORE_METRICS, METRIC_LABELS, METRIC_UNITS, SEVERITIES
from ..database import get_repository
from ..database.repository import SentinelRepository
from ..logger import get_logger
from ..ml.pipeline import AnomalyPipeline, CycleResult
from ..rag.pipeline import RagPipeline

log = get_logger("services.monitoring")

__all__ = ["MonitoringService"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _window_start(window: str) -> datetime:
    minutes = {
        "15m": 15,
        "1h": 60,
        "6h": 360,
        "24h": 1440,
        "7d": 10080,
    }.get(window, 60)
    return _utcnow() - timedelta(minutes=minutes)


class MonitoringService:
    """Facade over storage, detection, RAG and AI."""

    def __init__(
        self,
        repository: SentinelRepository | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repo = repository or get_repository(settings=self.settings)
        self.pipeline = AnomalyPipeline(self.repo, self.settings)
        self.rag = RagPipeline(self.repo, self.settings)
        self.investigator = Investigator(self.repo, self.settings)
        self._lock = threading.Lock()
        self._device_labels: dict[str, str] | None = None

    # ------------------------------------------------------------------ #
    # Presentation helpers
    # ------------------------------------------------------------------ #
    def _device_label_map(self) -> dict[str, str]:
        """Map internal device primary keys to public device ids.

        Fact tables store the internal ``devices.id`` FK in their ``device_id``
        column, so raw rows would otherwise surface opaque UUIDs in the UI,
        exports and notifications.
        """
        if self._device_labels is None:
            frame = self.repo.list_devices()
            mapping: dict[str, str] = {}
            if not frame.empty and {"id", "device_id"}.issubset(frame.columns):
                for record in frame.to_dict("records"):
                    key = record.get("id")
                    public = record.get("device_id")
                    if key is not None and public:
                        mapping[str(key)] = str(public)
            self._device_labels = mapping
        return self._device_labels

    def refresh_device_labels(self) -> None:
        """Drop the cached id map after devices change."""
        self._device_labels = None

    def _public_ids(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Replace internal device keys with public device ids in place."""
        if frame is None or frame.empty or "device_id" not in frame.columns:
            return frame
        mapping = self._device_label_map()
        if not mapping:
            return frame
        return frame.assign(
            device_id=frame["device_id"].astype(str).map(lambda v: mapping.get(v, v))
        )

    # ------------------------------------------------------------------ #
    # Devices
    # ------------------------------------------------------------------ #
    def devices(self) -> pd.DataFrame:
        return self.repo.list_devices()

    def device(self, device_id: str | None) -> dict[str, Any] | None:
        if not device_id:
            frame = self.devices()
            if frame.empty:
                return None
            return frame.iloc[0].to_dict()
        return self.repo.get_device(device_id)

    def resolve_device_id(self, device_id: str | None) -> str | None:
        """Accept a name or an id and return the public device id."""
        if device_id:
            return device_id
        frame = self.devices()
        if frame.empty or "device_id" not in frame.columns:
            return None
        return str(frame.iloc[0]["device_id"])

    # ------------------------------------------------------------------ #
    # Telemetry
    # ------------------------------------------------------------------ #
    def system_metrics(
        self, device_id: str | None = None, *, window: str = "1h", limit: int = 3000
    ) -> pd.DataFrame:
        return self._public_ids(
            self.repo.fetch_system_metrics(
                device_id=device_id, since=_window_start(window), limit=limit
            )
        )

    def network_metrics(
        self, device_id: str | None = None, *, window: str = "1h", limit: int = 3000
    ) -> pd.DataFrame:
        return self._public_ids(
            self.repo.fetch_network_metrics(
                device_id=device_id, since=_window_start(window), limit=limit
            )
        )

    def process_snapshots(
        self, device_id: str | None = None, *, limit: int = 250
    ) -> pd.DataFrame:
        return self._public_ids(
            self.repo.fetch_process_snapshots(device_id=device_id, limit=limit)
        )

    def logs(
        self,
        device_id: str | None = None,
        *,
        window: str = "6h",
        levels: Sequence[str] | None = None,
        source: str | None = None,
        search: str | None = None,
        limit: int = 500,
    ) -> pd.DataFrame:
        return self._public_ids(
            self.repo.fetch_logs(
                device_id=device_id,
                since=_window_start(window),
                levels=list(levels) if levels else None,
                source=source,
                search=search,
                limit=limit,
            )
        )

    def log_sources(self, device_id: str | None = None) -> list[str]:
        return self.repo.log_sources(device_id)

    # ------------------------------------------------------------------ #
    # Anomalies and alerts
    # ------------------------------------------------------------------ #
    def anomalies(
        self,
        device_id: str | None = None,
        *,
        window: str = "24h",
        severities: Sequence[str] | None = None,
        metric: str | None = None,
        limit: int = 300,
    ) -> pd.DataFrame:
        return self._public_ids(
            self.repo.fetch_anomalies(
                device_id=device_id,
                since=_window_start(window),
                severities=list(severities) if severities else None,
                metric=metric,
                limit=limit,
            )
        )

    def alerts(
        self,
        device_id: str | None = None,
        *,
        statuses: Sequence[str] | None = None,
        window: str = "24h",
        limit: int = 300,
    ) -> pd.DataFrame:
        return self._public_ids(
            self.repo.fetch_alerts(
                device_id=device_id,
                statuses=list(statuses) if statuses else None,
                since=_window_start(window),
                limit=limit,
            )
        )

    def risk_events(
        self, device_id: str | None = None, *, window: str = "24h", limit: int = 1000
    ) -> pd.DataFrame:
        return self._public_ids(
            self.repo.fetch_risk_events(
                device_id=device_id, since=_window_start(window), limit=limit
            )
        )

    def set_alert_status(self, alert_id: str, status: str) -> bool:
        return self.repo.set_alert_status(alert_id, status)

    def acknowledge_anomaly(self, anomaly_id: str) -> bool:
        return self.repo.acknowledge_anomaly(anomaly_id)

    # ------------------------------------------------------------------ #
    # Detection
    # ------------------------------------------------------------------ #
    def run_cycle(self, device_id: str | None = None, *, train: bool = True) -> CycleResult:
        """Run one detection cycle for a device (used by Demo Mode and tests)."""
        target = self.resolve_device_id(device_id)
        if not target:
            raise ValueError("No registered device to run a cycle for.")
        return self.pipeline.run_cycle(target, train=train)

    def model_status(self, device_id: str | None = None) -> Any:
        target = self.resolve_device_id(device_id)
        return self.pipeline.status(target) if target else None

    def train_model(self, device_id: str | None = None, *, force: bool = False) -> Any:
        target = self.resolve_device_id(device_id)
        if not target:
            raise ValueError("No registered device to train for.")
        return self.pipeline.train(target, force=force)

    # ------------------------------------------------------------------ #
    # Overview for the dashboard
    # ------------------------------------------------------------------ #
    def overview(self, device_id: str | None = None, *, window: str = "1h") -> dict[str, Any]:
        """Everything the dashboard needs in one call."""
        target = self.resolve_device_id(device_id)
        device = self.device(target) or {}
        latest = self.repo.latest_system_metrics(target) or {}
        metrics = self.system_metrics(target, window=window, limit=2000)
        alerts = self.alerts(target, window="24h", limit=200)
        anomalies = self.anomalies(target, window="24h", limit=200)
        risk = self.risk_events(target, window="24h", limit=2000)
        logs = self.logs(target, window="6h", levels=["ERROR", "CRITICAL"], limit=200)
        processes = self.process_snapshots(target, limit=10)
        network = self.network_metrics(target, window=window, limit=2000)

        current_risk = int(risk.iloc[-1]["risk_score"]) if not risk.empty else int(
            device.get("risk_score") or 0
        )
        severity = str(risk.iloc[-1]["severity"]) if not risk.empty else str(
            device.get("severity") or "LOW"
        )

        return {
            "device": {
                "device_id": target,
                "name": device.get("name") or "No device",
                "status": device.get("status") or "UNKNOWN",
                "os_name": device.get("os_name"),
                "os_version": device.get("os_version"),
                "hostname": device.get("hostname"),
                "agent_version": device.get("agent_version"),
                "last_seen": device.get("last_seen"),
            },
            "latest": {metric: latest.get(metric) for metric in CORE_METRICS},
            "metric_labels": dict(METRIC_LABELS),
            "metric_units": dict(METRIC_UNITS),
            "risk": {
                "score": current_risk,
                "severity": severity,
                "series": risk["risk_score"].tolist() if not risk.empty else [],
                "ts": risk["ts"].tolist() if not risk.empty else [],
                "trend": _risk_trend(risk),
                "drivers": _risk_drivers(risk),
                "summary": str(risk.iloc[-1]["summary"]) if not risk.empty else None,
                "updated_at": risk.iloc[-1]["ts"] if not risk.empty else None,
            },
            "series": {
                "ts": metrics["ts"].tolist() if not metrics.empty else [],
                "metrics": {
                    metric: metrics[metric].tolist() if metric in metrics.columns else []
                    for metric in CORE_METRICS
                },
            },
            "network": {
                "ts": network["ts"].tolist() if not network.empty else [],
                "sent_mbps": _series(network, "sent_mbps"),
                "recv_mbps": _series(network, "recv_mbps"),
                "errin": _series(network, "errin"),
                "errout": _series(network, "errout"),
            },
            "counts": {
                "alerts_new": _count(alerts, "status", "NEW"),
                "alerts_acknowledged": _count(alerts, "status", "ACKNOWLEDGED"),
                "alerts_resolved": _count(alerts, "status", "RESOLVED"),
                "anomalies": int(len(anomalies)),
                "errors": _count(logs, "level", "ERROR") + _count(logs, "level", "CRITICAL"),
                "processes": int(len(self.process_snapshots(target, limit=500))),
            },
            "severity_breakdown": _severity_counts(anomalies),
            "recent_alerts": _head(alerts, 8),
            "recent_anomalies": _head(anomalies, 8),
            "top_processes": _head(processes, 8),
            "recent_errors": _head(logs, 8),
            "model": _model_summary(self.pipeline, target),
            "updated_at": _utcnow().isoformat(),
        }

    # ------------------------------------------------------------------ #
    # Health
    # ------------------------------------------------------------------ #
    def health(self) -> dict[str, Any]:
        """System + backend health for the Settings and Security pages."""
        from ..ai.llm import llm_health
        from ..database import repository_health

        backend = self.repo.health()
        checks: list[dict[str, Any]] = [
            {
                "name": "Database",
                "ok": backend.connected,
                "detail": backend.detail or backend.name,
                "latency_ms": backend.latency_ms,
            }
        ]
        rag_stats = self.rag.stats()
        checks.append(
            {
                "name": "Vector store",
                "ok": True,
                "detail": f"{rag_stats['vector_store']['backend']} - "
                f"{rag_stats['vector_store']['vectors']} vector(s)",
            }
        )
        checks.append(
            {
                "name": "Embeddings",
                "ok": True,
                "detail": f"{rag_stats['embedder']['provider']} "
                f"({rag_stats['embedder']['dimension']}d)",
            }
        )
        llm = llm_health(self.settings)
        checks.append({"name": "AI provider", "ok": bool(llm.get("connected")), "detail": llm.get("detail", "")})

        problems = [str(p) for p in self.settings.validate_runtime()]
        counts = self.repo.table_counts()
        backends = sorted(
            (b.as_dict() for b in repository_health(self.settings).values()),
            key=lambda b: 0 if b.get("mode") == "primary" else 1,
        )
        return {
            "ok": all(c["ok"] for c in checks),
            "checks": checks,
            "problems": problems,
            "counts": counts,
            "backends": backends,
            "rag": rag_stats,
            "config": self.settings.public_summary(),
            "checked_at": _utcnow().isoformat(),
        }

    def counts(self) -> dict[str, int]:
        return self.repo.table_counts()

    def record_event(self, level: str, source: str, message: str, context: Mapping[str, Any] | None = None) -> None:
        try:
            self.repo.insert_system_events(
                [
                    {
                        "ts": _utcnow(),
                        "level": level,
                        "source": source,
                        "message": message,
                        "context": dict(context or {}),
                    }
                ]
            )
        except Exception as exc:  # pragma: no cover - logging must not raise
            log.debug("Could not record system event: %s", exc)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _series(frame: pd.DataFrame, column: str) -> list[float]:
    if frame.empty or column not in frame.columns:
        return []
    return [float(v) if pd.notna(v) else 0.0 for v in frame[column].tolist()]


def _count(frame: pd.DataFrame, column: str, value: str) -> int:
    if frame.empty or column not in frame.columns:
        return 0
    return int((frame[column] == value).sum())


def _severity_counts(frame: pd.DataFrame) -> dict[str, int]:
    counts = {severity: 0 for severity in SEVERITIES}
    if frame.empty or "severity" not in frame.columns:
        return counts
    for severity, value in frame["severity"].value_counts().items():
        key = str(severity).upper()
        if key in counts:
            counts[key] = int(value)
    return counts


def _head(frame: pd.DataFrame, n: int) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    head = frame.head(n) if "ts" in frame.columns else frame.head(n)
    records = head.to_dict("records")
    for record in records:
        for key in ("ts", "last_seen", "created_at", "create_time"):
            value = record.get(key)
            if hasattr(value, "isoformat"):
                record[key] = value.isoformat()
    return records


def _model_summary(pipeline: AnomalyPipeline, device_id: str | None) -> dict[str, Any]:
    if not device_id:
        return {"trained": False, "message": "No device registered."}
    try:
        status = pipeline.status(device_id)
    except Exception as exc:  # pragma: no cover
        return {"trained": False, "message": str(exc)}
    return {
        "trained": bool(getattr(status, "trained", False)),
        "models": list(getattr(status, "models", []) or []),
        "samples": int(getattr(status, "sample_count", 0) or 0),
        "features": int(getattr(status, "feature_count", 0) or 0),
        "message": str(getattr(status, "message", "") or ""),
        "calibration": dict(getattr(status, "calibration", {}) or {}),
    }


def _risk_trend(frame: pd.DataFrame) -> int | None:
    """Change in mean risk between the newest and previous thirds of samples."""
    if frame.empty or "risk_score" not in frame.columns:
        return None
    values = pd.to_numeric(frame["risk_score"], errors="coerce").dropna()
    if len(values) < 4:
        return None
    window = max(2, len(values) // 3)
    current = float(values.tail(window).mean())
    previous = float(values.head(len(values) - window).tail(window).mean())
    return int(round(current - previous))


def _risk_drivers(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Risk components of the newest risk event, strongest contribution first."""
    if frame.empty or "composite" not in frame.columns:
        return []
    composite = frame.iloc[-1]["composite"]
    if not isinstance(composite, Mapping):
        return []
    drivers: list[dict[str, Any]] = []
    for name, component in composite.items():
        if not isinstance(component, Mapping):
            continue
        value = float(component.get("value") or 0.0)
        weight = float(component.get("weight") or 0.0)
        drivers.append(
            {
                "metric": str(name).replace("_", " "),
                "value": value,
                "weight": weight,
                "contribution": value * weight,
            }
        )
    drivers.sort(key=lambda d: d["contribution"], reverse=True)
    return drivers
