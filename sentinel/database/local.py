"""On-disk SQLite implementation of :class:`SentinelRepository`.

This backend is a first-class citizen, not a stub. It is used when Supabase is
not configured so that the platform is fully functional for local development,
air-gapped evaluation and automated tests. It implements the same schema,
foreign keys, indexes and semantics as the Supabase/Postgres backend, so the
application behaves identically on either.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from ..constants import ALERT_STATUS_NEW
from ..exceptions import DatabaseError, DeviceNotAuthorizedError
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

log = get_logger("database.local")

SCHEMA_VERSION = 1

_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id           TEXT PRIMARY KEY,
    email        TEXT UNIQUE NOT NULL,
    display_name TEXT,
    role         TEXT NOT NULL DEFAULT 'analyst',
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pairing_codes (
    code       TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at    TEXT,
    used_by    TEXT
);

CREATE TABLE IF NOT EXISTS devices (
    id              TEXT PRIMARY KEY,
    device_id       TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    os_name         TEXT,
    os_version      TEXT,
    hostname        TEXT,
    arch            TEXT,
    agent_version   TEXT,
    status          TEXT NOT NULL DEFAULT 'PENDING',
    pairing_code    TEXT,
    authorized_at   TEXT,
    last_seen       TEXT,
    cpu_percent     REAL,
    memory_percent  REAL,
    disk_percent    REAL,
    risk_score      INTEGER DEFAULT 0,
    agent_ip        TEXT,
    meta            TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agents (
    id                   TEXT PRIMARY KEY,
    device_pk            TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    agent_version        TEXT,
    python_version       TEXT,
    platform             TEXT,
    interval_s           INTEGER DEFAULT 10,
    last_heartbeat       TEXT,
    consecutive_failures INTEGER DEFAULT 0,
    last_error           TEXT,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    UNIQUE (device_pk)
);

CREATE TABLE IF NOT EXISTS system_metrics (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id           TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    ts                  TEXT NOT NULL,
    cpu_percent         REAL,
    memory_percent      REAL,
    disk_percent        REAL,
    swap_percent        REAL,
    load_average        REAL,
    process_count       INTEGER,
    thread_count        INTEGER,
    handle_count        INTEGER,
    disk_free_gb        REAL,
    disk_read_mbps      REAL,
    disk_write_mbps     REAL,
    context_switch_rate REAL,
    uptime_seconds      INTEGER,
    temperature_c       REAL,
    raw                 TEXT
);
CREATE INDEX IF NOT EXISTS idx_sysmetrics_device_ts ON system_metrics (device_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_sysmetrics_ts ON system_metrics (ts DESC);

CREATE TABLE IF NOT EXISTS network_metrics (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id    TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    ts           TEXT NOT NULL,
    iface        TEXT,
    bytes_sent   INTEGER,
    bytes_recv   INTEGER,
    packets_sent INTEGER,
    packets_recv INTEGER,
    errin        INTEGER,
    errout       INTEGER,
    dropin       INTEGER,
    dropout      INTEGER,
    sent_mbps    REAL,
    recv_mbps    REAL,
    connections  INTEGER,
    raw          TEXT
);
CREATE INDEX IF NOT EXISTS idx_netmetrics_device_ts ON network_metrics (device_id, ts DESC);

CREATE TABLE IF NOT EXISTS process_snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id     TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    ts            TEXT NOT NULL,
    pid           INTEGER,
    ppid          INTEGER,
    name          TEXT,
    owner         TEXT,
    status        TEXT,
    cpu_percent   REAL,
    memory_percent REAL,
    rss_mb        REAL,
    num_threads   INTEGER,
    create_time   TEXT
);
CREATE INDEX IF NOT EXISTS idx_procs_device_ts ON process_snapshots (device_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_procs_name ON process_snapshots (name);

CREATE TABLE IF NOT EXISTS logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id   TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    ts          TEXT NOT NULL,
    source      TEXT,
    level       TEXT,
    message     TEXT,
    logger_name TEXT,
    module      TEXT,
    line_no     INTEGER,
    fingerprint TEXT,
    occurrences INTEGER DEFAULT 1,
    attributes  TEXT
);
CREATE INDEX IF NOT EXISTS idx_logs_device_ts ON logs (device_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_logs_level ON logs (level);
CREATE INDEX IF NOT EXISTS idx_logs_fingerprint ON logs (fingerprint);

CREATE TABLE IF NOT EXISTS anomalies (
    id              TEXT PRIMARY KEY,
    device_id       TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    ts              TEXT NOT NULL,
    metric          TEXT,
    observed_value  REAL,
    expected_value  REAL,
    baseline_std    REAL,
    delta           REAL,
    ratio           REAL,
    model           TEXT,
    model_scores    TEXT,
    anomaly_score   REAL,
    risk_score      INTEGER,
    severity        TEXT,
    explanation     TEXT,
    evidence        TEXT,
    features        TEXT,
    acknowledged    INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_anom_device_ts ON anomalies (device_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_anom_severity ON anomalies (severity);
CREATE INDEX IF NOT EXISTS idx_anom_metric ON anomalies (metric);

CREATE TABLE IF NOT EXISTS alerts (
    id              TEXT PRIMARY KEY,
    device_id       TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    anomaly_id      TEXT,
    ts              TEXT NOT NULL,
    title           TEXT,
    message         TEXT,
    metric          TEXT,
    severity        TEXT,
    risk_score      INTEGER,
    status          TEXT NOT NULL DEFAULT 'NEW',
    acknowledged_at TEXT,
    resolved_at     TEXT,
    resolved_by     TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    FOREIGN KEY (anomaly_id) REFERENCES anomalies(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_alerts_device_ts ON alerts (device_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts (status);

CREATE TABLE IF NOT EXISTS risk_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id    TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    ts           TEXT NOT NULL,
    window_start TEXT,
    window_end   TEXT,
    risk_score   INTEGER,
    severity     TEXT,
    composite    TEXT,
    summary      TEXT
);
CREATE INDEX IF NOT EXISTS idx_risk_device_ts ON risk_events (device_id, ts DESC);

CREATE TABLE IF NOT EXISTS documents (
    id           TEXT PRIMARY KEY,
    filename     TEXT NOT NULL,
    title        TEXT,
    content_type TEXT,
    size_bytes   INTEGER,
    checksum     TEXT,
    source       TEXT DEFAULT 'UPLOAD',
    pages        INTEGER DEFAULT 0,
    chunk_count  INTEGER DEFAULT 0,
    status       TEXT DEFAULT 'PENDING',
    error        TEXT,
    meta         TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id    TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index    INTEGER NOT NULL,
    content        TEXT NOT NULL,
    token_estimate INTEGER,
    char_start     INTEGER,
    char_end       INTEGER,
    page           INTEGER,
    heading        TEXT,
    embedding      TEXT,
    meta           TEXT,
    created_at     TEXT NOT NULL,
    UNIQUE (document_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON document_chunks (document_id, chunk_index);

CREATE TABLE IF NOT EXISTS rag_queries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT,
    query      TEXT NOT NULL,
    top_k      INTEGER,
    provider   TEXT,
    hit_count  INTEGER,
    top_score  REAL,
    latency_ms INTEGER,
    answer     TEXT,
    sources    TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_ragq_created ON rag_queries (created_at DESC);

CREATE TABLE IF NOT EXISTS ai_investigations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id   TEXT,
    anomaly_id  TEXT,
    question    TEXT,
    answer      TEXT,
    provider    TEXT,
    model       TEXT,
    evidence    TEXT,
    confidence  REAL,
    citations   TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_investigations_created ON ai_investigations (created_at DESC);

CREATE TABLE IF NOT EXISTS system_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    level      TEXT,
    source     TEXT,
    message    TEXT,
    context    TEXT
);
CREATE INDEX IF NOT EXISTS idx_sysevts_created ON system_events (ts DESC);
"""


