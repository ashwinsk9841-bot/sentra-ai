"""Read-mostly JSON API bridge for the SENTRA AI Next.js frontend.

This module is **additive**. It does not modify any existing Sentra logic: every
endpoint is a thin adapter that calls the very same services the Streamlit UI
uses (``MonitoringService``, ``AgentService``, ``AnalyticsService``,
``NotificationService``, ``DemoService``) and serialises what they return.

It exists so the production frontend (``frontend/``, Next.js on Vercel) can read
real Sentra data over HTTP without porting any ML/RAG/AI logic into React.

Only the Python standard library is used, so no new dependency is introduced.

Run it with::

    python -m sentinel.api.serve --port 8787

Then point the frontend at it with ``SENTRA_API_URL=http://127.0.0.1:8787``.
"""

from __future__ import annotations

import argparse
import json
import logging
import traceback
from collections.abc import Callable
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..database import get_repository
from ..database.repository import json_safe
from ..services import (
    AgentService,
    AnalyticsService,
    DemoService,
    MonitoringService,
    NotificationService,
)

LOG = logging.getLogger("sentinel.api")

#: Windows understood by the services, mapped to their label.
WINDOW_LABELS: dict[str, str] = {
    "15m": "Last 15 minutes",
    "1h": "Last hour",
    "6h": "Last 6 hours",
    "24h": "Last 24 hours",
    "7d": "Last 7 days",
}

#: Presentation order and labels for the composite risk drivers.
DRIVER_LABELS: tuple[tuple[str, str], ...] = (
    ("peak_anomaly", "Peak anomaly"),
    ("error_pressure", "Error pressure"),
    ("resource_pressure", "Resource pressure"),
    ("sustained_anomaly", "Sustained anomaly"),
)

_SERVICES: dict[str, Any] = {}


def services() -> dict[str, Any]:
    """Build the service graph once per process (reused across requests)."""
    if not _SERVICES:
        from ..config import get_settings

        cfg = get_settings()
        cfg.ensure_directories()
        repo = get_repository(settings=cfg)
        repo.initialise()
        mon = MonitoringService(repo, cfg)
        mon.refresh_device_labels()
        _SERVICES.update(
            cfg=cfg,
            repo=repo,
            mon=mon,
            agent=AgentService(repo, cfg),
            analytics=AnalyticsService(repo, cfg),
            notify=NotificationService(repo, cfg),
            demo=DemoService(repo, cfg),
        )
    return _SERVICES


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _records(frame: Any) -> list[dict[str, Any]]:
    """DataFrame -> JSON-safe records."""
    if frame is None or len(frame) == 0:
        return []
    return json_safe(frame.to_dict("records"))


def _resolve_device(device: str | None) -> str | None:
    svc = services()
    if device:
        resolved = svc["mon"].resolve_device_id(device)
        if resolved:
            return resolved
    devices = svc["mon"].devices()
    if len(devices) == 0:
        return None
    for column in ("device_id", "id"):
        if column in devices.columns:
            return str(devices.iloc[0][column])
    return None


def _window(qs: dict[str, list[str]], default: str = "1h") -> str:
    value = (qs.get("window") or [default])[0]
    return value if value in WINDOW_LABELS else default


def _limit(qs: dict[str, list[str]], default: int, maximum: int = 2000) -> int:
    try:
        value = int((qs.get("limit") or [default])[0])
    except (TypeError, ValueError):
        return default
    return max(1, min(value, maximum))


# --------------------------------------------------------------------------- #
# Payload builders
# --------------------------------------------------------------------------- #
def build_series(mon: Any, device: str | None, window: str) -> dict[str, Any]:
    """Telemetry series with ISO timestamps, ready for Recharts."""
    frame = mon.system_metrics(device, window=window, limit=3000)
    if len(frame) == 0:
        return {"ts": [], "metrics": {}}
    frame = frame.sort_values("ts")
    metrics: dict[str, list[float | None]] = {}
    for column in (
        "cpu_percent",
        "memory_percent",
        "disk_percent",
        "disk_read_mbps",
        "disk_write_mbps",
        "net_sent_mbps",
        "net_recv_mbps",
        "load_average",
        "process_count",
    ):
        if column in frame.columns:
            metrics[column] = [None if v is None else float(v) for v in frame[column]]
    return {"ts": [_iso(v) for v in frame["ts"]], "metrics": metrics}


