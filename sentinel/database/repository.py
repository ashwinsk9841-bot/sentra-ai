"""Repository contract shared by the Supabase and local SQLite backends.

The rest of the application only ever talks to a :class:`SentinelRepository`, so
switching between the hosted Supabase project and the on-disk store is a
configuration concern rather than a code change. Every method returns plain
``dict`` / ``pandas.DataFrame`` values so the UI layer never touches a
backend-specific response object.
"""

from __future__ import annotations

import abc
import json
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from ..constants import RISK_BANDS, SEVERITY_LOW
from ..exceptions import DatabaseError

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def utcnow() -> datetime:
    """Timezone-aware current time (UTC)."""
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


def to_iso(value: Any) -> str | None:
    """Serialise a datetime (or pass through an ISO string) for storage."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def parse_dt(value: Any) -> datetime | None:
    """Best-effort parse of a stored timestamp into an aware datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def json_safe(value: Any) -> Any:
    """Coerce a value into something ``json.dumps`` accepts.

    Used for the free-form ``meta``/``evidence``/``raw`` columns, which hold
    pandas scalars, numpy floats, datetimes and nested dicts.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else value
    if isinstance(value, datetime):
        return to_iso(value)
    if isinstance(value, Mapping):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]
    if isinstance(value, (pd.Series,)):
        return [json_safe(v) for v in value.tolist()]
    if isinstance(value, pd.DataFrame):
        return json_safe(value.to_dict(orient="records"))
    if hasattr(value, "item"):
        try:
            return json_safe(value.item())
        except Exception:
            pass
    if hasattr(value, "isoformat"):
        try:
            return to_iso(value)
        except Exception:
            pass
    return str(value)


def dump_json(value: Any) -> str | None:
    safe = json_safe(value)
    if safe is None:
        return None
    try:
        return json.dumps(safe, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return json.dumps(str(safe))


def load_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", "replace")
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def severity_for_risk(risk_score: float) -> str:
    """Map a 0-100 risk score onto the documented severity bands."""
    score = max(0.0, min(100.0, float(risk_score)))
    for floor, label in RISK_BANDS:
        if score >= floor:
            return label
    return SEVERITY_LOW


def chunk_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Normalise a document-chunk payload.

    The RAG layer emits ``metadata`` (its natural Python name) while the
    database column is ``meta``; this keeps both call sites honest without
    forcing either side to know about the other's vocabulary.
    """
    content = row.get("content") or ""
    payload: dict[str, Any] = {
        "document_id": row["document_id"],
        "chunk_index": int(row.get("chunk_index") or 0),
        "content": content,
        "token_estimate": int(row.get("token_estimate") or max(1, len(content) // 4)),
        "char_start": row.get("char_start"),
        "char_end": row.get("char_end"),
        "page": row.get("page"),
        "heading": row.get("heading"),
        "meta": row.get("meta") if row.get("meta") is not None else row.get("metadata") or {},
    }
    embedding = row.get("embedding")
    payload["embedding"] = [float(x) for x in embedding] if embedding is not None else None
    return payload


def frame(rows: Iterable[Mapping[str, Any]] | None) -> pd.DataFrame:
    """Build a DataFrame with a stable column order and no index."""
    records = [dict(r) for r in (rows or [])]
    if not records:
        return pd.DataFrame()
    frame_ = pd.DataFrame(records)
    if "ts" in frame_.columns:
        frame_["ts"] = pd.to_datetime(frame_["ts"], utc=True, errors="coerce")
        frame_ = frame_.sort_values("ts", kind="stable").reset_index(drop=True)
    return frame_


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class BackendHealth:
    """Result of a backend connectivity probe."""

    name: str
    connected: bool
    latency_ms: float = 0.0
    detail: str = ""
    mode: str = "primary"
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "connected": self.connected,
            "latency_ms": round(self.latency_ms, 2),
            "detail": self.detail,
            "mode": self.mode,
            "error": self.error,
        }


# --------------------------------------------------------------------------- #
# Abstract repository
# --------------------------------------------------------------------------- #
class SentinelRepository(abc.ABC):
    """Data-access contract for every Sentinel AI persistence backend."""

    backend_name: str = "abstract"

    # -- lifecycle -------------------------------------------------------- #
    @abc.abstractmethod
    def health(self) -> BackendHealth:
        """Probe connectivity. Must never raise."""

    @abc.abstractmethod
    def initialise(self) -> None:
        """Create schema if needed. Must never raise."""

    # -- devices ---------------------------------------------------------- #
    @abc.abstractmethod
    def create_pairing_code(self, ttl_minutes: int = 30) -> tuple[str, datetime]:
        """Create a short-lived pairing code an agent can present to register."""

    @abc.abstractmethod
    def register_device(
        self,
        *,
        device_id: str,
        name: str,
        os_name: str,
        os_version: str,
        hostname: str,
        arch: str,
        agent_version: str,
        pairing_code: str | None,
        python_version: str,
        interval_s: int,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Register (or re-register) a device. Raises on an invalid pairing code."""

    @abc.abstractmethod
    def list_devices(self) -> pd.DataFrame: ...

    @abc.abstractmethod
    def get_device(self, device_id: str) -> dict[str, Any] | None: ...

    @abc.abstractmethod
    def set_device_status(self, device_id: str, status: str) -> bool: ...

    @abc.abstractmethod
    def delete_device(self, device_id: str) -> bool: ...

    @abc.abstractmethod
    def touch_device(
        self,
        device_id: str,
        *,
        risk_score: int | None = None,
        cpu_percent: float | None = None,
        disk_percent: float | None = None,
        agent_version: str | None = None,
        source_ip: str | None = None,
    ) -> bool:
        """Update last-seen liveness and the cached device-level risk."""

    @abc.abstractmethod
    def resolve_device_pk(self, device_id: str) -> str | None:
        """Map the public device id onto the backend's internal primary key.

        Telemetry writes pass this value through as ``device_pk`` so callers
        never need to know whether the backend keys on a uuid or a text id.
        """

    # -- telemetry -------------------------------------------------------- #
    @abc.abstractmethod
    def insert_system_metrics(self, rows: Sequence[Mapping[str, Any]]) -> int: ...

    @abc.abstractmethod
    def insert_network_metrics(self, rows: Sequence[Mapping[str, Any]]) -> int: ...

    @abc.abstractmethod
    def insert_process_snapshots(self, rows: Sequence[Mapping[str, Any]]) -> int: ...

    @abc.abstractmethod
    def fetch_system_metrics(
        self,
        *,
        device_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 2000,
        newest_first: bool = False,
    ) -> pd.DataFrame: ...

    @abc.abstractmethod
    def fetch_network_metrics(
        self,
        *,
        device_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 2000,
    ) -> pd.DataFrame: ...

    @abc.abstractmethod
    def fetch_process_snapshots(
        self, *, device_id: str | None = None, ts: datetime | None = None, limit: int = 500
    ) -> pd.DataFrame: ...

    @abc.abstractmethod
    def latest_system_metrics(self, device_id: str | None = None) -> dict[str, Any] | None: ...

    @abc.abstractmethod
    def latest_network_metrics(self, device_id: str | None = None) -> dict[str, Any] | None: ...

    @abc.abstractmethod
    def delete_old_telemetry(self, *, before: datetime) -> int: ...

    # -- logs ------------------------------------------------------------- #
    @abc.abstractmethod
    def insert_logs(self, rows: Sequence[Mapping[str, Any]]) -> int: ...

    @abc.abstractmethod
    def fetch_logs(
        self,
        *,
        device_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        levels: Sequence[str] | None = None,
        source: str | None = None,
        search: str | None = None,
        limit: int = 1000,
    ) -> pd.DataFrame: ...

    @abc.abstractmethod
    def log_sources(self, device_id: str | None = None) -> list[str]: ...

    # -- anomalies / alerts ------------------------------------------------ #
    @abc.abstractmethod
    def insert_anomalies(self, rows: Sequence[Mapping[str, Any]]) -> list[str]:
        """Persist anomalies; returns the generated ids in input order."""

    @abc.abstractmethod
    def fetch_anomalies(
        self,
        *,
        device_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        severities: Sequence[str] | None = None,
        metric: str | None = None,
        limit: int = 500,
    ) -> pd.DataFrame: ...

    @abc.abstractmethod
    def get_anomaly(self, anomaly_id: str) -> dict[str, Any] | None: ...

    @abc.abstractmethod
    def acknowledge_anomaly(self, anomaly_id: str) -> bool: ...

    @abc.abstractmethod
    def insert_alerts(self, rows: Sequence[Mapping[str, Any]]) -> int: ...

    @abc.abstractmethod
    def fetch_alerts(
        self,
        *,
        device_id: str | None = None,
        statuses: Sequence[str] | None = None,
        severities: Sequence[str] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 500,
    ) -> pd.DataFrame: ...

    @abc.abstractmethod
    def set_alert_status(self, alert_id: str, status: str) -> bool: ...

    @abc.abstractmethod
    def insert_risk_events(self, rows: Sequence[Mapping[str, Any]]) -> int: ...

    @abc.abstractmethod
    def fetch_risk_events(
        self, *, device_id: str | None = None, since: datetime | None = None, limit: int = 1000
    ) -> pd.DataFrame: ...

    # -- documents / RAG --------------------------------------------------- #
    @abc.abstractmethod
    def create_document(
        self,
        *,
        filename: str,
        title: str | None,
        content_type: str,
        size_bytes: int,
        checksum: str,
        source: str = "UPLOAD",
        meta: Mapping[str, Any] | None = None,
    ) -> str: ...

    @abc.abstractmethod
    def update_document(
        self,
        document_id: str,
        *,
        status: str | None = None,
        error: str | None = None,
        chunk_count: int | None = None,
        pages: int | None = None,
    ) -> bool: ...

    @abc.abstractmethod
    def list_documents(self) -> pd.DataFrame: ...

    @abc.abstractmethod
    def get_document(self, document_id: str) -> dict[str, Any] | None: ...

    @abc.abstractmethod
    def delete_document(self, document_id: str) -> bool: ...

    @abc.abstractmethod
    def insert_chunks(
        self, rows: Sequence[Mapping[str, Any]], *, include_embeddings: bool = True
    ) -> int: ...

    @abc.abstractmethod
    def fetch_chunks(self, *, document_id: str | None = None, limit: int = 100000) -> pd.DataFrame: ...

    @abc.abstractmethod
    def delete_chunks(self, document_id: str) -> int: ...

    @abc.abstractmethod
    def insert_rag_query(
        self,
        *,
        query: str,
        document_id: str | None,
        top_k: int,
        provider: str,
        hit_count: int,
        top_score: float,
        latency_ms: int,
        answer: str | None = None,
        sources: Sequence[Mapping[str, Any]] | None = None,
    ) -> int: ...

    @abc.abstractmethod
    def fetch_rag_queries(self, limit: int = 100) -> pd.DataFrame: ...

    @abc.abstractmethod
    def insert_investigation(
        self,
        *,
        device_id: str | None,
        anomaly_id: str | None,
        question: str,
        answer: str,
        provider: str,
        model: str,
        evidence: Mapping[str, Any] | None = None,
        confidence: float | None = None,
        citations: Sequence[Mapping[str, Any]] | None = None,
    ) -> int: ...

    @abc.abstractmethod
    def fetch_investigations(self, limit: int = 100) -> pd.DataFrame: ...

    # -- system events ----------------------------------------------------- #
    @abc.abstractmethod
    def insert_system_events(self, rows: Sequence[Mapping[str, Any]]) -> int: ...

    @abc.abstractmethod
    def fetch_system_events(self, limit: int = 200) -> pd.DataFrame: ...

    # -- aggregates -------------------------------------------------------- #
    @abc.abstractmethod
    def table_counts(self) -> dict[str, int]: ...

    # ------------------------------------------------------------------ #
    def close(self) -> None:  # pragma: no cover - overridden where needed
        """Release resources. Safe to call repeatedly."""


__all__ = [
    "BackendHealth",
    "SentinelRepository",
    "DatabaseError",
    "chunk_row",
    "dump_json",
    "frame",
    "json_safe",
    "load_json",
    "new_id",
    "parse_dt",
    "severity_for_risk",
    "to_iso",
    "utcnow",
]
