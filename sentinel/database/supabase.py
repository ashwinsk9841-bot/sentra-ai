"""Supabase (Postgres) implementation of :class:`SentinelRepository`.

Uses the official ``supabase-py`` PostgREST client. Every method degrades to a
:class:`~sentinel.exceptions.DatabaseError` rather than propagating raw client
exceptions, and :meth:`SupabaseRepository.health` never raises so the dashboard
can keep rendering when Supabase is unreachable.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from ..constants import ALERT_STATUS_NEW
from ..exceptions import ConfigurationError, DatabaseError, DeviceNotAuthorizedError
from ..logger import get_logger
from .repository import (
    BackendHealth,
    SentinelRepository,
    chunk_row,
    dump_json,
    frame,
    load_json,
    new_id,
    severity_for_risk,
    to_iso,
    utcnow,
)

log = get_logger("database.supabase")

JSON_COLUMNS = ("meta", "raw", "attributes", "evidence", "features", "model_scores",
                "composite", "sources", "citations")

#: Sentinel value used when a public device id cannot be resolved to a row.
#: Nothing can match it, so a filter stays scoped instead of returning all rows.
_UNKNOWN_DEVICE_PK = "00000000-0000-0000-0000-000000000000"


class SupabaseRepository(SentinelRepository):
    """Postgres-backed repository with identical semantics to the local store."""

    backend_name = "supabase"

    def __init__(
        self,
        url: str,
        key: str,
        *,
        service_key: str | None = None,
        schema: str = "public",
        chunk_batch: int = 500,
    ) -> None:
        if not url or not key:
            raise ConfigurationError(
                "Supabase credentials are incomplete.",
                hint="Set both SUPABASE_URL and SUPABASE_KEY.",
            )
        self.url = url
        self.schema = schema
        self.chunk_batch = max(1, chunk_batch)
        self._service_key = service_key
        self._client: Any | None = None
        self._client_key = key
        self._schema_ready = False

    # -- plumbing ---------------------------------------------------------- #
    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                from supabase import create_client
            except ImportError as exc:  # pragma: no cover - dependency missing
                raise ConfigurationError(
                    "The 'supabase' package is not installed.",
                    hint="Run: pip install supabase",
                ) from exc
            try:
                self._client = create_client(
                    self.url,
                    self._service_key or self._client_key,
                    options={"schema": self.schema},
                )
            except Exception as exc:
                raise DatabaseError(f"Could not create Supabase client: {exc}") from exc
        return self._client

    def _run(self, builder: Any, *, what: str) -> Any:
        try:
            response = builder.execute()
        except Exception as exc:
            raise DatabaseError(f"Supabase request failed ({what}): {exc}") from exc
        error = getattr(response, "error", None)
        if error:
            raise DatabaseError(f"Supabase error ({what}): {error}")
        return response

    def _select(self, table: str, columns: str = "*") -> Any:
        return self.client.table(table).select(columns)

    def _insert(self, table: str, rows: Sequence[Mapping[str, Any]]) -> Any:
        payload = [dict(r) for r in rows]
        return self._run(
            self.client.table(table).insert(payload), what=f"insert {table}"
        )

    def _update(self, table: str, values: Mapping[str, Any], **filters: Any) -> Any:
        builder = self.client.table(table).update(dict(values))
        for column, value in filters.items():
            builder = builder.eq(column, value)
        return self._run(builder, what=f"update {table}")

    def _delete(self, table: str, **filters: Any) -> Any:
        builder = self.client.table(table).delete()
        for column, value in filters.items():
            builder = builder.eq(column, value)
        return self._run(builder, what=f"delete {table}")

    def _batched(self, table: str, rows: Sequence[Mapping[str, Any]]) -> int:
        total = 0
        records = [dict(r) for r in rows]
        for start in range(0, len(records), self.chunk_batch):
            batch = records[start : start + self.chunk_batch]
            response = self._insert(table, batch)
            total += len(getattr(response, "data", None) or batch)
        return total

    @staticmethod
    def _data(response: Any) -> list[dict[str, Any]]:
        return [dict(r) for r in (getattr(response, "data") or [])]

    @staticmethod
    def _normalise(df: pd.DataFrame, json_columns: Sequence[str] = JSON_COLUMNS) -> pd.DataFrame:
        if df.empty:
            return df
        for column in json_columns:
            if column in df.columns:
                df[column] = df[column].map(load_json)
        return df

    def close(self) -> None:
        self._client = None

    # -- lifecycle ---------------------------------------------------------- #
    def initialise(self) -> None:
        """Supabase schema is applied via ``database/schema.sql`` in the SQL editor.

        This method verifies connectivity and the presence of the core tables so
        misconfiguration surfaces immediately with a clear message.
        """
        if self._schema_ready:
            return
        self.health()
        probe = self._run(self._select("devices", "id").limit(1), what="probe devices")
        if probe is None:  # pragma: no cover - defensive
            raise DatabaseError("Supabase probe returned no response.")
        self._schema_ready = True

    def health(self) -> BackendHealth:
        started = time.perf_counter()
        try:
            response = self._run(self._select("devices", "id").limit(1), what="health")
            latency = (time.perf_counter() - started) * 1000
            rows = getattr(response, "data", None) or []
            return BackendHealth(
                name=self.backend_name,
                connected=True,
                latency_ms=latency,
                detail=f"project reachable, {len(rows)} device row(s) sampled",
                mode="primary",
            )
        except Exception as exc:
            return BackendHealth(
                name=self.backend_name,
                connected=False,
                latency_ms=(time.perf_counter() - started) * 1000,
                detail="Supabase unreachable",
                error=str(exc)[:400],
            )

    # -- devices -------------------------------------------------------------- #
    def create_pairing_code(self, ttl_minutes: int = 30) -> tuple[str, datetime]:
        import secrets

        code = f"{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}"
        now = utcnow()
        expires = now + timedelta(minutes=max(1, ttl_minutes))
        self._insert(
            "pairing_codes",
            [{"code": code, "created_at": to_iso(now), "expires_at": to_iso(expires)}],
        )
        return code, expires

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
        now = utcnow()
        existing = self._data(
            self._run(self._select("devices").eq("device_id", device_id).limit(1), what="device")
        )
        if existing:
            record = existing[0]
            if record.get("status") == "REVOKED":
                raise DeviceNotAuthorizedError(
                    f"Device {device_id} was revoked and cannot re-register."
                )
            self._update(
                "devices",
                {
                    "name": name,
                    "os_name": os_name,
                    "os_version": os_version,
                    "hostname": hostname,
                    "arch": arch,
                    "agent_version": agent_version,
                    "last_seen": to_iso(now),
                    "updated_at": to_iso(now),
                    "meta": metadata or {},
                },
                id=record["id"],
            )
            self._update(
                "agents",
                {
                    "agent_version": agent_version,
                    "python_version": python_version,
                    "platform": f"{os_name} {os_version}".strip(),
                    "interval_s": interval_s,
                    "last_heartbeat": to_iso(now),
                    "consecutive_failures": 0,
                    "last_error": None,
                    "updated_at": to_iso(now),
                },
                device_pk=record["id"],
            )
            return self.get_device(device_id) or {}

        authorized = False
        if pairing_code:
            codes = self._data(
                self._run(
                    self._select("pairing_codes")
                    .eq("code", pairing_code)
                    .is_("used_at", "null")
                    .limit(1),
                    what="pairing lookup",
                )
            )
            if codes:
                expires = str(codes[0].get("expires_at") or "")
                from .repository import parse_dt

                expiry_dt = parse_dt(expires)
                if expiry_dt and expiry_dt > now:
                    authorized = True
                    self._update(
                        "pairing_codes",
                        {"used_at": to_iso(now), "used_by": device_id},
                        code=pairing_code,
                    )

        device_row = {
            "id": new_id(),
            "device_id": device_id,
            "name": name,
            "os_name": os_name,
            "os_version": os_version,
            "hostname": hostname,
            "arch": arch,
            "agent_version": agent_version,
            "status": "AUTHORIZED" if authorized else "PENDING",
            "pairing_code": pairing_code,
            "authorized_at": to_iso(now) if authorized else None,
            "last_seen": to_iso(now),
            "meta": metadata or {},
            "created_at": to_iso(now),
            "updated_at": to_iso(now),
        }
        self._insert("devices", [device_row])
        self._insert(
            "agents",
            [
                {
                    "id": new_id(),
                    "device_pk": device_row["id"],
                    "agent_version": agent_version,
                    "python_version": python_version,
                    "platform": f"{os_name} {os_version}".strip(),
                    "interval_s": interval_s,
                    "last_heartbeat": to_iso(now),
                    "created_at": to_iso(now),
                    "updated_at": to_iso(now),
                }
            ],
        )
        return self.get_device(device_id) or {}

    def list_devices(self) -> pd.DataFrame:
        rows = self._data(self._run(self._select("devices").order("last_seen", desc=False), what="list devices"))
        rows.sort(key=lambda r: (r.get("last_seen") or ""), reverse=True)
        return self._normalise(frame(rows), ("meta",))

    def get_device(self, device_id: str) -> dict[str, Any] | None:
        rows = self._data(
            self._run(self._select("devices").eq("device_id", device_id).limit(1), what="get device")
        )
        if not rows:
            return None
        record = rows[0]
        record["meta"] = load_json(record.get("meta"))
        try:
            agents = self._data(
                self._run(
                    self._select("agents").eq("device_pk", record["id"]).limit(1),
                    what="get agent",
                )
            )
            if agents:
                for key, value in agents[0].items():
                    record.setdefault(key, value)
        except DatabaseError:
            pass
        return record

    def set_device_status(self, device_id: str, status: str) -> bool:
        rows = self._data(
            self._run(self._select("devices").eq("device_id", device_id).limit(1), what="device pk")
        )
        if not rows:
            return False
        values: dict[str, Any] = {"status": status, "updated_at": to_iso(utcnow())}
        if status == "AUTHORIZED" and not rows[0].get("authorized_at"):
            values["authorized_at"] = to_iso(utcnow())
        self._update("devices", values, id=rows[0]["id"])
        return True

    def delete_device(self, device_id: str) -> bool:
        rows = self._data(
            self._run(self._select("devices").eq("device_id", device_id).limit(1), what="device pk")
        )
        if not rows:
            return False
        self._delete("devices", id=rows[0]["id"])
        return True

    def touch_device(
        self,
        device_id: str,
        *,
        risk_score: int | None = None,
        cpu_percent: float | None = None,
        memory_percent: float | None = None,
        disk_percent: float | None = None,
        agent_version: str | None = None,
        source_ip: str | None = None,
    ) -> bool:
        now = to_iso(utcnow())
        values: dict[str, Any] = {"last_seen": now, "updated_at": now}
        for key, value in (
            ("risk_score", risk_score),
            ("cpu_percent", cpu_percent),
            ("memory_percent", memory_percent),
            ("disk_percent", disk_percent),
            ("agent_version", agent_version),
            ("agent_ip", source_ip),
        ):
            if value is not None:
                values[key] = value
        return bool(self._data(self._update("devices", values, device_id=device_id)))

    def resolve_device_pk(self, device_id: str) -> str | None:
        rows = self._data(
            self._run(self._select("devices", "id").eq("device_id", device_id).limit(1), what="device pk")
        )
        return rows[0]["id"] if rows else None

    def _device_filter(self, builder: Any, device_id: str | None) -> Any:
        """Scope a telemetry filter by the internal ``devices.id`` primary key.

        The public ``fetch_*`` methods take the operator-facing ``device_id``,
        but every telemetry table stores a foreign key to ``devices.id``.
        Filtering on the public value would silently match nothing, so the
        primary key is resolved first. An unknown device resolves to a sentinel
        that cannot match, which keeps queries tenant-safe instead of falling
        back to "all devices".
        """
        if not device_id:
            return builder
        return builder.eq("device_id", self.resolve_device_pk(device_id) or _UNKNOWN_DEVICE_PK)

    # -- telemetry ------------------------------------------------------------- #
    def insert_system_metrics(self, rows: Sequence[Mapping[str, Any]]) -> int:
        payload = [
            {
                "device_id": r["device_pk"],
                "ts": to_iso(r["ts"]),
                "cpu_percent": r.get("cpu_percent"),
                "memory_percent": r.get("memory_percent"),
                "disk_percent": r.get("disk_percent"),
                "swap_percent": r.get("swap_percent"),
                "load_average": r.get("load_average"),
                "process_count": r.get("process_count"),
                "thread_count": r.get("thread_count"),
                "handle_count": r.get("handle_count"),
                "disk_free_gb": r.get("disk_free_gb"),
                "disk_read_mbps": r.get("disk_read_mbps"),
                "disk_write_mbps": r.get("disk_write_mbps"),
                "context_switch_rate": r.get("context_switch_rate"),
                "uptime_seconds": r.get("uptime_seconds"),
                "temperature_c": r.get("temperature_c"),
                "raw": r.get("raw") or {},
            }
            for r in rows
        ]
        return self._batched("system_metrics", payload)

    def insert_network_metrics(self, rows: Sequence[Mapping[str, Any]]) -> int:
        payload = [
            {
                "device_id": r["device_pk"],
                "ts": to_iso(r["ts"]),
                "iface": r.get("iface"),
                "bytes_sent": r.get("bytes_sent"),
                "bytes_recv": r.get("bytes_recv"),
                "packets_sent": r.get("packets_sent"),
                "packets_recv": r.get("packets_recv"),
                "errin": r.get("errin"),
                "errout": r.get("errout"),
                "dropin": r.get("dropin"),
                "dropout": r.get("dropout"),
                "sent_mbps": r.get("sent_mbps"),
                "recv_mbps": r.get("recv_mbps"),
                "connections": r.get("connections"),
                "raw": r.get("raw") or {},
            }
            for r in rows
        ]
        return self._batched("network_metrics", payload)

    def insert_process_snapshots(self, rows: Sequence[Mapping[str, Any]]) -> int:
        payload = [
            {
                "device_id": r["device_pk"],
                "ts": to_iso(r["ts"]),
                "pid": r.get("pid"),
                "ppid": r.get("ppid"),
                "name": r.get("name"),
                "owner": r.get("owner"),
                "status": r.get("status"),
                "cpu_percent": r.get("cpu_percent"),
                "memory_percent": r.get("memory_percent"),
                "rss_mb": r.get("rss_mb"),
                "num_threads": r.get("num_threads"),
                "create_time": to_iso(r["create_time"]) if r.get("create_time") else None,
            }
            for r in rows
        ]
        return self._batched("process_snapshots", payload)

    def fetch_system_metrics(
        self,
        *,
        device_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 2000,
        newest_first: bool = False,
    ) -> pd.DataFrame:
        builder = self._select("system_metrics")
        if device_id:
            builder = self._device_filter(builder, device_id)
        if since is not None:
            builder = builder.gte("ts", to_iso(since))
        if until is not None:
            builder = builder.lte("ts", to_iso(until))
        builder = builder.order("ts", desc=bool(newest_first)).limit(int(limit))
        return self._normalise(frame(self._data(self._run(builder, what="system metrics"))))

    def fetch_network_metrics(
        self,
        *,
        device_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 2000,
    ) -> pd.DataFrame:
        builder = self._select("network_metrics")
        if device_id:
            builder = self._device_filter(builder, device_id)
        if since is not None:
            builder = builder.gte("ts", to_iso(since))
        if until is not None:
            builder = builder.lte("ts", to_iso(until))
        builder = builder.order("ts").limit(int(limit))
        return self._normalise(frame(self._data(self._run(builder, what="network metrics"))))

    def fetch_process_snapshots(
        self, *, device_id: str | None = None, ts: datetime | None = None, limit: int = 500
    ) -> pd.DataFrame:
        builder = self._select("process_snapshots")
        if device_id:
            builder = self._device_filter(builder, device_id)
        if ts is not None:
            builder = builder.eq("ts", to_iso(ts))
        builder = builder.order("cpu_percent", desc=True).limit(int(limit))
        return frame(self._data(self._run(builder, what="process snapshots")))

    def latest_system_metrics(self, device_id: str | None = None) -> dict[str, Any] | None:
        df = self.fetch_system_metrics(device_id=device_id, limit=1, newest_first=True)
        if df.empty:
            return None
        row = df.iloc[0].to_dict()
        row.pop("raw", None)
        return row

    def latest_network_metrics(self, device_id: str | None = None) -> dict[str, Any] | None:
        builder = self._select("network_metrics")
        if device_id:
            builder = self._device_filter(builder, device_id)
        builder = builder.order("ts", desc=True).limit(1)
        rows = self._data(self._run(builder, what="latest network"))
        if not rows:
            return None
        row = rows[0]
        row.pop("raw", None)
        return row

    def delete_old_telemetry(self, *, before: datetime) -> int:
        stamp = to_iso(before)
        removed = 0
        for table in ("system_metrics", "network_metrics", "process_snapshots", "logs", "risk_events"):
            try:
                response = self._run(
                    self.client.table(table).delete().lt("ts", stamp), what=f"prune {table}"
                )
                removed += len(getattr(response, "data", None) or [])
            except DatabaseError as exc:
                log.warning("Could not prune %s: %s", table, exc)
        return removed

    # -- logs ------------------------------------------------------------------ #
    def insert_logs(self, rows: Sequence[Mapping[str, Any]]) -> int:
        payload = [
            {
                "device_id": r["device_pk"],
                "ts": to_iso(r["ts"]),
                "source": r.get("source"),
                "level": r.get("level"),
                "message": r.get("message"),
                "logger_name": r.get("logger_name"),
                "module": r.get("module"),
                "line_no": r.get("line_no"),
                "fingerprint": r.get("fingerprint"),
                "occurrences": int(r.get("occurrences") or 1),
                "attributes": r.get("attributes") or {},
            }
            for r in rows
        ]
        return self._batched("logs", payload)

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
    ) -> pd.DataFrame:
        builder = self._select("logs")
        if device_id:
            builder = self._device_filter(builder, device_id)
        if since is not None:
            builder = builder.gte("ts", to_iso(since))
        if until is not None:
            builder = builder.lte("ts", to_iso(until))
        if levels:
            builder = builder.in_("level", list(levels))
        if source:
            builder = builder.eq("source", source)
        if search:
            builder = builder.ilike("message", f"%{search}%")
        builder = builder.order("ts", desc=True).limit(int(limit))
        return self._normalise(frame(self._data(self._run(builder, what="logs"))))

    def log_sources(self, device_id: str | None = None) -> list[str]:
        builder = self._select("logs", "source").not_.is_("source", "null")
        if device_id:
            builder = self._device_filter(builder, device_id)
        rows = self._data(self._run(builder, what="log sources"))
        return sorted({r["source"] for r in rows if r.get("source")})

    # -- anomalies / alerts ------------------------------------------------------ #
    def insert_anomalies(self, rows: Sequence[Mapping[str, Any]]) -> list[str]:
        ids: list[str] = []
        payload = []
        for r in rows:
            anomaly_id = r.get("id") or new_id()
            ids.append(anomaly_id)
            risk = int(max(0, min(100, round(float(r.get("risk_score") or 0)))))
            payload.append(
                {
                    "id": anomaly_id,
                    "device_id": r["device_pk"],
                    "ts": to_iso(r["ts"]),
                    "metric": r.get("metric"),
                    "observed_value": r.get("observed_value"),
                    "expected_value": r.get("expected_value"),
                    "baseline_std": r.get("baseline_std"),
                    "delta": r.get("delta"),
                    "ratio": r.get("ratio"),
                    "model": r.get("model"),
                    "model_scores": r.get("model_scores") or {},
                    "anomaly_score": r.get("anomaly_score"),
                    "risk_score": risk,
                    "severity": r.get("severity") or severity_for_risk(risk),
                    "explanation": r.get("explanation"),
                    "evidence": r.get("evidence") or {},
                    "features": r.get("features") or {},
                    "acknowledged": bool(r.get("acknowledged")),
                }
            )
        self._batched("anomalies", payload)
        return ids

    def fetch_anomalies(
        self,
        *,
        device_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        severities: Sequence[str] | None = None,
        metric: str | None = None,
        limit: int = 500,
    ) -> pd.DataFrame:
        builder = self._select("anomalies")
        if device_id:
            builder = self._device_filter(builder, device_id)
        if since is not None:
            builder = builder.gte("ts", to_iso(since))
        if until is not None:
            builder = builder.lte("ts", to_iso(until))
        if severities:
            builder = builder.in_("severity", list(severities))
        if metric:
            builder = builder.eq("metric", metric)
        builder = builder.order("ts", desc=True).limit(int(limit))
        return self._normalise(frame(self._data(self._run(builder, what="anomalies"))))

    def get_anomaly(self, anomaly_id: str) -> dict[str, Any] | None:
        rows = self._data(
            self._run(self._select("anomalies").eq("id", anomaly_id).limit(1), what="anomaly")
        )
        if not rows:
            return None
        record = rows[0]
        for col in ("model_scores", "evidence", "features"):
            record[col] = load_json(record.get(col))
        return record

    def acknowledge_anomaly(self, anomaly_id: str) -> bool:
        return bool(self._data(self._update("anomalies", {"acknowledged": True}, id=anomaly_id)))

    def insert_alerts(self, rows: Sequence[Mapping[str, Any]]) -> int:
        now = to_iso(utcnow())
        payload = []
        for r in rows:
            risk = int(max(0, min(100, round(float(r.get("risk_score") or 0)))))
            payload.append(
                {
                    "id": r.get("id") or new_id(),
                    "device_id": r["device_pk"],
                    "anomaly_id": r.get("anomaly_id"),
                    "ts": to_iso(r["ts"]),
                    "title": r.get("title"),
                    "message": r.get("message"),
                    "metric": r.get("metric"),
                    "severity": r.get("severity") or severity_for_risk(risk),
                    "risk_score": risk,
                    "status": r.get("status") or ALERT_STATUS_NEW,
                    "created_at": now,
                    "updated_at": now,
                }
            )
        return self._batched("alerts", payload)

    def fetch_alerts(
        self,
        *,
        device_id: str | None = None,
        statuses: Sequence[str] | None = None,
        severities: Sequence[str] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 500,
    ) -> pd.DataFrame:
        builder = self._select("alerts")
        if device_id:
            builder = self._device_filter(builder, device_id)
        if statuses:
            builder = builder.in_("status", list(statuses))
        if severities:
            builder = builder.in_("severity", list(severities))
        if since is not None:
            builder = builder.gte("ts", to_iso(since))
        if until is not None:
            builder = builder.lte("ts", to_iso(until))
        builder = builder.order("ts", desc=True).limit(int(limit))
        return frame(self._data(self._run(builder, what="alerts")))

    def set_alert_status(self, alert_id: str, status: str) -> bool:
        now = to_iso(utcnow())
        values: dict[str, Any] = {"status": status, "updated_at": now}
        if status == "ACKNOWLEDGED":
            values["acknowledged_at"] = now
        if status == "RESOLVED":
            values["resolved_at"] = now
        return bool(self._data(self._update("alerts", values, id=alert_id)))

    def insert_risk_events(self, rows: Sequence[Mapping[str, Any]]) -> int:
        payload = [
            {
                "device_id": r["device_pk"],
                "ts": to_iso(r["ts"]),
                "window_start": to_iso(r.get("window_start")) if r.get("window_start") else None,
                "window_end": to_iso(r.get("window_end")) if r.get("window_end") else None,
                "risk_score": int(max(0, min(100, round(float(r.get("risk_score") or 0))))),
                "severity": r.get("severity") or severity_for_risk(r.get("risk_score") or 0),
                "composite": r.get("composite") or {},
                "summary": r.get("summary"),
            }
            for r in rows
        ]
        return self._batched("risk_events", payload)

    def fetch_risk_events(
        self, *, device_id: str | None = None, since: datetime | None = None, limit: int = 1000
    ) -> pd.DataFrame:
        builder = self._select("risk_events")
        if device_id:
            builder = self._device_filter(builder, device_id)
        if since is not None:
            builder = builder.gte("ts", to_iso(since))
        builder = builder.order("ts").limit(int(limit))
        return self._normalise(frame(self._data(self._run(builder, what="risk events"))))

    # -- documents / RAG ---------------------------------------------------------- #
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
    ) -> str:
        document_id = new_id()
        now = to_iso(utcnow())
        self._insert(
            "documents",
            [
                {
                    "id": document_id,
                    "filename": filename,
                    "title": title or filename,
                    "content_type": content_type,
                    "size_bytes": int(size_bytes or 0),
                    "checksum": checksum,
                    "source": source,
                    "pages": 0,
                    "chunk_count": 0,
                    "status": "PENDING",
                    "meta": meta or {},
                    "created_at": now,
                    "updated_at": now,
                }
            ],
        )
        return document_id

    def update_document(
        self,
        document_id: str,
        *,
        status: str | None = None,
        error: str | None = None,
        chunk_count: int | None = None,
        pages: int | None = None,
    ) -> bool:
        values: dict[str, Any] = {"updated_at": to_iso(utcnow())}
        for key, value in (
            ("status", status),
            ("error", error),
            ("chunk_count", chunk_count),
            ("pages", pages),
        ):
            if value is not None:
                values[key] = value
        return bool(self._data(self._update("documents", values, id=document_id)))

    def list_documents(self) -> pd.DataFrame:
        rows = self._data(
            self._run(self._select("documents").order("created_at", desc=True), what="documents")
        )
        df = self._normalise(frame(rows), ("meta",))
        if not df.empty and "created_at" in df.columns:
            df["created_at"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce")
        return df

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        rows = self._data(
            self._run(self._select("documents").eq("id", document_id).limit(1), what="document")
        )
        if not rows:
            return None
        record = rows[0]
        record["meta"] = load_json(record.get("meta"))
        return record

    def delete_document(self, document_id: str) -> bool:
        return bool(self._data(self._delete("documents", id=document_id)))

    def insert_chunks(
        self, rows: Sequence[Mapping[str, Any]], *, include_embeddings: bool = True
    ) -> int:
        now = to_iso(utcnow())
        payload = []
        for row in rows:
            r = chunk_row(row)
            record: dict[str, Any] = {
                "document_id": r["document_id"],
                "chunk_index": r["chunk_index"],
                "content": r["content"],
                "token_estimate": r["token_estimate"],
                "char_start": r["char_start"],
                "char_end": r["char_end"],
                "page": r["page"],
                "heading": r["heading"],
                "meta": r["meta"] or {},
                "created_at": now,
            }
            if include_embeddings and r["embedding"] is not None:
                record["embedding"] = r["embedding"]
            payload.append(record)
        return self._batched("document_chunks", payload)

    def fetch_chunks(self, *, document_id: str | None = None, limit: int = 100000) -> pd.DataFrame:
        builder = self._select("document_chunks")
        if document_id:
            builder = builder.eq("document_id", document_id)
        builder = builder.order("chunk_index").limit(int(limit))
        return self._normalise(frame(self._data(self._run(builder, what="chunks"))))

    def delete_chunks(self, document_id: str) -> int:
        return len(self._data(self._delete("document_chunks", document_id=document_id)))

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
    ) -> int:
        self._insert(
            "rag_queries",
            [
                {
                    "document_id": document_id,
                    "query": query,
                    "top_k": int(top_k),
                    "provider": provider,
                    "hit_count": int(hit_count),
                    "top_score": float(top_score),
                    "latency_ms": int(latency_ms),
                    "answer": answer,
                    "sources": list(sources) if sources else [],
                    "created_at": to_iso(utcnow()),
                }
            ],
        )
        return 1

    def fetch_rag_queries(self, limit: int = 100) -> pd.DataFrame:
        rows = self._data(
            self._run(self._select("rag_queries").order("created_at", desc=True).limit(int(limit)),
                      what="rag queries")
        )
        return self._normalise(frame(rows))

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
    ) -> int:
        self._insert(
            "ai_investigations",
            [
                {
                    "device_id": device_id,
                    "anomaly_id": anomaly_id,
                    "question": question,
                    "answer": answer,
                    "provider": provider,
                    "model": model,
                    "evidence": evidence or {},
                    "confidence": float(confidence) if confidence is not None else None,
                    "citations": list(citations) if citations else [],
                    "created_at": to_iso(utcnow()),
                }
            ],
        )
        return 1

    def fetch_investigations(self, limit: int = 100) -> pd.DataFrame:
        rows = self._data(
            self._run(
                self._select("ai_investigations").order("created_at", desc=True).limit(int(limit)),
                what="investigations",
            )
        )
        df = self._normalise(frame(rows))
        if not df.empty and "created_at" in df.columns:
            df["created_at"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce")
        return df

    # -- system events ------------------------------------------------------------- #
    def insert_system_events(self, rows: Sequence[Mapping[str, Any]]) -> int:
        payload = [
            {
                "ts": to_iso(r.get("ts") or utcnow()),
                "level": r.get("level") or "INFO",
                "source": r.get("source") or "sentinel",
                "message": r.get("message") or "",
                "context": r.get("context") or {},
            }
            for r in rows
        ]
        return self._batched("system_events", payload)

    def fetch_system_events(self, limit: int = 200) -> pd.DataFrame:
        rows = self._data(
            self._run(
                self._select("system_events").order("ts", desc=True).limit(int(limit)),
                what="system events",
            )
        )
        return frame(rows)

    # -- aggregates ----------------------------------------------------------------- #
    def table_counts(self) -> dict[str, int]:
        tables = (
            "devices",
            "system_metrics",
            "network_metrics",
            "process_snapshots",
            "logs",
            "anomalies",
            "alerts",
            "risk_events",
            "documents",
            "document_chunks",
            "rag_queries",
            "ai_investigations",
            "system_events",
        )
        counts: dict[str, int] = {}
        for table in tables:
            try:
                builder = self.client.table(table).select("id", count="exact").limit(1)
                response = self._run(builder, what=f"count {table}")
                counts[table] = int(getattr(response, "count", 0) or 0)
            except DatabaseError:
                counts[table] = 0
        return counts


__all__ = ["SupabaseRepository"]
