"""Synthetic telemetry generator.

Used by Demo Mode and by the test-suite. Everything produced here is clearly
labelled as synthetic in the UI and is written to the same tables as real
telemetry, with ``SENTINEL-DEMO-`` device ids so demo data can never be confused
with an authorized device.

The generator models realistic behaviour rather than uniform noise:

* a diurnal load curve (busier during working hours),
* autocorrelated per-metric noise so delta features are meaningful,
* explicit incident windows for the ``anomaly`` and ``critical`` scenarios.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Final, Iterable, Literal, Sequence

import numpy as np
import pandas as pd

from ..constants import CORE_METRICS, LOG_LEVELS

__all__ = [
    "DEMO_DEVICE_ID",
    "DEMO_DEVICE_NAME",
    "SCENARIOS",
    "SyntheticProfile",
    "demo_device",
    "generate_logs",
    "generate_processes",
    "generate_telemetry",
    "incident_windows",
    "profile_for",
    "sample_document",
]

DEMO_DEVICE_ID: Final = "SENTINEL-DEMO-LOCAL-01"
DEMO_DEVICE_NAME: Final = "DEMO-WORKSTATION"
DEMO_AGENT_VERSION: Final = "1.0.0-demo"

Scenario = Literal["normal", "warning", "anomaly", "critical", "mixed"]
SCENARIOS: Final[tuple[str, ...]] = ("normal", "warning", "anomaly", "critical", "mixed")


# --------------------------------------------------------------------------- #
# Profiles
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class SyntheticProfile:
    """Baseline levels and volatility for one behavioural profile."""

    name: str
    cpu_base: float
    cpu_vol: float
    memory_base: float
    memory_vol: float
    net_sent_base: float
    net_recv_base: float
    disk_read_base: float
    disk_write_base: float
    disk_used_base: float
    swap_base: float
    process_base: int
    error_rate: float
    """Probability that a generated log record is ERROR or worse."""
    load_factor: float = 1.0
    thread_factor: float = 6.0
    handle_factor: float = 120.0


PROFILES: dict[str, SyntheticProfile] = {
    "normal": SyntheticProfile(
        name="normal", cpu_base=24.0, cpu_vol=6.0, memory_base=46.0, memory_vol=3.0,
        net_sent_base=0.35, net_recv_base=1.8, disk_read_base=4.0, disk_write_base=2.2,
        disk_used_base=48.0, swap_base=1.0, process_base=210, error_rate=0.012,
    ),
    "warning": SyntheticProfile(
        name="warning", cpu_base=58.0, cpu_vol=9.0, memory_base=68.0, memory_vol=5.0,
        net_sent_base=0.9, net_recv_base=4.5, disk_read_base=9.0, disk_write_base=6.0,
        disk_used_base=66.0, swap_base=8.0, process_base=248, error_rate=0.05,
    ),
    "anomaly": SyntheticProfile(
        name="anomaly", cpu_base=84.0, cpu_vol=10.0, memory_base=79.0, memory_vol=6.0,
        net_sent_base=2.6, net_recv_base=13.0, disk_read_base=22.0, disk_write_base=16.0,
        disk_used_base=79.0, swap_base=22.0, process_base=305, error_rate=0.14,
    ),
    "critical": SyntheticProfile(
        name="critical", cpu_base=96.0, cpu_vol=3.5, memory_base=93.0, memory_vol=3.0,
        net_sent_base=6.5, net_recv_base=34.0, disk_read_base=48.0, disk_write_base=41.0,
        disk_used_base=95.0, swap_base=48.0, process_base=372, error_rate=0.38,
    ),
}


def profile_for(scenario: str) -> SyntheticProfile:
    key = (scenario or "normal").lower()
    return PROFILES.get(key, PROFILES["normal"])


# --------------------------------------------------------------------------- #
# Signal helpers
# --------------------------------------------------------------------------- #
def _diurnal(index: int | np.ndarray, period: int, phase: float = 0.0) -> np.ndarray:
    """Smooth 0-1 daily load curve."""
    angle = 2 * math.pi * ((np.asarray(index, dtype=float) / max(period, 1)) + phase)
    return (0.5 + 0.5 * np.sin(angle)) ** 1.6


def _ar1(rng: np.random.Generator, n: int, rho: float = 0.75) -> np.ndarray:
    """Autocorrelated noise so first differences are not pure white noise."""
    noise = rng.normal(0.0, 1.0, n)
    out = np.empty(n, dtype=float)
    out[0] = noise[0]
    for i in range(1, n):
        out[i] = rho * out[i - 1] + math.sqrt(max(1e-6, 1 - rho**2)) * noise[i]
    return out


def _burst(window: int, magnitude: float) -> np.ndarray:
    """A smooth rise-and-fall curve of exactly ``window`` samples.

    The curve is returned at full window length (not centred inside a longer
    array) so that :func:`_add_burst` can place it at the incident window with
    ``curve[:length]`` and actually have something to add.
    """
    length = max(0, int(window))
    if length <= 0 or not magnitude:
        return np.zeros(length, dtype=float)
    curve = np.sin(np.linspace(0.0, math.pi, length)) ** 1.4
    return curve * float(magnitude)


def _add_burst(
    target: np.ndarray, start: int, stop: int, curve: np.ndarray
) -> None:
    """Add ``curve`` into ``target[start:stop]``, clipped to the array.

    Incident windows are sized from fixed minimums (20 samples), so a short
    series can produce a window that reaches past the end of the array. A plain
    slice assignment would then fail to broadcast; clipping keeps small
    requests - unit tests, tiny demo ranges - working.
    """
    length = min(max(0, stop - start), max(0, len(target) - start), len(curve))
    if length <= 0:
        return
    target[start : start + length] += curve[:length]


def _clamp_windows(
    windows: Sequence[tuple[int, int, str]], n_samples: int
) -> list[tuple[int, int, str]]:
    """Clamp incident windows to the series length and drop empty ones."""
    clamped: list[tuple[int, int, str]] = []
    for start, stop, reason in windows:
        low = max(0, min(int(start), n_samples))
        high = max(0, min(int(stop), n_samples))
        if high - low >= 2:
            clamped.append((low, high, reason))
    return clamped


def incident_windows(n_samples: int, scenario: str) -> list[tuple[int, int, str]]:
    """``[(start, stop, reason), ...]`` describing where incidents occur."""
    n = max(2, int(n_samples))
    if scenario == "mixed":
        third = max(2, n // 3)
        return _clamp_windows(
            [
                (third, third * 2, "sustained load increase"),
                (max(0, n - third // 2), n, "network burst + error storm"),
            ],
            n,
        )
    if scenario in ("anomaly", "critical"):
        width = max(2, int(n * 0.22))
        start = max(0, (n - width) // 2)
        return _clamp_windows(
            [(start, min(n, start + width), f"{scenario} condition sustained")], n
        )
    return []


# --------------------------------------------------------------------------- #
# Telemetry
# --------------------------------------------------------------------------- #
def generate_telemetry(
    samples: int = 240,
    *,
    interval_s: int = 5,
    scenario: Scenario = "mixed",
    seed: int | None = 7,
    start: datetime | None = None,
    disk_total_gb: float = 512.0,
) -> pd.DataFrame:
    """Generate a telemetry frame with the ``CORE_METRICS`` schema."""
    n = max(2, int(samples))
    rng = np.random.default_rng(seed)
    py_random = random.Random(seed)

    end = start or (datetime.now(timezone.utc) - timedelta(seconds=interval_s * n))
    timestamps = [end - timedelta(seconds=interval_s * (n - 1 - i)) for i in range(n)]

    base = profile_for("normal")
    # Blend the normal baseline with the requested scenario over time.
    target = profile_for(scenario)
    curve = _diurnal(np.arange(n), period=max(24, int(86400 / max(interval_s, 1))), phase=0.28)

    cpu_noise = _ar1(rng, n, 0.8)
    mem_noise = _ar1(rng, n, 0.9)
    net_noise = _ar1(rng, n, 0.6)
    disk_noise = _ar1(rng, n, 0.7)

    burst_cpu = np.zeros(n)
    burst_mem = np.zeros(n)
    burst_net = np.zeros(n)
    burst_disk = np.zeros(n)
    burst_swap = np.zeros(n)
    windows = incident_windows(n, scenario)
    # A "mixed" series has no single target profile - each incident window
    # escalates toward a different one (a mild warning first, a hard anomaly at
    # the end), otherwise the deltas below would all be zero.
    window_profiles = (
        ["warning", "anomaly"] if scenario == "mixed" else [scenario] * max(1, len(windows))
    )
    for index, (start_i, stop_i, _reason) in enumerate(windows):
        width = stop_i - start_i
        window_target = profile_for(window_profiles[index % len(window_profiles)])
        _add_burst(
            burst_cpu, start_i, stop_i, _burst(width, window_target.cpu_base - base.cpu_base)
        )
        _add_burst(
            burst_mem, start_i, stop_i, _burst(width, window_target.memory_base - base.memory_base)
        )
        _add_burst(
            burst_net,
            start_i,
            stop_i,
            _burst(width, window_target.net_recv_base - base.net_recv_base),
        )
        _add_burst(
            burst_disk,
            start_i,
            stop_i,
            _burst(width, window_target.disk_read_base - base.disk_read_base),
        )
        _add_burst(
            burst_swap, start_i, stop_i, _burst(width, window_target.swap_base - base.swap_base)
        )

    records: list[dict[str, Any]] = []
    disk_used = base.disk_used_base
    boot_offset = py_random.uniform(0, 6) * 86400
    context_switch_baseline = float(rng.uniform(800.0, 1600.0))

    for i, ts in enumerate(timestamps):
        # Scenario blend: 0 -> normal baseline, 1 -> target profile.
        blend = min(1.0, (i / max(1, n - 1)) * 1.35) if scenario != "mixed" else 1.0
        load = 0.75 + 0.35 * float(curve[i])

        cpu = (
            base.cpu_base + (target.cpu_base - base.cpu_base) * blend
        ) * load + base.cpu_vol * cpu_noise[i] + burst_cpu[i]
        mem = (
            base.memory_base + (target.memory_base - base.memory_base) * blend
        ) + base.memory_vol * mem_noise[i] + burst_mem[i]
        net_sent = (
            base.net_sent_base + (target.net_sent_base - base.net_sent_base) * blend
        ) * load * max(0.25, 1.0 + 0.45 * net_noise[i])
        net_recv = (
            base.net_recv_base + (target.net_recv_base - base.net_recv_base) * blend
        ) * load * max(0.25, 1.0 + 0.45 * net_noise[i]) + burst_net[i]
        disk_read = (
            base.disk_read_base + (target.disk_read_base - base.disk_read_base) * blend
        ) * max(0.2, 1.0 + 0.35 * disk_noise[i])
        disk_write = (
            base.disk_write_base + (target.disk_write_base - base.disk_write_base) * blend
        ) * max(0.2, 1.0 + 0.30 * disk_noise[i])
        swap = max(0.0, (base.swap_base + (target.swap_base - base.swap_base) * blend)
                   + 0.35 * mem_noise[i] + burst_swap[i])

        # Disk utilisation drifts upward, and faster under load.
        disk_used = min(
            99.4,
            max(4.0, disk_used + 0.006 * (target.disk_used_base - base.disk_used_base) + 0.004 * disk_noise[i]),
        )
        disk_free = max(0.0, disk_total_gb * (1.0 - disk_used / 100.0))

        process_count = int(
            max(35, base.process_base + (target.process_base - base.process_base) * blend + 9 * cpu_noise[i])
        )
        thread_count = int(process_count * (base.thread_factor + 1.5 * (cpu / 100.0)) + 40 * mem_noise[i])
        handle_count = int(process_count * (base.handle_factor + 90 * (mem / 100.0)) + 200 * cpu_noise[i])
        load_average = round(
            max(0.0, (cpu / 100.0) * max(1, _os_cpu_count()) * 0.55 + 0.25 * cpu_noise[i]), 3
        )
        context_switch = max(
            50.0, context_switch_baseline * (0.7 + 0.9 * (cpu / 100.0)) + 220 * cpu_noise[i]
        )

        records.append(
            {
                "ts": ts,
                "cpu_percent": _clip(cpu, 0.5, 100.0),
                "memory_percent": _clip(mem, 1.0, 100.0),
                "disk_percent": _clip(disk_used, 1.0, 100.0),
                "swap_percent": _clip(swap, 0.0, 100.0),
                "load_average": load_average,
                "process_count": process_count,
                "thread_count": thread_count,
                "handle_count": handle_count,
                "disk_free_gb": round(disk_free, 3),
                "disk_read_mbps": round(_clip(disk_read, 0.0, 5000.0), 3),
                "disk_write_mbps": round(_clip(disk_write, 0.0, 5000.0), 3),
                "net_sent_mbps": round(_clip(net_sent, 0.0, 5000.0), 4),
                "net_recv_mbps": round(_clip(net_recv, 0.0, 5000.0), 4),
                "context_switch_rate": round(context_switch, 2),
                "uptime_seconds": int(
                    (ts - timestamps[0]).total_seconds() + boot_offset
                ),
                "temperature_c": round(_clip(38.0 + 22.0 * (cpu / 100.0) + 1.5 * mem_noise[i], 20.0, 95.0), 2),
            }
        )

    frame = pd.DataFrame(records)
    return frame[["ts", *CORE_METRICS]]


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _os_cpu_count() -> int:
    import os

    return max(1, os.cpu_count() or 1)


# --------------------------------------------------------------------------- #
# Network
# --------------------------------------------------------------------------- #
def generate_network(
    samples: int = 240, *, interval_s: int = 5, scenario: Scenario = "mixed", seed: int = 11
) -> pd.DataFrame:
    """Network counters consistent with the generated CPU/network curve."""
    telemetry = generate_telemetry(samples, interval_s=interval_s, scenario=scenario, seed=seed)
    rng = np.random.default_rng(seed + 1)
    bytes_sent = 0
    bytes_recv = 0
    packets_sent = 0
    packets_recv = 0
    rows: list[dict[str, Any]] = []
    interval_bytes = max(1, interval_s)

    for _, row in telemetry.iterrows():
        sent_b = int(row["net_sent_mbps"] * 1_048_576 * interval_bytes)
        recv_b = int(row["net_recv_mbps"] * 1_048_576 * interval_bytes)
        bytes_sent += sent_b
        bytes_recv += recv_b
        packets_sent += int(sent_b / np.random.uniform(600, 1400))
        packets_recv += int(recv_b / np.random.uniform(600, 1400))
        rows.append(
            {
                "ts": row["ts"],
                "iface": "demo0",
                "bytes_sent": bytes_sent,
                "bytes_recv": bytes_recv,
                "packets_sent": packets_sent,
                "packets_recv": packets_recv,
                "errin": int(rng.integers(0, 3)),
                "errout": int(rng.integers(0, 3)),
                "dropin": int(rng.integers(0, 5)),
                "dropout": int(rng.integers(0, 5)),
                "sent_mbps": round(float(row["net_sent_mbps"]), 4),
                "recv_mbps": round(float(row["net_recv_mbps"]), 4),
                "connections": int(max(4, 90 * (row["cpu_percent"] / 100.0) + rng.normal(0, 6))),
            }
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Processes
# --------------------------------------------------------------------------- #
_PROCESS_POOL: Final[tuple[tuple[str, float, float, str], ...]] = (
    ("system", 0.4, 0.3, "SYSTEM"),
    ("python", 2.6, 3.1, "RUNNING"),
    ("node", 3.4, 4.8, "RUNNING"),
    ("postgres", 1.8, 6.2, "RUNNING"),
    ("redis-server", 0.3, 0.9, "SLEEPING"),
    ("nginx", 0.6, 0.7, "SLEEPING"),
    ("streamlit", 2.2, 5.4, "RUNNING"),
    ("chrome", 4.8, 7.1, "RUNNING"),
    ("defender", 1.1, 2.4, "RUNNING"),
    ("sshd", 0.05, 0.1, "SLEEPING"),
    ("cron", 0.02, 0.05, "SLEEPING"),
)


def generate_processes(
    count: int = 24, *, scenario: Scenario = "normal", seed: int = 13, ts: datetime | None = None
) -> pd.DataFrame:
    """Safe process metadata: identity and resource use only, no command lines."""
    rng = np.random.default_rng(seed)
    pressure = {"normal": 1.0, "warning": 1.7, "anomaly": 3.1, "critical": 4.6}.get(scenario, 1.0)
    stamp = ts or datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    pid = 1000
    for index in range(max(1, count)):
        name, cpu_base, mem_base, status = _PROCESS_POOL[index % len(_PROCESS_POOL)]
        pid += int(rng.integers(4, 90))
        cpu = max(0.0, rng.gamma(2.0, cpu_base * pressure * 0.6))
        mem = max(0.05, rng.gamma(2.2, mem_base * pressure * 0.55))
        rows.append(
            {
                "ts": stamp,
                "pid": pid,
                "ppid": 4 if index % 3 else 0,
                "name": f"{name}.exe" if name != "system" else "System",
                "owner": "SYSTEM" if name in ("system", "defender") else "operator",
                "status": status,
                "cpu_percent": round(min(100.0, cpu), 2),
                "memory_percent": round(min(100.0, mem), 2),
                "rss_mb": round(mem * 42.0, 1),
                "num_threads": max(1, int(mem * 9 + rng.integers(0, 6))),
                "create_time": stamp - timedelta(seconds=int(rng.integers(60, 400000))),
            }
        )
    return pd.DataFrame(rows).sort_values("cpu_percent", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Logs
# --------------------------------------------------------------------------- #
_LOG_TEMPLATES: Final[tuple[tuple[str, str], ...]] = (
    ("INFO", "request completed method=GET path=/api/v1/metrics status=200 duration_ms={d}"),
    ("INFO", "request completed method=POST path=/api/v1/ingest status=202 duration_ms={d}"),
    ("INFO", "cache warm complete entries={n}"),
    ("INFO", "scheduled job finished job=metrics-rollup rows={n}"),
    ("INFO", "agent heartbeat interval={n}s"),
    ("WARNING", "slow request detected method=GET path=/api/v1/reports duration_ms={d}"),
    ("WARNING", "connection pool at {n}% capacity"),
    ("WARNING", "retrying upstream call attempt={n}"),
    ("ERROR", "upstream timeout method=GET path=/api/v1/sync after {d}ms"),
    ("ERROR", "database connection reset by peer"),
    ("ERROR", "failed to persist batch size={n}"),
    ("CRITICAL", "service degraded: error rate {n}% over 5m window"),
    ("CRITICAL", "disk usage above critical threshold on /data"),
)

_LOG_SOURCES: Final[tuple[str, ...]] = ("sentinel-agent", "api-gateway", "worker", "database", "system")


def generate_logs(
    samples: int = 240,
    *,
    interval_s: int = 5,
    scenario: Scenario = "mixed",
    seed: int = 17,
    per_sample: float = 0.55,
) -> pd.DataFrame:
    """Log records whose severity mix tracks the requested scenario."""
    telemetry = generate_telemetry(samples, interval_s=interval_s, scenario=scenario, seed=seed)
    rng = np.random.default_rng(seed + 3)
    py_random = random.Random(seed + 3)
    profile = profile_for("anomaly" if scenario in ("anomaly", "critical") else scenario)
    rows: list[dict[str, Any]] = []

    for _, sample in telemetry.iterrows():
        if py_random.random() > per_sample:
            continue
        stress = max(0.0, (float(sample["cpu_percent"]) - 55.0) / 45.0)
        error_prob = min(0.75, profile.error_rate + stress * 0.28)
        roll = py_random.random()
        if roll < min(0.02, error_prob * 0.4):
            level = "CRITICAL"
        elif roll < error_prob:
            level = "ERROR"
        elif roll < error_prob + 0.18 + stress * 0.2:
            level = "WARNING"
        else:
            level = "INFO"

        template_pool = [t for t in _LOG_TEMPLATES if t[0] == level] or [("INFO", "heartbeat")]
        template = template_pool[py_random.randrange(len(template_pool))]
        message = template[1].format(
            d=int(abs(rng.normal(120, 90))) + 5,
            n=int(abs(rng.normal(240, 90))) + 3,
        )
        source = _LOG_SOURCES[py_random.randrange(len(_LOG_SOURCES))]
        fingerprint = hashlib.sha1(
            f"{level}|{source}|{_normalise_message(message)}".encode()
        ).hexdigest()[:16]
        rows.append(
            {
                "ts": sample["ts"] + timedelta(seconds=int(rng.integers(0, max(1, interval_s)))),
                "source": source,
                "level": level,
                "message": message,
                "logger_name": f"{source}.core",
                "module": _normalise_message(message).split(" ")[0],
                "line_no": int(rng.integers(100, 9999)),
                "fingerprint": fingerprint,
                "occurrences": 1,
                "attributes": {"synthetic": True, "scenario": scenario},
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=[
                "ts", "source", "level", "message", "logger_name", "module",
                "line_no", "fingerprint", "occurrences", "attributes",
            ]
        )
    return pd.DataFrame(rows).sort_values("ts", kind="stable").reset_index(drop=True)


def _normalise_message(message: str) -> str:
    """Strip variable values so identical errors share a fingerprint."""
    out: list[str] = []
    for token in message.split():
        cleaned = token
        for sep in ("=", ":"):
            if sep in cleaned:
                cleaned = cleaned.split(sep, 1)[0]
        if cleaned.isdigit() or cleaned.replace(".", "", 1).isdigit():
            cleaned = "<n>"
        out.append(cleaned)
    return " ".join(out)


# --------------------------------------------------------------------------- #
# Device record
# --------------------------------------------------------------------------- #
def demo_device() -> dict[str, Any]:
    """Registration payload for the synthetic device."""
    import platform
    import sys

    return {
        "device_id": DEMO_DEVICE_ID,
        "name": DEMO_DEVICE_NAME,
        "os_name": platform.system() or "Unknown",
        "os_version": platform.release(),
        "hostname": "sentinel-demo",
        "arch": platform.machine() or "unknown",
        "agent_version": DEMO_AGENT_VERSION,
        "python_version": sys.version.split()[0],
        "interval_s": 5,
        "metadata": {"synthetic": True, "scenario": "mixed", "generator": "sentinel.synth"},
    }


# --------------------------------------------------------------------------- #
# Sample knowledge document
# --------------------------------------------------------------------------- #
def sample_document() -> tuple[str, str]:
    """A real runbook authored for the demo corpus.

    Returns ``(filename, text)``. This is genuine reference material written
    for Sentinel AI - not a placeholder - so RAG retrieval has something
    meaningful to work with out of the box.
    """
    text = """Sentinel AI - Anomaly Response Runbook