def build_network(mon: Any, device: str | None, window: str) -> dict[str, Any]:
    frame = mon.network_metrics(device, window=window, limit=3000)
    if len(frame) == 0:
        return {"ts": [], "sent_mbps": [], "recv_mbps": [], "latest": None}
    frame = frame.sort_values("ts")
    latest = _records(frame.tail(1))[0]
    return {
        "ts": [_iso(v) for v in frame["ts"]],
        "sent_mbps": [
            None if v is None else float(v) for v in frame.get("sent_mbps", [])
        ],
        "recv_mbps": [
            None if v is None else float(v) for v in frame.get("recv_mbps", [])
        ],
        "latest": latest,
    }


def build_risk(mon: Any, device: str | None, window: str) -> dict[str, Any]:
    """Latest risk event plus the four composite risk drivers."""
    frame = mon.risk_events(device, window=window, limit=500)
    fallback: list[dict[str, Any]] = []
    if len(frame) == 0:
        overview_risk = (mon.overview(device, window=window) or {}).get("risk") or {}
        fallback = overview_risk.get("drivers") or []
        return {
            "score": overview_risk.get("score"),
            "severity": overview_risk.get("severity"),
            "summary": overview_risk.get("summary"),
            "updated_at": _iso(overview_risk.get("updated_at")),
            "trend": overview_risk.get("trend"),
            "drivers": fallback,
            "events": [],
        }

    frame = frame.sort_values("ts")
    latest = _records(frame.tail(1))[0]
    composite = latest.get("composite") or {}
    if isinstance(composite, str):
        try:
            composite = json.loads(composite)
        except (TypeError, ValueError):
            composite = {}

    drivers: list[dict[str, Any]] = []
    for key, label in DRIVER_LABELS:
        entry = composite.get(key) or {}
        if isinstance(entry, (int, float)):
            entry = {"value": float(entry)}
        if not isinstance(entry, dict):
            continue
        value = entry.get("value")
        drivers.append(
            {
                "key": key,
                "label": label,
                "value": None if value is None else round(float(value), 1),
                "weight": entry.get("weight"),
            }
        )
    if not drivers:
        drivers = [
            {"key": str(d.get("label", "")), "label": d.get("label"), "value": d.get("value")}
            for d in fallback
        ]

    return {
        "score": latest.get("risk_score"),
        "severity": latest.get("severity"),
        "summary": latest.get("summary"),
        "updated_at": _iso(latest.get("ts")),
        "trend": None,
        "drivers": drivers,
        "events": _records(frame.tail(24).iloc[::-1]),
    }


def build_timeline(svc: dict[str, Any], device: str | None, limit: int) -> list[dict[str, Any]]:
    """Real system + risk events, newest first, with a tone for colouring."""
    events: list[dict[str, Any]] = []
    for row in _records(svc["agent"].recent_events().head(limit)):
        level = str(row.get("level") or "INFO").upper()
        tone = {
            "ERROR": "danger",
            "CRITICAL": "danger",
            "WARNING": "warning",
            "WARN": "warning",
        }.get(level, "info")
        events.append(
            {
                "id": f"sys-{row.get('id')}",
                "ts": _iso(row.get("ts")),
                "title": str(row.get("message") or "System event"),
                "detail": str(row.get("source") or "system"),
                "level": level,
                "tone": tone,
                "status": level.title(),
                "origin": "system",
            }
        )
    for row in _records(
        svc["mon"].risk_events(device, window="7d", limit=limit).sort_values("ts").tail(limit)
    ):
        severity = str(row.get("severity") or "LOW").upper()
        tone = (
            "danger"
            if severity in {"CRITICAL", "HIGH"}
            else "warning"
            if severity == "MEDIUM"
            else "info"
        )
        events.append(
            {
                "id": f"risk-{row.get('id')}",
                "ts": _iso(row.get("ts")),
                "title": f"Risk score {row.get('risk_score')}/100 ({severity})",
                "detail": str(row.get("summary") or "Composite risk update"),
                "level": severity,
                "tone": tone,
                "status": severity.title(),
                "origin": "risk",
            }
        )
    events.sort(key=lambda e: e.get("ts") or "", reverse=True)
    return events[:limit]