def _ph(values: Sequence[Any]) -> str:
    """Render a parameter list for an ``IN (...)`` clause."""
    return "(" + ",".join("?" for _ in values) + ")"


class LocalRepository(SentinelRepository):
    """SQLite-backed repository (WAL mode, one connection per thread)."""

    backend_name = "local-sqlite"

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        # Reentrant: register_device() holds the lock while calling _execute().
        self._write_lock = threading.RLock()
        self._initialised = False

    # -- plumbing ---------------------------------------------------------- #
    @property
    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(
                self.db_path, timeout=30.0, isolation_level=None, check_same_thread=False
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=30000")
            self._local.conn = conn
        return conn

    def _query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        try:
            cur = self._conn.execute(sql, tuple(params))
            return [dict(r) for r in cur.fetchall()]
        except sqlite3.Error as exc:
            raise DatabaseError(f"SQLite query failed: {exc}") from exc

    def _execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        try:
            with self._write_lock:
                cur = self._conn.execute(sql, tuple(params))
            return cur.rowcount
        except sqlite3.Error as exc:
            raise DatabaseError(f"SQLite write failed: {exc}") from exc

    def _executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> int:
        if not rows:
            return 0
        try:
            with self._write_lock:
                cur = self._conn.executemany(sql, [tuple(r) for r in rows])
            return cur.rowcount
        except sqlite3.Error as exc:
            raise DatabaseError(f"SQLite batch write failed: {exc}") from exc

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass
            self._local.conn = None

    def initialise(self) -> None:
        if self._initialised:
            return
        try:
            self._conn.executescript(_SCHEMA)
            self._conn.execute(
                "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self._initialised = True
            log.info("Local store ready at %s", self.db_path)
        except sqlite3.Error as exc:
            raise DatabaseError(f"Could not initialise local store: {exc}") from exc

    def health(self) -> BackendHealth:
        started = time.perf_counter()
        try:
            self.initialise()
            row = self._query("SELECT value FROM schema_meta WHERE key='version'")
            latency = (time.perf_counter() - started) * 1000
            return BackendHealth(
                name=self.backend_name,
                connected=True,
                latency_ms=latency,
                detail=f"schema v{row[0]['value'] if row else '?'} at {self.db_path.name}",
                mode="primary",
            )
        except Exception as exc:  # pragma: no cover - defensive
            return BackendHealth(
                name=self.backend_name,
                connected=False,
                latency_ms=(time.perf_counter() - started) * 1000,
                detail="local store unavailable",
                error=str(exc),
            )

    # -- devices ------------------------------------------------------------ #
    def create_pairing_code(self, ttl_minutes: int = 30) -> tuple[str, datetime]:
        import secrets

        code = f"{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}"
        now = utcnow()
        expires = now + timedelta(minutes=max(1, ttl_minutes))
        self._execute(
            "INSERT INTO pairing_codes (code, created_at, expires_at) VALUES (?,?,?)",
            (code, to_iso(now), to_iso(expires)),
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
        self.initialise()
        now = utcnow()
        with self._write_lock:
            existing = self._query("SELECT * FROM devices WHERE device_id=?", (device_id,))
            if existing:
                status = existing[0]["status"]
                if status == "REVOKED":
                    raise DeviceNotAuthorizedError(
                        f"Device {device_id} was revoked and cannot re-register."
                    )
                self._execute(
                    """UPDATE devices SET name=?, os_name=?, os_version=?, hostname=?, arch=?,
                       agent_version=?, last_seen=?, updated_at=?, meta=? WHERE device_id=?""",
                    (
                        name,
                        os_name,
                        os_version,
                        hostname,
                        arch,
                        agent_version,
                        to_iso(now),
                        to_iso(now),
                        dump_json(metadata or {}),
                        device_id,
                    ),
                )
                self._execute(
                    """UPDATE agents SET agent_version=?, python_version=?, platform=?,
                       interval_s=?, last_heartbeat=?, consecutive_failures=0, last_error=NULL,
                       updated_at=? WHERE device_pk=(SELECT id FROM devices WHERE device_id=?)""",
                    (
                        agent_version,
                        python_version,
                        f"{os_name} {os_version}".strip(),
                        interval_s,
                        to_iso(now),
                        to_iso(now),
                        device_id,
                    ),
                )
                return self.get_device(device_id) or {}

            authorized = False
            used_code: str | None = None
            if pairing_code:
                rows = self._query(
                    "SELECT * FROM pairing_codes WHERE code=? AND used_at IS NULL", (pairing_code,)
                )
                if rows:
                    row = rows[0]
                    from .repository import parse_dt

                    if parse_dt(row["expires_at"]) and parse_dt(row["expires_at"]) > now:
                        authorized = True
                        used_code = pairing_code
                        self._execute(
                            "UPDATE pairing_codes SET used_at=?, used_by=? WHERE code=?",
                            (to_iso(now), device_id, pairing_code),
                        )
            status = "AUTHORIZED" if authorized else "PENDING"
            pk = new_id()
            self._execute(
                """INSERT INTO devices (id, device_id, name, os_name, os_version, hostname, arch,
                   agent_version, status, pairing_code, authorized_at, last_seen, meta,
                   created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    pk,
                    device_id,
                    name,
                    os_name,
                    os_version,
                    hostname,
                    arch,
                    agent_version,
                    status,
                    pairing_code,
                    to_iso(now) if authorized else None,
                    to_iso(now),
                    dump_json(metadata or {}),
                    to_iso(now),
                    to_iso(now),
                ),
            )
            self._execute(
                """INSERT INTO agents (id, device_pk, agent_version, python_version, platform,
                   interval_s, last_heartbeat, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    new_id(),
                    pk,
                    agent_version,
                    python_version,
                    f"{os_name} {os_version}".strip(),
                    interval_s,
                    to_iso(now),
                    to_iso(now),
                    to_iso(now),
                ),
            )
        return self.get_device(device_id) or {}

    def list_devices(self) -> pd.DataFrame:
        rows = self._query("SELECT * FROM devices ORDER BY last_seen DESC NULLS LAST, name")
        df = frame(rows)
        if df.empty:
            return df
        if "meta" in df.columns:
            df["meta"] = df["meta"].map(load_json)
        return df

    def get_device(self, device_id: str) -> dict[str, Any] | None:
        rows = self._query(
            """SELECT d.*, a.agent_version AS agent_version_detail, a.python_version,
                      a.platform, a.interval_s, a.consecutive_failures, a.last_error,
                      a.last_heartbeat
               FROM devices d LEFT JOIN agents a ON a.device_pk = d.id
               WHERE d.device_id=?""",
            (device_id,),
        )
        if not rows:
            return None
        record = rows[0]
        record["meta"] = load_json(record.get("meta"))
        return record

    def set_device_status(self, device_id: str, status: str) -> bool:
        now = to_iso(utcnow())
        return (
            self._execute(
                "UPDATE devices SET status=?, authorized_at=COALESCE(authorized_at, ?), updated_at=? WHERE device_id=?",
                (status, now, now, device_id),
            )
            > 0
        )

    def delete_device(self, device_id: str) -> bool:
        return self._execute("DELETE FROM devices WHERE device_id=?", (device_id,)) > 0

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
        assignments = ["last_seen=?", "updated_at=?"]
        params: list[Any] = [now, now]
        for column, value in (
            ("risk_score", risk_score),
            ("cpu_percent", cpu_percent),
            ("memory_percent", memory_percent),
            ("disk_percent", disk_percent),
            ("agent_version", agent_version),
            ("agent_ip", source_ip),
        ):
            if value is not None:
                assignments.append(f"{column}=?")
                params.append(value)
        params.append(device_id)
        return self._execute(f"UPDATE devices SET {', '.join(assignments)} WHERE device_id=?", params) > 0

    def resolve_device_pk(self, device_id: str) -> str | None:
        rows = self._query("SELECT id FROM devices WHERE device_id=?", (device_id,))
        return rows[0]["id"] if rows else None

    # -- telemetry ---------------------------------------------------------- #
    def insert_system_metrics(self, rows: Sequence[Mapping[str, Any]]) -> int:
        if not rows:
            return 0
        payload = [
            (
                r["device_pk"],
                to_iso(r["ts"]),
                r.get("cpu_percent"),
                r.get("memory_percent"),
                r.get("disk_percent"),
                r.get("swap_percent"),
                r.get("load_average"),
                r.get("process_count"),
                r.get("thread_count"),
                r.get("handle_count"),
                r.get("disk_free_gb"),
                r.get("disk_read_mbps"),
                r.get("disk_write_mbps"),
                r.get("context_switch_rate"),
                r.get("uptime_seconds"),
                r.get("temperature_c"),
                dump_json(r.get("raw")) if r.get("raw") is not None else None,
            )
            for r in rows
        ]
        return self._executemany(
            """INSERT INTO system_metrics (device_id, ts, cpu_percent, memory_percent,
               disk_percent, swap_percent, load_average, process_count, thread_count,
               handle_count, disk_free_gb, disk_read_mbps, disk_write_mbps,
               context_switch_rate, uptime_seconds, temperature_c, raw)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            payload,
        )

    def insert_network_metrics(self, rows: Sequence[Mapping[str, Any]]) -> int:
        if not rows:
            return 0
        payload = [
            (
                r["device_pk"],
                to_iso(r["ts"]),
                r.get("iface"),
                r.get("bytes_sent"),
                r.get("bytes_recv"),
                r.get("packets_sent"),
                r.get("packets_recv"),
                r.get("errin"),
                r.get("errout"),
                r.get("dropin"),
                r.get("dropout"),
                r.get("sent_mbps"),
                r.get("recv_mbps"),
                r.get("connections"),
                dump_json(r.get("raw")) if r.get("raw") is not None else None,
            )
            for r in rows
        ]
        return self._executemany(
            """INSERT INTO network_metrics (device_id, ts, iface, bytes_sent, bytes_recv,
               packets_sent, packets_recv, errin, errout, dropin, dropout, sent_mbps,
               recv_mbps, connections, raw) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            payload,
        )

    def insert_process_snapshots(self, rows: Sequence[Mapping[str, Any]]) -> int:
        if not rows:
            return 0
        payload = [
            (
                r["device_pk"],
                to_iso(r["ts"]),
                r.get("pid"),
                r.get("ppid"),
                r.get("name"),
                r.get("owner"),
                r.get("status"),
                r.get("cpu_percent"),
                r.get("memory_percent"),
                r.get("rss_mb"),
                r.get("num_threads"),
                to_iso(r["create_time"]) if r.get("create_time") else None,
            )
            for r in rows
        ]
        return self._executemany(
            """INSERT INTO process_snapshots (device_id, ts, pid, ppid, name, owner, status,
               cpu_percent, memory_percent, rss_mb, num_threads, create_time)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            payload,
        )

    def _device_pks(self, device_id: str | None) -> list[str] | None:
        if not device_id:
            return None
        rows = self._query("SELECT id FROM devices WHERE device_id=?", (device_id,))
        return [r["id"] for r in rows] or ["__none__"]

    def _time_filters(
        self, since: datetime | None, until: datetime | None
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if since is not None:
            clauses.append("ts >= ?")
            params.append(to_iso(since))
        if until is not None:
            clauses.append("ts <= ?")
            params.append(to_iso(until))
        return (" AND ".join(clauses), params)

    def fetch_system_metrics(
        self,
        *,
        device_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 2000,
        newest_first: bool = False,
    ) -> pd.DataFrame:
        pks = self._device_pks(device_id)
        where = ["1=1"]
        params: list[Any] = []
        if pks is not None:
            where.append(f"device_id IN {_ph(pks)}")
            params.extend(pks)
        clause, extra = self._time_filters(since, until)
        where.append(clause.strip() or "1=1")
        params.extend(extra)
        order = "DESC" if newest_first else "ASC"
        rows = self._query(
            f"SELECT * FROM system_metrics WHERE {' AND '.join(w for w in where if w)} "
            f"ORDER BY ts {order} LIMIT ?",
            [*params, max(1, int(limit))],
        )
        df = frame(rows)
        if not df.empty and "raw" in df.columns:
            df["raw"] = df["raw"].map(load_json)
        return df

    def fetch_network_metrics(
        self,
        *,
        device_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 2000,
    ) -> pd.DataFrame:
        pks = self._device_pks(device_id)
        where = ["1=1"]
        params: list[Any] = []
        if pks is not None:
            where.append(f"device_id IN {_ph(pks)}")
            params.extend(pks)
        clause, extra = self._time_filters(since, until)
        where.append(clause.strip() or "1=1")
        params.extend(extra)
        rows = self._query(
            f"SELECT * FROM network_metrics WHERE {' AND '.join(where)} ORDER BY ts ASC LIMIT ?",
            [*params, max(1, int(limit))],
        )
        df = frame(rows)
        if not df.empty and "raw" in df.columns:
            df["raw"] = df["raw"].map(load_json)
        return df

    def fetch_process_snapshots(
        self, *, device_id: str | None = None, ts: datetime | None = None, limit: int = 500
    ) -> pd.DataFrame:
        pks = self._device_pks(device_id)
        where = ["1=1"]
        params: list[Any] = []
        if pks is not None:
            where.append(f"device_id IN {_ph(pks)}")
            params.extend(pks)
        if ts is not None:
            where.append("ts = ?")
            params.append(to_iso(ts))
        rows = self._query(
            f"SELECT * FROM process_snapshots WHERE {' AND '.join(where)} ORDER BY cpu_percent DESC LIMIT ?",
            [*params, max(1, int(limit))],
        )
        return frame(rows)

    def latest_system_metrics(self, device_id: str | None = None) -> dict[str, Any] | None:
        df = self.fetch_system_metrics(device_id=device_id, limit=1, newest_first=True)
        if df.empty:
            return None
        row = df.iloc[0].to_dict()
        row.pop("raw", None)
        return row

    def latest_network_metrics(self, device_id: str | None = None) -> dict[str, Any] | None:
        pks = self._device_pks(device_id)
        where = "1=1"
        params: list[Any] = []
        if pks is not None:
            where = f"device_id IN {_ph(pks)}"
            params.extend(pks)
        rows = self._query(
            f"SELECT * FROM network_metrics WHERE {where} ORDER BY ts DESC LIMIT 1", params
        )
        if not rows:
            return None
        row = rows[0]
        row.pop("raw", None)
        return row

    def delete_old_telemetry(self, *, before: datetime) -> int:
        stamp = to_iso(before)
        total = 0
        for table in (
            "system_metrics",
            "network_metrics",
            "process_snapshots",
            "logs",
            "risk_events",
        ):
            total += max(0, self._execute(f"DELETE FROM {table} WHERE ts < ?", (stamp,)))
        return total

    # -- logs ---------------------------------------------------------------- #
    def insert_logs(self, rows: Sequence[Mapping[str, Any]]) -> int:
        if not rows:
            return 0
        payload = [
            (
                r["device_pk"],
                to_iso(r["ts"]),
                r.get("source"),
                r.get("level"),
                r.get("message"),
                r.get("logger_name"),
                r.get("module"),
                r.get("line_no"),
                r.get("fingerprint"),
                int(r.get("occurrences") or 1),
                dump_json(r.get("attributes")) if r.get("attributes") is not None else None,
            )
            for r in rows
        ]
        return self._executemany(
            """INSERT INTO logs (device_id, ts, source, level, message, logger_name, module,
               line_no, fingerprint, occurrences, attributes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            payload,
        )

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
        pks = self._device_pks(device_id)
        where = ["1=1"]
        params: list[Any] = []
        if pks is not None:
            where.append(f"device_id IN {_ph(pks)}")
            params.extend(pks)
        clause, extra = self._time_filters(since, until)
        where.append(clause.strip() or "1=1")
        params.extend(extra)
        if levels:
            where.append(f"level IN {_ph(list(levels))}")
            params.extend(list(levels))
        if source:
            where.append("source = ?")
            params.append(source)
        if search:
            where.append("message LIKE ?")
            params.append(f"%{search}%")
        rows = self._query(
            f"SELECT * FROM logs WHERE {' AND '.join(where)} ORDER BY ts DESC LIMIT ?",
            [*params, max(1, int(limit))],
        )
        df = frame(rows)
        if df.empty:
            # ``frame([])`` has no columns at all, so sorting would raise.
            return df
        if "attributes" in df.columns:
            df["attributes"] = df["attributes"].map(load_json)
        return df.sort_values("ts", ascending=False).reset_index(drop=True)

    def log_sources(self, device_id: str | None = None) -> list[str]:
        pks = self._device_pks(device_id)
        where = "1=1"
        params: list[Any] = []
        if pks is not None:
            where = f"device_id IN {_ph(pks)}"
            params.extend(pks)
        rows = self._query(
            f"SELECT DISTINCT source FROM logs WHERE {where} AND source IS NOT NULL ORDER BY source",
            params,
        )
        return [r["source"] for r in rows]

    # -- anomalies / alerts --------------------------------------------------- #
    def insert_anomalies(self, rows: Sequence[Mapping[str, Any]]) -> list[str]:
        if not rows:
            return []
        ids: list[str] = []
        payload = []
        for r in rows:
            anomaly_id = r.get("id") or new_id()
            ids.append(anomaly_id)
            risk = int(max(0, min(100, round(float(r.get("risk_score") or 0)))))
            payload.append(
                (
                    anomaly_id,
                    r["device_pk"],
                    to_iso(r["ts"]),
                    r.get("metric"),
                    r.get("observed_value"),
                    r.get("expected_value"),
                    r.get("baseline_std"),
                    r.get("delta"),
                    r.get("ratio"),
                    r.get("model"),
                    dump_json(r.get("model_scores")) if r.get("model_scores") else None,
                    r.get("anomaly_score"),
                    risk,
                    r.get("severity") or severity_for_risk(risk),
                    r.get("explanation"),
                    dump_json(r.get("evidence")) if r.get("evidence") is not None else None,
                    dump_json(r.get("features")) if r.get("features") is not None else None,
                    1 if r.get("acknowledged") else 0,
                )
            )
        self._executemany(
            """INSERT INTO anomalies (id, device_id, ts, metric, observed_value, expected_value,
               baseline_std, delta, ratio, model, model_scores, anomaly_score, risk_score,
               severity, explanation, evidence, features, acknowledged)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            payload,
        )
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
        pks = self._device_pks(device_id)
        where = ["1=1"]
        params: list[Any] = []
        if pks is not None:
            where.append(f"device_id IN {_ph(pks)}")
            params.extend(pks)
        clause, extra = self._time_filters(since, until)
        where.append(clause.strip() or "1=1")
        params.extend(extra)
        if severities:
            where.append(f"severity IN {_ph(list(severities))}")
            params.extend(list(severities))
        if metric:
            where.append("metric = ?")
            params.append(metric)
        rows = self._query(
            f"SELECT * FROM anomalies WHERE {' AND '.join(where)} ORDER BY ts DESC LIMIT ?",
            [*params, max(1, int(limit))],
        )
        df = frame(rows)
        for col in ("model_scores", "evidence", "features"):
            if col in df.columns:
                df[col] = df[col].map(load_json)
        return df

    def get_anomaly(self, anomaly_id: str) -> dict[str, Any] | None:
        rows = self._query("SELECT * FROM anomalies WHERE id=?", (anomaly_id,))
        if not rows:
            return None
        record = rows[0]
        for col in ("model_scores", "evidence", "features"):
            record[col] = load_json(record.get(col))
        return record

    def acknowledge_anomaly(self, anomaly_id: str) -> bool:
        return self._execute("UPDATE anomalies SET acknowledged=1 WHERE id=?", (anomaly_id,)) > 0

    def insert_alerts(self, rows: Sequence[Mapping[str, Any]]) -> int:
        if not rows:
            return 0
        now = to_iso(utcnow())
        payload = []
        for r in rows:
            risk = int(max(0, min(100, round(float(r.get("risk_score") or 0)))))
            payload.append(
                (
                    r.get("id") or new_id(),
                    r["device_pk"],
                    r.get("anomaly_id"),
                    to_iso(r["ts"]),
                    r.get("title"),
                    r.get("message"),
                    r.get("metric"),
                    r.get("severity") or severity_for_risk(risk),
                    risk,
                    r.get("status") or ALERT_STATUS_NEW,
                    now,
                    now,
                )
            )
        return self._executemany(
            """INSERT INTO alerts (id, device_id, anomaly_id, ts, title, message, metric,
               severity, risk_score, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            payload,
        )

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
        pks = self._device_pks(device_id)
        where = ["1=1"]
        params: list[Any] = []
        if pks is not None:
            where.append(f"device_id IN {_ph(pks)}")
            params.extend(pks)
        clause, extra = self._time_filters(since, until)
        where.append(clause.strip() or "1=1")
        params.extend(extra)
        if statuses:
            where.append(f"status IN {_ph(list(statuses))}")
            params.extend(list(statuses))
        if severities:
            where.append(f"severity IN {_ph(list(severities))}")
            params.extend(list(severities))
        rows = self._query(
            f"SELECT * FROM alerts WHERE {' AND '.join(where)} ORDER BY ts DESC LIMIT ?",
            [*params, max(1, int(limit))],
        )
        return frame(rows)

    def set_alert_status(self, alert_id: str, status: str) -> bool:
        now = to_iso(utcnow())
        acknowledged = to_iso(now) if status == "ACKNOWLEDGED" else None
        resolved = to_iso(now) if status == "RESOLVED" else None
        return (
            self._execute(
                """UPDATE alerts SET status=?, acknowledged_at=COALESCE(?, acknowledged_at),
                   resolved_at=COALESCE(?, resolved_at), updated_at=? WHERE id=?""",
                (status, acknowledged, resolved, now, alert_id),
            )
            > 0
        )

    def insert_risk_events(self, rows: Sequence[Mapping[str, Any]]) -> int:
        if not rows:
            return 0
        payload = [
            (
                r["device_pk"],
                to_iso(r["ts"]),
                to_iso(r.get("window_start")) if r.get("window_start") else None,
                to_iso(r.get("window_end")) if r.get("window_end") else None,
                int(max(0, min(100, round(float(r.get("risk_score") or 0))))),
                r.get("severity") or severity_for_risk(r.get("risk_score") or 0),
                dump_json(r.get("composite")) if r.get("composite") is not None else None,
                r.get("summary"),
            )
            for r in rows
        ]
        return self._executemany(
            """INSERT INTO risk_events (device_id, ts, window_start, window_end, risk_score,
               severity, composite, summary) VALUES (?,?,?,?,?,?,?,?)""",
            payload,
        )

    def fetch_risk_events(
        self, *, device_id: str | None = None, since: datetime | None = None, limit: int = 1000
    ) -> pd.DataFrame:
        pks = self._device_pks(device_id)
        where = ["1=1"]
        params: list[Any] = []
        if pks is not None:
            where.append(f"device_id IN {_ph(pks)}")
            params.extend(pks)
        if since is not None:
            where.append("ts >= ?")
            params.append(to_iso(since))
        rows = self._query(
            f"SELECT * FROM risk_events WHERE {' AND '.join(where)} ORDER BY ts ASC LIMIT ?",
            [*params, max(1, int(limit))],
        )
        df = frame(rows)
        if not df.empty and "composite" in df.columns:
            df["composite"] = df["composite"].map(load_json)
        return df

    # -- documents / RAG ------------------------------------------------------ #
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
        self._execute(
            """INSERT INTO documents (id, filename, title, content_type, size_bytes, checksum,
               source, pages, chunk_count, status, meta, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,0,0,'PENDING',?,?,?)""",
            (
                document_id,
                filename,
                title or filename,
                content_type,
                int(size_bytes or 0),
                checksum,
                source,
                dump_json(meta or {}),
                now,
                now,
            ),
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
        assignments = ["updated_at=?"]
        params: list[Any] = [to_iso(utcnow())]
        for column, value in (
            ("status", status),
            ("error", error),
            ("chunk_count", chunk_count),
            ("pages", pages),
        ):
            if value is not None:
                assignments.append(f"{column}=?")
                params.append(value)
        params.append(document_id)
        return self._execute(f"UPDATE documents SET {', '.join(assignments)} WHERE id=?", params) > 0

    def list_documents(self) -> pd.DataFrame:
        rows = self._query("SELECT * FROM documents ORDER BY created_at DESC")
        df = frame(rows)
        if df.empty:
            return df
        df["meta"] = df["meta"].map(load_json)
        if "created_at" in df.columns:
            df["created_at"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce")
        return df

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        rows = self._query("SELECT * FROM documents WHERE id=?", (document_id,))
        if not rows:
            return None
        record = rows[0]
        record["meta"] = load_json(record.get("meta"))
        return record

    def delete_document(self, document_id: str) -> bool:
        return self._execute("DELETE FROM documents WHERE id=?", (document_id,)) > 0

    def insert_chunks(
        self, rows: Sequence[Mapping[str, Any]], *, include_embeddings: bool = True
    ) -> int:
        if not rows:
            return 0
        now = to_iso(utcnow())
        payload = []
        for row in rows:
            r = chunk_row(row)
            payload.append(
                (
                    r["document_id"],
                    r["chunk_index"],
                    r["content"],
                    r["token_estimate"],
                    r["char_start"],
                    r["char_end"],
                    r["page"],
                    r["heading"],
                    dump_json(r["embedding"]) if include_embeddings and r["embedding"] else None,
                    dump_json(r["meta"]),
                    now,
                )
            )
        return self._executemany(
            """INSERT OR REPLACE INTO document_chunks (document_id, chunk_index, content,
               token_estimate, char_start, char_end, page, heading, embedding, meta, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            payload,
        )

    def fetch_chunks(self, *, document_id: str | None = None, limit: int = 100000) -> pd.DataFrame:
        where, params = "1=1", []
        if document_id:
            where = "document_id = ?"
            params.append(document_id)
        rows = self._query(
            f"SELECT * FROM document_chunks WHERE {where} ORDER BY document_id, chunk_index LIMIT ?",
            [*params, max(1, int(limit))],
        )
        df = frame(rows)
        if not df.empty:
            if "meta" in df.columns:
                df["meta"] = df["meta"].map(load_json)
            if "embedding" in df.columns:
                df["embedding"] = df["embedding"].map(load_json)
        return df

    def delete_chunks(self, document_id: str) -> int:
        return self._execute("DELETE FROM document_chunks WHERE document_id=?", (document_id,))

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
        return self._execute(
            """INSERT INTO rag_queries (document_id, query, top_k, provider, hit_count,
               top_score, latency_ms, answer, sources, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                document_id,
                query,
                int(top_k),
                provider,
                int(hit_count),
                float(top_score),
                int(latency_ms),
                answer,
                dump_json(list(sources)) if sources else None,
                to_iso(utcnow()),
            ),
        )

    def fetch_rag_queries(self, limit: int = 100) -> pd.DataFrame:
        rows = self._query("SELECT * FROM rag_queries ORDER BY created_at DESC LIMIT ?", (limit,))
        df = frame(rows)
        if not df.empty and "sources" in df.columns:
            df["sources"] = df["sources"].map(load_json)
        return df

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
        return self._execute(
            """INSERT INTO ai_investigations (device_id, anomaly_id, question, answer, provider,
               model, evidence, confidence, citations, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                device_id,
                anomaly_id,
                question,
                answer,
                provider,
                model,
                dump_json(evidence or {}),
                float(confidence) if confidence is not None else None,
                dump_json(list(citations)) if citations else None,
                to_iso(utcnow()),
            ),
        )

    def fetch_investigations(self, limit: int = 100) -> pd.DataFrame:
        rows = self._query(
            "SELECT * FROM ai_investigations ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        df = frame(rows)
        for col in ("evidence", "citations"):
            if col in df.columns:
                df[col] = df[col].map(load_json)
        if not df.empty and "created_at" in df.columns:
            df["created_at"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce")
        return df

    # -- system events --------------------------------------------------------- #
    def insert_system_events(self, rows: Sequence[Mapping[str, Any]]) -> int:
        if not rows:
            return 0
        payload = [
            (
                to_iso(r.get("ts") or utcnow()),
                r.get("level") or "INFO",
                r.get("source") or "sentinel",
                r.get("message") or "",
                dump_json(r.get("context")) if r.get("context") is not None else None,
            )
            for r in rows
        ]
        return self._executemany(
            "INSERT INTO system_events (ts, level, source, message, context) VALUES (?,?,?,?,?)",
            payload,
        )

    def fetch_system_events(self, limit: int = 200) -> pd.DataFrame:
        rows = self._query("SELECT * FROM system_events ORDER BY ts DESC LIMIT ?", (limit,))
        return frame(rows)

    # -- aggregates ------------------------------------------------------------ #
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
                rows = self._query(f"SELECT COUNT(*) AS n FROM {table}")
                counts[table] = int(rows[0]["n"]) if rows else 0
            except DatabaseError:
                counts[table] = 0
        return counts


__all__ = ["LocalRepository", "SCHEMA_VERSION"]