1. PURPOSE
This runbook describes how an operator responds to anomalies reported by
Sentinel AI on an authorized monitored system. Sentinel AI reports anomalous
behaviour derived from system-health telemetry. It does not attribute cause,
and a detected anomaly is not by itself evidence of malicious activity.

2. SEVERITY BANDS
Sentinel AI assigns a risk score between 0 and 100 and maps it to a severity:
  0-30   LOW      - record only; no action required.
  31-60  MEDIUM   - review during the next operational window.
  61-80  HIGH     - investigate within one hour.
  81-100 CRITICAL - investigate immediately.

3. TRIAGE PROCEDURE
Step 1. Confirm the signal. Open the Anomalies page and read the explanation.
Every anomaly lists the observed value, the learned baseline, the difference,
the model score, the risk score and the severity.
Step 2. Check the baseline quality. If the analyzer reports fewer than 60
samples, treat the baseline as provisional and gather more telemetry before
acting on a HIGH or CRITICAL verdict.
Step 3. Correlate with change. Check whether a deployment, batch job, backup
or configuration change occurred within the anomaly window. Most anomalies in
a healthy environment are explained by legitimate workload change.
Step 4. Inspect the contributing processes. The Process Monitor shows CPU and
memory share by process. A sustained increase in thread count or handle count
usually indicates a resource leak rather than an intrusion.
Step 5. Inspect the logs. The Logs page groups records by fingerprint. A sudden
increase in the repetition rate of a single error fingerprint is a stronger
signal than any individual record.