def build_dashboard(qs: dict[str, list[str]]) -> dict[str, Any]:
    """Everything the Overview screen needs, in one round trip."""
    svc = services()
    mon, ana, notify = svc["mon"], svc["analytics"], svc["notify"]
    device = _resolve_device((qs.get("device") or [None])[0])
    window = _window(qs, default="1h")

    if device is None:
        return {
            "device": None,
            "window": window,
            "window_label": WINDOW_LABELS[window],
            "empty": True,
            "health": mon.health(),
            "counts": mon.counts(),
        }

    overview = mon.overview(device, window=window) or {}
    latest = overview.get("latest") or {}
    network = build_network(mon, device, window)
    net_latest = network.get("latest") or {}
    counts = overview.get("counts") or {}
    risk = build_risk(mon, device, window)

    anomalies = _records(mon.anomalies(device, window=window, limit=50))
    alerts = _records(mon.alerts(device, window=window, limit=50))

    # The device summary is used for the hero device card.
    device_row = mon.device(device) or {}
    meta = device_row.get("meta") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except (TypeError, ValueError):
            meta = {}

    uptime_seconds = latest.get("uptime_seconds")
    series = build_series(mon, device, window)
    # Real agents report uptime; when it is absent, fall back to how long this
    # device has actually been reporting telemetry for.
    monitored_seconds = None
    stamps = series.get("ts") or build_series(mon, device, "7d").get("ts") or []
    if stamps:
        try:
            first = datetime.fromisoformat(str(stamps[0]))
            last = datetime.fromisoformat(str(stamps[-1]))
            monitored_seconds = (last - first).total_seconds()
        except (TypeError, ValueError):
            monitored_seconds = None
    return {
        "empty": False,
        "window": window,
        "window_label": WINDOW_LABELS[window],
        "generated_at": _iso(datetime.now(timezone.utc)),
        "device": {
            "device_id": device_row.get("device_id") or device,
            "name": device_row.get("name") or device,
            "status": device_row.get("status"),
            "os_name": device_row.get("os_name"),
            "os_version": device_row.get("os_version"),
            "hostname": device_row.get("hostname"),
            "arch": device_row.get("arch"),
            "agent_version": device_row.get("agent_version"),
            "last_seen": _iso(device_row.get("last_seen")),
            "risk_score": device_row.get("risk_score"),
            "demo": bool(meta.get("demo") or meta.get("synthetic")),
            "scenario": meta.get("scenario"),
        },
        "latest": json_safe(latest),
        "metric_labels": overview.get("metric_labels") or {},
        "metric_units": overview.get("metric_units") or {},
        "counts": json_safe(counts),
        "severity_breakdown": json_safe(overview.get("severity_breakdown") or {}),
        "risk": risk,
        "series": series,
        "network": network,
        "anomalies": anomalies,
        "alerts": alerts,
        "timeline": build_timeline(svc, device, 12),
        "unread": notify.unread_count(device),
        "model": json_safe(overview.get("model") or {}),
        "health": mon.health(),
        "totals": mon.counts(),
        "demo": svc["demo"].describe(),
        "uptime_seconds": uptime_seconds,
        "monitored_seconds": monitored_seconds,
        "net_activity_mbps": (
            None
            if net_latest.get("sent_mbps") is None and net_latest.get("recv_mbps") is None
            else round(
                float(net_latest.get("sent_mbps") or 0) + float(net_latest.get("recv_mbps") or 0),
                3,
            )
        ),
        "reliability": json_safe(ana.reliability(device, window="7d")),
    }


