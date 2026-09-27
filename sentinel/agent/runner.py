"""The Sentinel agent: a small, explicit, authorised monitoring loop.

Usage::

    python -m sentinel.agent --interval 5 --name my-host
    python -m sentinel.agent --register --pairing-code ABCD1234
    python -m sentinel.agent --once --dry-run

What it does each cycle:

1. Collect aggregate system, network and process metrics (see
   :mod:`sentinel.agent.collector` for the explicit safety boundary).
2. Tail the operator-configured log files, with credential-shaped strings
   masked.
3. Deliver the batch to the configured transport, spooling on failure.

What it never does: read command lines or environment variables, open
keystroke/clipboard/browser stores, capture packets, modify the host, or
persist outside its own state directory.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from ..config import Settings, get_settings
from ..logger import get_logger
from .collector import PSUTIL_AVAILABLE, Collector
from .identity import AGENT_VERSION, AgentIdentity, load_or_create_identity
from .log_tail import LogTarget, LogTailer
from .sender import DeliveryResult, Sender

log = get_logger("agent.runner")

__all__ = ["AgentRunner", "main"]


@dataclass(slots=True)
class CycleSummary:
    """What one agent cycle did."""

    ts: str
    system_rows: int
    network_rows: int
    process_rows: int
    log_rows: int
    delivery: dict[str, Any] | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "system_rows": self.system_rows,
            "network_rows": self.network_rows,
            "process_rows": self.process_rows,
            "log_rows": self.log_rows,
            "delivery": self.delivery,
            "error": self.error,
        }


class AgentRunner:
    """Owns the identity, collector, log tailer and transport."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        state_dir: Path | None = None,
        name: str | None = None,
        log_targets: Sequence[LogTarget] = (),
        repository: Any | None = None,
        sender: Sender | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_directories()
        self.state_dir = state_dir or (self.settings.data_dir / "agent")
        self.identity: AgentIdentity = load_or_create_identity(
            self.state_dir, name=name or self.settings.device_id
        )
        self.collector = Collector(
            interval_s=self.settings.agent_update_interval, process_top=15
        )
        self.tailer = LogTailer(list(log_targets))
        self.sender = sender or Sender.from_settings(
            self.settings, state_dir=self.state_dir, repository=repository
        )
        self._stop = threading.Event()
        self.cycles: list[CycleSummary] = []

    # -- registration -------------------------------------------------------- #
    def register(self, pairing_code: str | None = None) -> dict[str, Any]:
        """Register with the ingest API (HTTP transport only)."""
        backend = self.sender.backend
        if not hasattr(backend, "base_url"):
            raise RuntimeError("Registration requires the HTTP transport (AGENT_INGEST_URL).")
        import urllib.request

        payload = self.identity.registration_payload(
            interval_s=self.settings.agent_update_interval, pairing_code=pairing_code
        )
        url = backend.endpoint.replace("/ingest", "/devices/register")
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, default=str).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {backend.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=backend.timeout) as response:
            body = json.loads(response.read().decode("utf-8") or "{}")
        if body.get("status") == "AUTHORIZED" or body.get("authorized"):
            self.identity.mark_authorized()
        return body

    # -- collection ---------------------------------------------------------- #
    def build_payload(self, *, include_processes: bool = True) -> dict[str, Any]:
        """Collect one cycle and shape it for the ingest API."""
        sample = self.collector.collect(include_processes=include_processes)
        logs = [line.as_row("") for line in self.tailer.poll()]
        return {
            "device_id": self.identity.device_id,
            "device_pk": "",
            "agent_version": AGENT_VERSION,
            "system_metrics": [sample.system],
            "network_metrics": sample.network,
            "process_snapshots": sample.processes,
            "logs": logs,
        }

    def cycle(self, *, include_processes: bool = True, dry_run: bool = False) -> CycleSummary:
        """One collect -> deliver cycle."""
        started = datetime.now(timezone.utc)
        try:
            sample = self.collector.collect(include_processes=include_processes)
            logs = [line.as_row("") for line in self.tailer.poll()]
            payload = {
                "device_id": self.identity.device_id,
                "device_pk": "",
                "agent_version": AGENT_VERSION,
                "system_metrics": [sample.system],
                "network_metrics": sample.network,
                "process_snapshots": sample.processes,
                "logs": logs,
            }
            delivery: dict[str, Any] | None = None
            if dry_run:
                log.info(
                    "dry-run: %d system / %d network / %d process / %d log row(s)",
                    len(payload["system_metrics"]),
                    len(payload["network_metrics"]),
                    len(payload["process_snapshots"]),
                    len(payload["logs"]),
                )
            else:
                result: DeliveryResult = self.sender.send([payload])
                delivery = result.as_dict()
                if not result.ok:
                    log.warning("Delivery failed (%s); spooled %d payload(s)", result.error, result.spooled)
            summary = CycleSummary(
                ts=started.isoformat(),
                system_rows=len(payload["system_metrics"]),
                network_rows=len(payload["network_metrics"]),
                process_rows=len(payload["process_snapshots"]),
                log_rows=len(payload["logs"]),
                delivery=delivery,
            )
        except Exception as exc:
            log.exception("Agent cycle failed")
            summary = CycleSummary(
                ts=started.isoformat(), system_rows=0, network_rows=0, process_rows=0, log_rows=0,
                error=str(exc)[:300],
            )
        self.cycles.append(summary)
        self.cycles = self.cycles[-50:]
        return summary

    # -- loop ---------------------------------------------------------------- #
    def stop(self) -> None:
        self._stop.set()

    def run_forever(self, *, max_cycles: int | None = None, include_processes: bool = True) -> None:
        """Run until stopped (Ctrl-C) or ``max_cycles`` is reached."""
        self._install_signals()
        interval = max(1, int(self.settings.agent_update_interval))
        # Prime network counters so the first throughput reading is real.
        self.collector.prime()

        taken = 0
        log.info(
            "Sentinel agent %s started (device=%s, interval=%ss, transport=%s, psutil=%s)",
            AGENT_VERSION,
            self.identity.device_id,
            interval,
            self.sender.name,
            "yes" if PSUTIL_AVAILABLE else "no",
        )
        while not self._stop.is_set() and (max_cycles is None or taken < max_cycles):
            summary = self.cycle(include_processes=include_processes)
            taken += 1
            log.info("cycle %d: %s", taken, summary.as_dict())
            if self._stop.wait(interval):
                break
            if taken % 12 == 0:
                self.sender.flush_spool()
        log.info("Agent stopped after %d cycle(s).", taken)

    def _install_signals(self) -> None:
        def _handler(signum: int, _frame: Any) -> None:  # pragma: no cover - signal path
            log.info("Received signal %s; shutting down.", signum)
            self.stop()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _handler)
            except (ValueError, OSError):  # pragma: no cover - not main thread
                pass

    # -- reporting ------------------------------------------------------------ #
    def status(self) -> dict[str, Any]:
        """Agent status, safe to render in the dashboard."""
        return {
            "agent_version": AGENT_VERSION,
            "device_id": self.identity.device_id,
            "name": self.identity.name,
            "authorized": self.identity.authorized,
            "registered_at": self.identity.registered_at,
            "interval_s": self.settings.agent_update_interval,
            "psutil_available": PSUTIL_AVAILABLE,
            "transport": self.sender.stats(),
            "log_targets": self.tailer.status(),
            "last_cycle": self.cycles[-1].as_dict() if self.cycles else None,
            "state_dir": str(self.state_dir),
        }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="sentinel.agent",
        description="Sentinel AI monitoring agent (authorised use only).",
    )
    parser.add_argument("--interval", type=int, default=None, help="Seconds between collections.")
    parser.add_argument("--name", default=None, help="Display name for this device.")
    parser.add_argument(
        "--log-file",
        action="append",
        default=[],
        metavar="SOURCE=PATH",
        help="Log file to tail. Repeatable. Nothing else on the host is read.",
    )
    parser.add_argument("--register", action="store_true", help="Register/pair and exit.")
    parser.add_argument("--pairing-code", default=None, help="Pairing code from the dashboard.")
    parser.add_argument("--once", action="store_true", help="Run a single cycle and exit.")
    parser.add_argument("--cycles", type=int, default=None, help="Stop after N cycles.")
    parser.add_argument("--dry-run", action="store_true", help="Collect but do not deliver.")
    parser.add_argument("--status", action="store_true", help="Print agent status as JSON and exit.")
    parser.add_argument("--no-processes", action="store_true", help="Skip the process snapshot.")
    return parser.parse_args(list(argv) if argv is not None else None)


def _targets(entries: Sequence[str]) -> list[LogTarget]:
    from .log_tail import targets_from_env

    return targets_from_env(entries)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = get_settings()
    if args.interval:
        settings = _with_interval(settings, args.interval)

    try:
        runner = AgentRunner(settings, name=args.name, log_targets=_targets(args.log_file))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.status:
        print(json.dumps(runner.status(), indent=2, default=str))
        return 0

    if args.register:
        try:
            body = runner.register(args.pairing_code)
        except Exception as exc:
            print(f"registration failed: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(body, indent=2, default=str))
        return 0

    if args.once:
        summary = runner.cycle(include_processes=not args.no_processes, dry_run=args.dry_run)
        print(json.dumps(summary.as_dict(), indent=2, default=str))
        return 0 if summary.error is None else 1

    runner.run_forever(
        max_cycles=args.cycles, include_processes=not args.no_processes
    )
    return 0


def _with_interval(settings: Settings, interval: int) -> Settings:
    import dataclasses

    return dataclasses.replace(settings, agent_update_interval=max(1, int(interval)))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