4. NETWORK ANOMALIES
Sentinel AI records interface counters only: bytes, packets, errors and drops.
It does not capture packet contents. When network throughput exceeds the
learned baseline, identify which process is responsible using the Network and
Process pages, then confirm the traffic matches an expected workload such as a
backup, a data sync or a deployment artifact pull.

5. MEMORY ANOMALIES
Compare current memory utilisation with the trailing baseline. A monotonic
increase over hours, with rising swap utilisation, indicates memory pressure.
Investigate long-running processes for leaks before restarting anything. A
sudden step change that returns to baseline is more likely a workload change.

6. DISK ANOMALIES
Free space below the configured threshold is reported as a breach. Confirm
that backups can still complete, then identify the largest recent growth.
Elevated write throughput combined with high disk utilisation often indicates
a runaway log writer or an unbounded export.

7. WHAT SENTINEL AI DOES NOT DO
Sentinel AI does not capture keystrokes, credentials, browser data, tokens or
private message content. It does not intercept packets. It does not modify the
host, disable security tooling or conceal itself. Agents run as ordinary,
visible processes and send only aggregate telemetry.

8. ESCALATION
Escalate to CRITICAL when a resource metric is saturated and a matching log
fingerprint is repeating at an elevated rate, or when risk score trends upward
across consecutive windows with no matching change record. Record the anomaly
identifier, the evidence reviewed and the action taken in the alert status.
"""
    return "sentinel-anomaly-response-runbook.md", text


def levels_for_scenario(scenario: str) -> Iterable[str]:
    """Level mix used to describe a scenario in the UI."""
    profile = profile_for(scenario)
    if profile.error_rate < 0.02:
        return ("INFO", "WARNING")
    if profile.error_rate < 0.1:
        return ("INFO", "WARNING", "ERROR")
    return ("INFO", "WARNING", "ERROR", "CRITICAL")


def describe_scenario(scenario: str) -> str:
    """One-line human description shown next to the Demo Mode selector."""
    return {
        "normal": "Steady baseline behaviour with a normal diurnal load curve.",
        "warning": "Elevated but plausible resource use with an increased warning rate.",
        "anomaly": "A sustained incident window: high CPU, network burst, error rise.",
        "critical": "Saturated resources, large traffic surge and a critical error storm.",
        "mixed": "Mostly normal operation with two distinct incident windows.",
    }.get(scenario, "Synthetic mixed workload.")


def scenario_thresholds(scenario: str) -> Sequence[str]:
    """Severity bands a scenario is expected to exercise."""
    return {
        "normal": ("LOW",),
        "warning": ("LOW", "MEDIUM"),
        "anomaly": ("MEDIUM", "HIGH"),
        "critical": ("HIGH", "CRITICAL"),
        "mixed": ("LOW", "MEDIUM", "HIGH", "CRITICAL"),
    }[scenario]


assert set(LOG_LEVELS) >= {"INFO", "WARNING", "ERROR", "CRITICAL"}