# --------------------------------------------------------------------------- #
# Route table
# --------------------------------------------------------------------------- #
def get_dashboard(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    return build_dashboard(qs)


def get_health(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    svc = services()
    return {"health": svc["mon"].health(), "counts": svc["mon"].counts()}


def get_security(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    """Security posture: subsystem checks, storage backends and config warnings.

    Secrets are never included. ``config`` comes from the settings' public
    summary, which reports only whether each variable is set, never its value.
    """
    svc = services()
    health = svc["mon"].health()
    device = _resolve_device((qs.get("device") or [None])[0])
    return {
        "posture": "nominal" if health.get("ok") else "degraded",
        "checks": health.get("checks") or [],
        "backends": health.get("backends") or [],
        "problems": health.get("problems") or [],
        "config": health.get("config") or [],
        "rag": health.get("rag") or {},
        "events": _records(svc["repo"].fetch_system_events(limit=50)),
        "unread": svc["notify"].unread_count(device),
    }


def get_investigations(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    """Recent AI investigations, newest first."""
    svc = services()
    limit = _limit(qs, 20)
    device = _resolve_device((qs.get("device") or [None])[0])
    return {
        "history": json_safe(svc["analytics"].investigation_history(limit=limit)),
        "records": _records(svc["repo"].fetch_investigations(limit=limit)),
    }


def get_agents_health(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    """Agent fleet, ingest configuration and recent agent events."""
    svc = services()
    device = _resolve_device((qs.get("device") or [None])[0])
    return {
        "status": svc["agent"].status(device),
        "fleet": _records(svc["agent"].fleet()),
        "events": _records(svc["agent"].recent_events(limit=50)),
    }


def get_overview(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    svc = services()
    device = _resolve_device((qs.get("device") or [None])[0])
    window = _window(qs)
    return svc["mon"].overview(device, window=window)


def get_timeseries(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    svc = services()
    device = _resolve_device((qs.get("device") or [None])[0])
    window = _window(qs, default="6h")
    return svc["analytics"].timeseries(device, window=window)


def get_series(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    svc = services()
    device = _resolve_device((qs.get("device") or [None])[0])
    window = _window(qs)
    return build_series(svc["mon"], device, window)


def get_devices(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    return {"devices": _records(services()["mon"].devices())}


def get_anomalies(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    svc = services()
    device = _resolve_device((qs.get("device") or [None])[0])
    window = _window(qs, default="24h")
    severities = (qs.get("severity") or [None])[0]
    return {
        "anomalies": _records(
            svc["mon"].anomalies(
                device,
                window=window,
                severities=[severities] if severities else None,
                metric=(qs.get("metric") or [None])[0],
                limit=_limit(qs, 100),
            )
        )
    }


def get_alerts(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    svc = services()
    device = _resolve_device((qs.get("device") or [None])[0])
    window = _window(qs, default="24h")
    status = (qs.get("status") or [None])[0]
    return {
        "alerts": _records(
            svc["mon"].alerts(
                device,
                window=window,
                statuses=[status] if status else None,
                limit=_limit(qs, 100),
            )
        )
    }


def get_logs(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    svc = services()
    device = _resolve_device((qs.get("device") or [None])[0])
    window = _window(qs, default="24h")
    level = (qs.get("level") or [None])[0]
    return {
        "logs": _records(
            svc["mon"].logs(
                device,
                window=window,
                levels=[level] if level else None,
                source=(qs.get("source") or [None])[0],
                search=(qs.get("search") or [None])[0],
                limit=_limit(qs, 200),
            )
        ),
        "sources": svc["mon"].log_sources(device),
    }


def get_processes(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    svc = services()
    device = _resolve_device((qs.get("device") or [None])[0])
    return {"processes": _records(svc["mon"].process_snapshots(device, limit=_limit(qs, 120)))}


def get_network(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    svc = services()
    device = _resolve_device((qs.get("device") or [None])[0])
    return build_network(svc["mon"], device, _window(qs))


def get_risk(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    svc = services()
    device = _resolve_device((qs.get("device") or [None])[0])
    return build_risk(svc["mon"], device, _window(qs, default="24h"))


def get_timeline(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    svc = services()
    device = _resolve_device((qs.get("device") or [None])[0])
    return {"events": build_timeline(svc, device, _limit(qs, 20, 200))}


def get_fleet(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    return {"fleet": _records(services()["agent"].fleet())}


def get_agent(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    svc = services()
    device = _resolve_device((qs.get("device") or [None])[0])
    return svc["agent"].status(device)


def get_analytics(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    svc = services()
    device = _resolve_device((qs.get("device") or [None])[0])
    window = _window(qs, default="24h")
    return {
        "summary": json_safe(svc["analytics"].summary(device, window=window)),
        "reliability": json_safe(svc["analytics"].reliability(device, window=window)),
        "correlation": _records(svc["analytics"].metric_correlation(device, window=window)),
        "hourly_profile": _records(svc["analytics"].hourly_profile(device, window=window)),
        "rag_usage": json_safe(svc["analytics"].rag_usage()),
    }


def get_rag(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    svc = services()
    health = svc["mon"].health()
    return {
        "stats": health.get("rag") or {},
        "usage": json_safe(svc["analytics"].rag_usage()),
        "history": json_safe(svc["analytics"].investigation_history(limit=20)),
        "documents": _records(svc["repo"].list_documents()),
    }


def get_documents(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    svc = services()
    return {"documents": _records(svc["repo"].list_documents())}


# --------------------------------------------------------------------------- #
# Mutations (thin pass-throughs to the existing services)
# --------------------------------------------------------------------------- #
def post_ack_anomaly(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    anomaly_id = str(body.get("anomaly_id") or "")
    if not anomaly_id:
        raise ValueError("anomaly_id is required")
    return {"acknowledged": services()["mon"].acknowledge_anomaly(anomaly_id)}


def post_alert_status(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    alert_id = str(body.get("alert_id") or "")
    status = str(body.get("status") or "")
    if not alert_id or not status:
        raise ValueError("alert_id and status are required")
    return {"updated": services()["mon"].set_alert_status(alert_id, status)}


def post_device_status(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    device_id = str(body.get("device_id") or "")
    status = str(body.get("status") or "")
    if not device_id or not status:
        raise ValueError("device_id and status are required")
    return {"updated": services()["agent"].set_status(device_id, status)}


def post_run_cycle(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    svc = services()
    device = _resolve_device(str(body.get("device_id") or "") or None)
    return json_safe(svc["mon"].run_cycle(device))


def post_train_model(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    svc = services()
    device = _resolve_device(str(body.get("device_id") or "") or None)
    return json_safe(svc["mon"].train_model(device))


def post_investigate(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    svc = services()
    device = _resolve_device(str(body.get("device_id") or "") or None)
    question = str(body.get("question") or "Summarise the current risk on this device.")
    return json_safe(
        svc["mon"].investigator.ask(question, device_id=device, history=[], persist=True)
    )


def post_investigate_anomaly(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    svc = services()
    anomaly_id = str(body.get("anomaly_id") or "")
    if not anomaly_id:
        raise ValueError("anomaly_id is required")
    return json_safe(
        svc["mon"].investigator.investigate(
            anomaly_id, question=body.get("question"), persist=True
        )
    )


def post_rag_answer(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    svc = services()
    query = str(body.get("query") or "")
    if not query:
        raise ValueError("query is required")
    return json_safe(
        svc["mon"].rag.answer(
            query,
            top_k=body.get("top_k"),
            use_llm=bool(body.get("use_llm", False)),
            persist=True,
        )
    )


def post_rag_retrieve(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    svc = services()
    query = str(body.get("query") or "")
    if not query:
        raise ValueError("query is required")
    return json_safe(svc["mon"].rag.retrieve(query, top_k=int(body.get("top_k") or 5), persist=False))


def post_demo_seed(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    svc = services()
    result = svc["demo"].seed(
        samples=int(body.get("samples") or 240),
        scenario=str(body.get("scenario") or "anomaly"),
        seed=int(body.get("seed") or 7),
        train_model=bool(body.get("train_model", True)),
        include_document=bool(body.get("include_document", True)),
    )
    svc["mon"].refresh_device_labels()
    return json_safe(result)


def post_demo_clear(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    return json_safe(services()["demo"].clear())


def post_pairing_code(qs: dict[str, list[str]], body: dict[str, Any]) -> Any:
    return json_safe(services()["agent"].create_pairing_code())


ROUTES: dict[tuple[str, str], Callable[[dict[str, list[str]], dict[str, Any]], Any]] = {
    ("GET", "/api/dashboard"): get_dashboard,
    ("GET", "/api/health"): get_health,
    ("GET", "/api/overview"): get_overview,
    ("GET", "/api/timeseries"): get_timeseries,
    ("GET", "/api/series"): get_series,
    ("GET", "/api/devices"): get_devices,
    ("GET", "/api/anomalies"): get_anomalies,
    ("GET", "/api/alerts"): get_alerts,
    ("GET", "/api/logs"): get_logs,
    ("GET", "/api/processes"): get_processes,
    ("GET", "/api/network"): get_network,
    ("GET", "/api/risk"): get_risk,
    ("GET", "/api/timeline"): get_timeline,
    ("GET", "/api/fleet"): get_fleet,
    ("GET", "/api/agent"): get_agent,
    ("GET", "/api/analytics"): get_analytics,
    ("GET", "/api/rag"): get_rag,
    ("GET", "/api/documents"): get_documents,
    ("POST", "/api/ack-anomaly"): post_ack_anomaly,
    ("POST", "/api/alert-status"): post_alert_status,
    ("POST", "/api/device-status"): post_device_status,
    ("POST", "/api/run-cycle"): post_run_cycle,
    ("POST", "/api/train-model"): post_train_model,
    ("POST", "/api/investigate"): post_investigate,
    ("POST", "/api/investigate-anomaly"): post_investigate_anomaly,
    ("POST", "/api/rag-answer"): post_rag_answer,
    ("POST", "/api/rag-retrieve"): post_rag_retrieve,
    ("POST", "/api/demo/seed"): post_demo_seed,
    ("POST", "/api/demo/clear"): post_demo_clear,
    ("POST", "/api/pairing-code"): post_pairing_code,
}


class Handler(BaseHTTPRequestHandler):
    server_version = "SentraAPI/1.0"
    protocol_version = "HTTP/1.1"

    # -- plumbing ---------------------------------------------------------- #
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        LOG.info("%s - %s", self.address_string(), fmt % args)

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        try:
            parsed = json.loads(self.rfile.read(length).decode("utf-8"))
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        handler = ROUTES.get((method, path))
        if handler is None:
            self._send(404, {"ok": False, "error": f"no route for {method} {path}"})
            return
        try:
            data = handler(parse_qs(parsed.query), self._body() if method == "POST" else {})
        except ValueError as exc:
            self._send(400, {"ok": False, "error": str(exc)})
            return
        except Exception as exc:  # pragma: no cover - defensive
            LOG.error("request failed: %s\n%s", exc, traceback.format_exc())
            self._send(500, {"ok": False, "error": str(exc)})
            return
        self._send(200, {"ok": True, "data": data})

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")


def serve(host: str = "127.0.0.1", port: int = 8787) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
    httpd = ThreadingHTTPServer((host, port), Handler)
    LOG.info("SENTRA API listening on http://%s:%s", host, port)
    LOG.info("Try http://%s:%s/api/dashboard", host, port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        LOG.info("shutting down")
    finally:
        httpd.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="SENTRA AI JSON API bridge")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    serve(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
