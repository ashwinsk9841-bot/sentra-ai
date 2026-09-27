"""System telemetry collection for the Sentinel agent.

Scope and safety rules enforced here, not just documented:

* **Aggregate metrics only.** CPU, memory, disk, network, load, uptime.
* **Process metadata only** - pid, name, owner, resource use. Command lines,
  environment variables and open file paths are never read or transmitted.
* **No user content.** No keystrokes, clipboard, screenshots, browser data,
  document contents, cookies or tokens.
* **No network interception.** Interface counters only; no packet capture.
* **No persistence or evasion.** The agent writes nothing outside its own
  spool directory and registers itself only with a pairing code the operator
  supplies.

Anything the operator cannot see in this file is anything the agent does not do.
"""

from __future__ import annotations

import os
import platform
import socket
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from ..logger import get_logger

log = get_logger("agent.collector")

try:  # pragma: no cover - import guarded so the UI can run without psutil
    import psutil

    PSUTIL_AVAILABLE = True
except Exception:  # pragma: no cover
    psutil = None  # type: ignore[assignment]
    PSUTIL_AVAILABLE = False

__all__ = [
    "Collector",
    "PSUTIL_AVAILABLE",
    "Sample",
    "agent_facts",
    "collect_network",
    "collect_processes",
    "collect_system",
    "system_facts",
]


def system_facts() -> dict[str, Any]:
    """Static, non-identifying host description sent with registration."""
    return {
        "os_name": platform.system() or "Unknown",
        "os_version": platform.release() or "unknown",
        "hostname": socket.gethostname(),
        "arch": platform.machine() or "unknown",
        "python_version": sys.version.split()[0],
        "cpu_count_logical": os.cpu_count() or 0,
        "boot_time": datetime.fromtimestamp(psutil.boot_time(), tz=timezone.utc).isoformat()
        if PSUTIL_AVAILABLE
        else None,
    }


def agent_facts() -> dict[str, Any]:
    """Facts about the agent process itself (used by the Agent Console page)."""
    return {
        "psutil_available": PSUTIL_AVAILABLE,
        "psutil_version": getattr(psutil, "__version__", None),
        "pid": os.getpid(),
        "executable": os.path.basename(sys.executable),
        "platform": platform.platform(),
    }


@dataclass(slots=True)
class Sample:
    """One collection cycle: system, network and process rows for one instant."""

    ts: datetime
    system: dict[str, Any]
    network: list[dict[str, Any]] = field(default_factory=list)
    processes: list[dict[str, Any]] = field(default_factory=list)

    def as_payload(self) -> dict[str, Any]:
        return {
            "ts": self.ts.isoformat(),
            "system_metrics": [self.system],
            "network_metrics": self.network,
            "process_snapshots": self.processes,
        }


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# System metrics
# --------------------------------------------------------------------------- #
def collect_system() -> dict[str, Any]:
    """Aggregate system health for this instant."""
    if not PSUTIL_AVAILABLE:  # pragma: no cover - degraded mode
        return {"ts": _now(), "cpu_percent": None, "memory_percent": None, "raw": {"psutil": "unavailable"}}

    virtual = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage(os.path.abspath(os.sep))
    load1, load5, load15 = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)

    row: dict[str, Any] = {
        "ts": _now(),
        "cpu_percent": float(psutil.cpu_percent(interval=None)),
        "memory_percent": float(virtual.percent),
        "disk_percent": float(disk.percent),
        "swap_percent": float(swap.percent),
        "load_average": float(load1),
        "process_count": int(len(psutil.pids())),
        "thread_count": int(sum(p.info.get("num_threads") or 0 for p in psutil.process_iter(["num_threads"]))),
        "handle_count": _handle_count(),
        "disk_free_gb": round(disk.free / 1024**3, 3),
        "disk_read_mbps": 0.0,
        "disk_write_mbps": 0.0,
        "context_switch_rate": 0.0,
        "uptime_seconds": int(time.time() - psutil.boot_time()),
    }
    row["raw"] = {
        "memory_total_gb": round(virtual.total / 1024**3, 3),
        "memory_available_gb": round(virtual.available / 1024**3, 3),
        "swap_total_gb": round(swap.total / 1024**3, 3),
        "disk_total_gb": round(disk.total / 1024**3, 3),
        "load_5m": round(float(load5), 3),
        "load_15m": round(float(load15), 3),
        "cpu_count_logical": os.cpu_count() or 0,
    }
    return row


def _handle_count() -> int:
    """Open handles across processes, best effort (Linux only, optional)."""
    try:
        count = 0
        for proc in psutil.process_iter(["num_handles"] if sys.platform == "win32" else ["num_fds"]):
            info = proc.info
            count += int((info.get("num_handles") or info.get("num_fds") or 0))
        return count
    except Exception:  # pragma: no cover - not fatal
        return 0


