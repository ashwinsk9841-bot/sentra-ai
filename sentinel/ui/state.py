"""Cached services and shared UI state.

Streamlit reruns every script on each interaction, so the repository, the ML
pipeline and the RAG pipeline are created once per server (``st.cache_resource``)
and the expensive reads are cached with a short TTL (``st.cache_data``).

Nothing here fabricates data: every loader returns what the repository actually
holds, and pages show an empty state when there is nothing to show.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Final

import pandas as pd
import streamlit as st

from ..config import Settings, get_settings
from ..database.repository import SentinelRepository
from ..ml.pipeline import AnomalyPipeline
from ..services import (
    AgentService,
    AnalyticsService,
    DemoService,
    MonitoringService,
    NotificationService,
)

__all__ = [
    "WINDOWS",
    "acknowledge_anomaly",
    "agent_service",
    "agent_status",
    "alerts",
    "analytics_service",
    "analytics_summary",
    "anomalies",
    "channels",
    "clear_caches",
    "clear_demo",
    "correlation",
    "create_pairing_code",
    "current_device",
    "demo_service",
    "device_choices",
    "documents",
    "fleet",
    "health_brief",
    "health_report",
    "hourly_profile",
    "init_state",
    "investigate",
    "investigate_anomaly",
    "log_sources",
    "logs",
    "monitoring_service",
    "network_metrics",
    "notification_feed",
    "notification_service",
    "overview",
    "pipeline",
    "process_snapshots",
    "rag_answer",
    "rag_delete_document",
    "rag_ingest_bytes",
    "rag_overview",
    "rag_retrieve",
    "read_controls",
    "refresh_all",
    "reliability",
    "repo",
    "revoke_device",
    "run_cycle",
    "run_demo",
    "select_device",
    "select_window",
    "set_alert_status",
    "set_device_status",
    "settings",
    "system_events",
    "system_metrics",
    "timeseries",
    "train_model",
    "unread_count",
    "window_report",
]

#: Selectable time windows, shortest first.
WINDOWS: Final[dict[str, str]] = {
    "1h": "Last hour",
    "6h": "Last 6 hours",
    "24h": "Last 24 hours",
    "7d": "Last 7 days",
    "30d": "Last 30 days",
}


# --------------------------------------------------------------------------- #
# Shared resources
# --------------------------------------------------------------------------- #
@st.cache_resource(show_spinner=False)
def settings() -> Settings:
    return get_settings()


@st.cache_resource(show_spinner=False)
def repo() -> SentinelRepository:
    from ..database import get_repository

    cfg = settings()
    cfg.ensure_directories()
    repository = get_repository(settings=cfg)
    repository.initialise()
    return repository


@st.cache_resource(show_spinner=False)
def monitoring_service() -> MonitoringService:
    return MonitoringService(repo(), settings())


@st.cache_resource(show_spinner=False)
def analytics_service() -> AnalyticsService:
    return AnalyticsService(repo(), settings(), service=monitoring_service())


@st.cache_resource(show_spinner=False)
def notification_service() -> NotificationService:
    return NotificationService(repo(), settings(), service=monitoring_service())


@st.cache_resource(show_spinner=False)
def agent_service() -> AgentService:
    return AgentService(repo(), settings(), service=monitoring_service())


@st.cache_resource(show_spinner=False)
def demo_service() -> DemoService:
    return DemoService(repo(), settings())


@st.cache_resource(show_spinner=False)
def pipeline() -> AnomalyPipeline:
    return AnomalyPipeline(repo(), settings())


# --------------------------------------------------------------------------- #
# Session state
# --------------------------------------------------------------------------- #
def init_state() -> None:
    """Initialise session state in one place."""
    defaults: dict[str, Any] = {
        "window": "24h",
        "device_id": None,
        "demo_status": None,
        "rag_conversation": [],
        "chat_input": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def clear_caches() -> None:
    """Drop cached reads so the next render shows fresh data."""
    for loader in (
        monitoring_service,
        analytics_service,
        notification_service,
        agent_service,
        demo_service,
    ):
        loader.clear()


def refresh_all() -> None:
    """Invalidate every cached read and rerun."""
    clear_caches()
    st.rerun()


# --------------------------------------------------------------------------- #
# Cached reads
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=15, show_spinner=False)
def device_choices() -> list[tuple[str, str]]:
    """``(device_id, label)`` for every registered device, most recent first."""
    frame = repo().list_devices()
    if frame.empty or "device_id" not in frame.columns:
        return []
    now = datetime.now(timezone.utc)
    rows: list[tuple[float, str, str]] = []
    for record in frame.to_dict("records"):
        device_id = str(record.get("device_id"))
        age = _age_seconds(record.get("last_seen"), now)
        status = str(record.get("status") or "UNKNOWN")
        name = str(record.get("name") or device_id)
        suffix = "  ·  demo" if _is_synthetic(record.get("meta")) else ""
        when = "never seen" if age is None else _ago(age)
        label = f"{name} ({device_id}){suffix} — {status}, {when}"
        rows.append((age if age is not None else 9e9, device_id, label))
    rows.sort(key=lambda r: (r[0], r[1]))
    return [(device_id, label) for _age, device_id, label in rows]


def _age_seconds(value: Any, now: datetime) -> float | None:
    if value is None or (isinstance(value, float) and value != value):
        return None
    stamp = pd.Timestamp(value)
    if stamp is pd.NaT or pd.isna(stamp):
        return None
    stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
    return max(0.0, (now - stamp).total_seconds())


def _ago(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s ago"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


def _is_synthetic(meta: Any) -> bool:
    """``meta`` may already be a dict or a JSON string depending on backend."""
    if isinstance(meta, Mapping):
        return bool(meta.get("synthetic") or meta.get("demo"))
    if isinstance(meta, str) and meta.strip():
        try:
            parsed = json.loads(meta)
        except (TypeError, ValueError):
            return False
        return bool(isinstance(parsed, Mapping) and (parsed.get("synthetic") or parsed.get("demo")))
    return False


@st.cache_data(ttl=10, show_spinner=False)
def overview(device_id: str, window: str) -> dict[str, Any]:
    return monitoring_service().overview(device_id, window=window)


@st.cache_data(ttl=10, show_spinner=False)
def timeseries(device_id: str, window: str) -> dict[str, Any]:
    return analytics_service().timeseries(device_id, window=window)


@st.cache_data(ttl=10, show_spinner=False)
def analytics_summary(device_id: str, window: str) -> dict[str, Any]:
    return analytics_service().summary(device_id, window=window)


@st.cache_data(ttl=10, show_spinner=False)
def reliability(device_id: str, window: str) -> dict[str, Any]:
    return analytics_service().reliability(device_id, window=window)


@st.cache_data(ttl=10, show_spinner=False)
def correlation(device_id: str, window: str) -> pd.DataFrame:
    return analytics_service().metric_correlation(device_id, window=window)


@st.cache_data(ttl=10, show_spinner=False)
def hourly_profile(device_id: str, window: str) -> pd.DataFrame:
    return analytics_service().hourly_profile(device_id, window=window)


@st.cache_data(ttl=20, show_spinner=False)
def documents() -> pd.DataFrame:
    return repo().list_documents()


@st.cache_data(ttl=20, show_spinner=False)
def rag_overview() -> dict[str, Any]:
    """Vector-store stats plus observed query quality, all from the repository."""
    health = health_report()
    return {
        "stats": health.get("rag", {}),
        "usage": analytics_service().rag_usage(),
        "history": analytics_service().investigation_history(limit=20),
    }


@st.cache_data(ttl=10, show_spinner=False)
def notification_feed(device_id: str, window: str, limit: int) -> list[dict[str, Any]]:
    feed = notification_service().feed(device_id, window=window, limit=limit)
    return [n.as_dict() for n in feed]


@st.cache_data(ttl=10, show_spinner=False)
def unread_count(device_id: str) -> int:
    return notification_service().unread_count(device_id)


@st.cache_data(ttl=10, show_spinner=False)
def anomalies(device_id: str, window: str, limit: int = 500) -> pd.DataFrame:
    return monitoring_service().anomalies(device_id, window=window, limit=limit)


@st.cache_data(ttl=10, show_spinner=False)
def alerts(device_id: str, window: str, limit: int = 500) -> pd.DataFrame:
    return monitoring_service().alerts(device_id, window=window, limit=limit)


@st.cache_data(ttl=10, show_spinner=False)
def logs(
    device_id: str,
    window: str,
    *,
    levels: tuple[str, ...] | None = None,
    source: str | None = None,
    search: str | None = None,
    limit: int = 1000,
) -> pd.DataFrame:
    return monitoring_service().logs(
        device_id,
        window=window,
        levels=list(levels) if levels else None,
        source=source,
        search=search,
        limit=limit,
    )


@st.cache_data(ttl=30, show_spinner=False)
def log_sources(device_id: str) -> list[str]:
    return monitoring_service().log_sources(device_id)


@st.cache_data(ttl=10, show_spinner=False)
def network_metrics(device_id: str, window: str, limit: int = 3000) -> pd.DataFrame:
    return monitoring_service().network_metrics(device_id, window=window, limit=limit)


@st.cache_data(ttl=10, show_spinner=False)
def process_snapshots(device_id: str, limit: int = 500) -> pd.DataFrame:
    return monitoring_service().process_snapshots(device_id, limit=limit)


@st.cache_data(ttl=10, show_spinner=False)
def system_metrics(device_id: str, window: str, limit: int = 3000) -> pd.DataFrame:
    return monitoring_service().system_metrics(device_id, window=window, limit=limit)


@st.cache_data(ttl=20, show_spinner=False)
def channels() -> list[dict[str, Any]]:
    return notification_service().channels()


@st.cache_data(ttl=20, show_spinner=False)
def fleet() -> pd.DataFrame:
    return agent_service().fleet()


@st.cache_data(ttl=20, show_spinner=False)
def agent_status(device_id: str) -> dict[str, Any]:
    return agent_service().status(device_id)


@st.cache_data(ttl=20, show_spinner=False)
def health_report() -> dict[str, Any]:
    return monitoring_service().health()


@st.cache_data(ttl=20, show_spinner=False)
def system_events(limit: int = 200) -> pd.DataFrame:
    return repo().fetch_system_events(limit=limit)


# --------------------------------------------------------------------------- #
# Mutations (demo mode, pairing, detection control)
# --------------------------------------------------------------------------- #
def run_demo(
    *, samples: int, scenario: str, seed: int, train_model: bool, include_document: bool
) -> dict[str, Any]:
    """Seed the labelled demo dataset, then drop every cached read."""
    result = demo_service().seed(
        samples=samples,
        scenario=scenario,
        seed=seed,
        train_model=train_model,
        include_document=include_document,
    )
    monitoring_service().refresh_device_labels()
    clear_caches()
    return result.as_dict() if hasattr(result, "as_dict") else {"risk_score": result.risk_score}


def clear_demo() -> dict[str, Any]:
    summary = demo_service().clear()
    monitoring_service().refresh_device_labels()
    clear_caches()
    return summary


def create_pairing_code(ttl_minutes: int = 30) -> dict[str, Any]:
    code = agent_service().create_pairing_code(ttl_minutes=ttl_minutes)
    clear_caches()
    return code


def set_device_status(device_id: str, status: str) -> bool:
    changed = agent_service().set_status(device_id, status)
    clear_caches()
    return changed


def revoke_device(device_id: str) -> bool:
    changed = agent_service().revoke_device(device_id)
    monitoring_service().refresh_device_labels()
    clear_caches()
    return changed


def set_alert_status(alert_id: str, status: str) -> bool:
    changed = monitoring_service().set_alert_status(alert_id, status)
    clear_caches()
    return changed


def acknowledge_anomaly(anomaly_id: str) -> bool:
    changed = monitoring_service().acknowledge_anomaly(anomaly_id)
    clear_caches()
    return changed


def run_cycle(device_id: str, *, train: bool = True) -> Any:
    result = monitoring_service().run_cycle(device_id, train=train)
    clear_caches()
    return result


def train_model(device_id: str, *, force: bool = False) -> Any:
    result = monitoring_service().train_model(device_id, force=force)
    clear_caches()
    return result


def rag_ingest_bytes(data: bytes, filename: str, title: str | None, source: str) -> Any:
    report = monitoring_service().rag.ingest_bytes(
        data, filename, title=title, source=source
    )
    clear_caches()
    return report


def rag_delete_document(document_id: str) -> bool:
    deleted = monitoring_service().rag.delete_document(document_id)
    clear_caches()
    return deleted


def rag_answer(query: str, *, top_k: int | None, use_llm: bool) -> Any:
    return monitoring_service().rag.answer(
        query, top_k=top_k, use_llm=use_llm, persist=True
    )


def rag_retrieve(query: str, *, top_k: int) -> Any:
    return monitoring_service().rag.retrieve(query, top_k=top_k, persist=False)


def investigate(question: str, device_id: str, history: list[tuple[str, str]]) -> Any:
    return monitoring_service().investigator.ask(
        question, device_id=device_id, history=history, persist=True
    )


def investigate_anomaly(anomaly_id: str, *, question: str | None) -> Any:
    return monitoring_service().investigator.investigate(
        anomaly_id, question=question, persist=True
    )


def health_brief(device_id: str) -> Any:
    result = monitoring_service().investigator.health_brief(device_id)
    clear_caches()
    return result


def window_report(device_id: str, window_label: str) -> Any:
    result = monitoring_service().investigator.window_report(
        device_id, window_label=window_label
    )
    clear_caches()
    return result


# --------------------------------------------------------------------------- #
# Widgets
# --------------------------------------------------------------------------- #
def current_device() -> str:
    """The device every page should use right now."""
    return st.session_state.get("device_id") or ""


def select_device(key: str = "device_picker", *, label: str = "Device") -> str:
    """Device selector shared by every page."""
    choices = device_choices()
    if not choices:
        st.session_state["device_id"] = None
        return ""
    ids = [device_id for device_id, _label in choices]
    labels = {device_id: label for device_id, label in choices}
    current = st.session_state.get("device_id")
    index = ids.index(current) if current in ids else 0
    chosen = st.selectbox(
        label,
        ids,
        index=index,
        format_func=lambda device_id: labels.get(device_id, device_id),
        key=key,
    )
    st.session_state["device_id"] = chosen
    return chosen


def select_window(key: str = "window_picker", *, default: str = "24h") -> str:
    """Time-window selector shared by every page."""
    chosen = st.segmented_control(
        "Time range",
        options=list(WINDOWS),
        default=st.session_state.get("window", default),
        format_func=lambda key: WINDOWS[key],
        key=key,
    )
    value = chosen or st.session_state.get("window", default)
    st.session_state["window"] = value
    return value


def read_controls(default: str = "24h") -> tuple[str, str]:
    """Device and window chosen in the sidebar.

    Pages call this instead of rendering their own selectors so the controls
    exist in exactly one place.
    """
    return current_device(), st.session_state.get("window", default)