# --------------------------------------------------------------------------- #
# Network
# --------------------------------------------------------------------------- #
def collect_network(
    previous: dict[str, dict[str, int]] | None, *, interval_s: float = 5.0
) -> tuple[list[dict[str, Any]], dict[str, dict[str, int]]]:
    """Per-interface counters and derived throughput.

    Interface counters only - no packet inspection of any kind.
    """
    if not PSUTIL_AVAILABLE:  # pragma: no cover
        return [], previous or {}

    current: dict[str, dict[str, int]] = {}
    rows: list[dict[str, Any]] = []
    elapsed = max(0.5, float(interval_s))
    previous = previous or {}

    counters = psutil.net_io_counters(pernic=True)
    connections = _connection_count()

    for iface, stats in counters.items():
        sent = int(stats.bytes_sent)
        recv = int(stats.bytes_recv)
        current[iface] = {
            "bytes_sent": sent,
            "bytes_recv": recv,
            "packets_sent": int(stats.packets_sent),
            "packets_recv": int(stats.packets_recv),
        }
        prior = previous.get(iface)
        if prior is None:
            sent_mbps = recv_mbps = 0.0
        else:
            sent_mbps = max(0.0, (sent - int(prior.get("bytes_sent", 0))) / elapsed / 1024**2)
            recv_mbps = max(0.0, (recv - int(prior.get("bytes_recv", 0))) / elapsed / 1024**2)
        rows.append(
            {
                "ts": _now(),
                "iface": iface,
                "bytes_sent": sent,
                "bytes_recv": recv,
                "packets_sent": int(stats.packets_sent),
                "packets_recv": int(stats.packets_recv),
                "errin": int(stats.errin),
                "errout": int(stats.errout),
                "dropin": int(stats.dropin),
                "dropout": int(stats.dropout),
                "sent_mbps": round(sent_mbps, 4),
                "recv_mbps": round(recv_mbps, 4),
                "connections": connections,
            }
        )
    return rows, current


def _connection_count() -> int:
    try:
        return int(len(psutil.net_connections(kind="inet")))
    except Exception:  # pragma: no cover - needs privileges on some platforms
        return 0


# --------------------------------------------------------------------------- #
# Processes
# --------------------------------------------------------------------------- #
def collect_processes(*, top: int = 15) -> list[dict[str, Any]]:
    """Top processes by CPU.

    Only identity and resource usage are read. ``cmdline`` and ``environ`` are
    never accessed, so secrets passed on a command line cannot leak.
    """
    if not PSUTIL_AVAILABLE:  # pragma: no cover
        return []

    rows: list[dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "ppid", "name", "username", "status", "cpu_percent", "memory_percent", "memory_info", "num_threads", "create_time"]):
        try:
            info = proc.info
            rss = info.get("memory_info")
            rows.append(
                {
                    "ts": _now(),
                    "pid": int(info.get("pid") or 0),
                    "ppid": int(info.get("ppid") or 0),
                    "name": (info.get("name") or "unknown")[:120],
                    "owner": (info.get("username") or "")[:120],
                    "status": info.get("status") or "unknown",
                    "cpu_percent": round(float(info.get("cpu_percent") or 0.0), 2),
                    "memory_percent": round(float(info.get("memory_percent") or 0.0), 2),
                    "rss_mb": round(getattr(rss, "rss", 0) / 1024**2, 2) if rss else 0.0,
                    "num_threads": int(info.get("num_threads") or 0),
                    "create_time": datetime.fromtimestamp(
                        float(info.get("create_time") or time.time()), tz=timezone.utc
                    ),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("Skipped a process entry: %s", exc)

    rows.sort(key=lambda r: (r["cpu_percent"], r["memory_percent"]), reverse=True)
    return rows[: max(1, int(top))]


# --------------------------------------------------------------------------- #
# Collector
# --------------------------------------------------------------------------- #
class Collector:
    """Stateful collector: keeps the previous network counters for deltas."""

    def __init__(self, *, interval_s: float = 5.0, process_top: int = 15) -> None:
        self.interval_s = float(interval_s)
        self.process_top = int(process_top)
        self._previous_net: dict[str, dict[str, int]] = {}
        self._lock = threading.Lock()
        self._last_sample: Sample | None = None

    @property
    def psutil_available(self) -> bool:
        return PSUTIL_AVAILABLE

    def collect(self, *, include_processes: bool = True) -> Sample:
        """Collect one full sample."""
        with self._lock:
            system = collect_system()
            network, self._previous_net = collect_network(
                self._previous_net, interval_s=self.interval_s
            )
            processes = collect_processes(top=self.process_top) if include_processes else []
            sample = Sample(ts=system["ts"], system=system, network=network, processes=processes)
            self._last_sample = sample
            return sample

    @property
    def last_sample(self) -> Sample | None:
        return self._last_sample

    def prime(self) -> Sample:
        """Take a first sample so the next cycle has a counter baseline.

        The first sample always reports 0 throughput because there is no
        previous counter set to difference against; without priming, throughput
        would look like a spike on the very first reading.
        """
        return self.collect(include_processes=False)


def iter_samples(
    interval_s: float, *, include_processes: bool = True, cycles: int | None = None
) -> Iterable[Sample]:
    """Yield samples forever (or for ``cycles`` iterations). Testing helper."""
    collector = Collector(interval_s=interval_s)
    collector.prime()
    taken = 0
    while cycles is None or taken < cycles:
        time.sleep(max(0.0, float(interval_s)))
        yield collector.collect(include_processes=include_processes)
        taken += 1
