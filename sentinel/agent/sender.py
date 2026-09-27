"""Agent transport.

Two sinks, chosen by configuration:

* **HTTP** - posts batches to the Sentinel ingest API with a bearer key.
* **Local** - writes straight into the configured repository, which is what a
  single-machine deployment (``streamlit`` + agent on the same host) uses.

When HTTP delivery fails the payload is spooled to a bounded on-disk queue and
retried later, so a monitoring agent never silently drops data because the
server was briefly down. The spool is a plain JSON-lines file in the agent's own
state directory - nothing is written anywhere else.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..logger import get_logger

log = get_logger("agent.sender")

__all__ = ["DeliveryResult", "HttpSender", "LocalSender", "Sender", "Spool"]

MAX_BATCH = 500
MAX_SPOOL_LINES = 2000


@dataclass(slots=True)
class DeliveryResult:
    """Outcome of one delivery attempt."""

    ok: bool
    accepted: int = 0
    spooled: int = 0
    status_code: int | None = None
    error: str | None = None
    latency_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "accepted": self.accepted,
            "spooled": self.spooled,
            "status_code": self.status_code,
            "error": self.error,
            "latency_ms": round(self.latency_ms, 1),
        }


class Spool:
    """Bounded JSON-lines retry queue."""

    def __init__(self, path: Path, *, max_lines: int = MAX_SPOOL_LINES) -> None:
        self.path = path
        self.max_lines = int(max_lines)

    def append(self, payloads: Sequence[Mapping[str, Any]]) -> int:
        if not payloads:
            return 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(p, default=str) for p in payloads]
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        self._trim()
        return len(lines)

    def drain(self) -> list[dict[str, Any]]:
        """Read and clear the spool (caller re-appends whatever failed)."""
        if not self.path.is_file():
            return []
        try:
            content = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            log.warning("Could not read spool: %s", exc)
            return []
        payloads: list[dict[str, Any]] = []
        for line in content.splitlines():
            if not line.strip():
                continue
            try:
                payloads.append(json.loads(line))
            except ValueError:
                continue
        self.clear()
        return payloads

    def clear(self) -> None:
        try:
            if self.path.is_file():
                self.path.unlink()
        except OSError as exc:  # pragma: no cover
            log.warning("Could not clear spool: %s", exc)

    def _trim(self) -> None:
        try:
            if not self.path.is_file():
                return
            lines = self.path.read_text(encoding="utf-8").splitlines()
            if len(lines) <= self.max_lines:
                return
            self.path.write_text("\n".join(lines[-self.max_lines :]) + "\n", encoding="utf-8")
        except OSError:  # pragma: no cover
            pass

    @property
    def depth(self) -> int:
        if not self.path.is_file():
            return 0
        try:
            return sum(1 for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip())
        except OSError:  # pragma: no cover
            return 0


class HttpSender:
    """Posts telemetry batches to the ingest API."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 20.0,
        max_retries: int = 3,
        spool: Spool | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = float(timeout)
        self.max_retries = max(1, int(max_retries))
        self.spool = spool

    def endpoint(self) -> str:
        """Full ingest URL."""
        if self.base_url.endswith("/ingest"):
            return self.base_url
        return f"{self.base_url}/ingest"

    def send(self, payloads: Sequence[Mapping[str, Any]]) -> DeliveryResult:
        if not payloads:
            return DeliveryResult(ok=True)
        started = time.perf_counter()
        batch = list(payloads)[:MAX_BATCH]
        body = json.dumps(
            {
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "batch_size": len(batch),
                "items": batch,
            },
            default=str,
        ).encode("utf-8")

        request = urllib.request.Request(
            self.endpoint(),
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "User-Agent": "SentinelAgent/1.0",
            },
            method="POST",
        )

        last_error: str | None = None
        status: int | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    status = response.getcode()
                    payload = json.loads(response.read().decode("utf-8") or "{}")
                return DeliveryResult(
                    ok=True,
                    accepted=int(payload.get("accepted") or len(batch)),
                    status_code=status,
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
            except urllib.error.HTTPError as exc:
                status = exc.code
                detail = exc.read().decode("utf-8", "replace")[:200]
                last_error = f"HTTP {exc.code}: {detail}"
                if 400 <= exc.code < 500 and exc.code not in (408, 429):
                    break  # client error: retrying will not help
            except Exception as exc:
                last_error = str(exc)[:200]
            if attempt < self.max_retries:
                time.sleep(min(8.0, 0.5 * (2 ** (attempt - 1))))

        spooled = 0
        if self.spool is not None:
            spooled = self.spool.append(batch)
        return DeliveryResult(
            ok=False,
            spooled=spooled,
            status_code=status,
            error=last_error,
            latency_ms=(time.perf_counter() - started) * 1000,
        )

    def flush_spool(self) -> DeliveryResult:
        """Attempt to deliver previously spooled batches."""
        if self.spool is None:
            return DeliveryResult(ok=True)
        pending = self.spool.drain()
        if not pending:
            return DeliveryResult(ok=True)
        result = self.send(pending)
        if not result.ok and self.spool is not None:
            self.spool.append(pending)
        return result


class LocalSender:
    """Writes straight into a repository (single-host deployments)."""

    def __init__(self, repository: Any) -> None:
        self.repo = repository

    def send(self, payloads: Sequence[Mapping[str, Any]]) -> DeliveryResult:
        if not payloads:
            return DeliveryResult(ok=True)
        started = time.perf_counter()
        accepted = 0
        try:
            for item in payloads:
                accepted += self._write(item)
            result = DeliveryResult(
                ok=True, accepted=accepted, latency_ms=(time.perf_counter() - started) * 1000
            )
            if not accepted and any(
                (item.get("system_metrics") or item.get("network_metrics") or item.get("logs"))
                for item in payloads
            ):
                result.error = "No device could be resolved for the collected rows."
                result.ok = False
            return result
        except Exception as exc:
            log.warning("Local delivery failed: %s", exc)
            return DeliveryResult(ok=False, error=str(exc)[:200])

    def _write(self, item: Mapping[str, Any]) -> int:
        device_id = str(item.get("device_id") or "")
        device_pk = self._resolve_pk(item)
        system = item.get("system_metrics") or []
        network = item.get("network_metrics") or []
        processes = item.get("process_snapshots") or []
        logs = item.get("logs") or []
        written = 0
        if device_pk:
            if system:
                written += self.repo.insert_system_metrics(
                    [dict(row, device_pk=device_pk) for row in system]
                )
            if network:
                written += self.repo.insert_network_metrics(
                    [dict(row, device_pk=device_pk) for row in network]
                )
            if processes:
                written += self.repo.insert_process_snapshots(
                    [dict(row, device_pk=device_pk) for row in processes]
                )
            if logs:
                written += self.repo.insert_logs([dict(row, device_pk=device_pk) for row in logs])
            self.repo.touch_device(
                device_id,
                cpu_percent=_first(system, "cpu_percent"),
                disk_percent=_first(system, "disk_percent"),
                agent_version=item.get("agent_version"),
            )
        return written

    def _resolve_pk(self, item: Mapping[str, Any]) -> Any:
        """Find the internal device pk, falling back to a public-id lookup.

        The HTTP transport fills this in server-side; the local transport has to
        do it here or every row would be written with a null device.
        """
        device_pk = item.get("device_pk")
        if device_pk:
            return device_pk
        device_id = str(item.get("device_id") or "")
        if not device_id:
            return None
        resolver = getattr(self.repo, "resolve_device_pk", None)
        if callable(resolver):
            return resolver(device_id)
        return device_id  # pragma: no cover - repository without pk support

    def flush_spool(self) -> DeliveryResult:  # pragma: no cover - nothing spooled
        return DeliveryResult(ok=True)


def _first(rows: Sequence[Mapping[str, Any]], key: str) -> float | None:
    if not rows:
        return None
    value = rows[0].get(key)
    return float(value) if isinstance(value, (int, float)) else None


@dataclass
class Sender:
    """Facade that picks the configured transport and keeps counters."""

    backend: Any = None
    spool: Spool | None = None
    sent: int = 0
    failed: int = 0
    spooled: int = 0
    last_result: DeliveryResult | None = field(default=None)

    @classmethod
    def from_settings(
        cls, settings: Any, *, state_dir: Path | None = None, repository: Any | None = None
    ) -> "Sender":
        spool = Spool(state_dir / "spool.jsonl") if state_dir is not None else None
        if settings.agent_ingest_configured:
            backend: Any = HttpSender(
                settings.agent_ingest_url or "",
                settings.agent_ingest_key or "",
                max_retries=settings.agent_max_retries,
                spool=spool,
            )
        elif repository is not None:
            backend = LocalSender(repository)
        else:
            raise ValueError(
                "No transport available: set AGENT_INGEST_URL/AGENT_INGEST_KEY or pass a repository."
            )
        return cls(backend=backend, spool=spool)

    @property
    def name(self) -> str:
        return type(self.backend).__name__.replace("Sender", "").lower()

    def send(self, payloads: Sequence[Mapping[str, Any]]) -> DeliveryResult:
        result = self.backend.send(payloads)
        self._record(result)
        return result

    def flush_spool(self) -> DeliveryResult:
        result = self.backend.flush_spool()
        self._record(result)
        return result

    def _record(self, result: DeliveryResult) -> None:
        self.last_result = result
        if result.ok:
            self.sent += result.accepted
        else:
            self.failed += max(1, result.spooled or 1)
        self.spooled += result.spooled

    def stats(self) -> dict[str, Any]:
        return {
            "transport": self.name,
            "sent": self.sent,
            "failed": self.failed,
            "spooled": self.spooled,
            "spool_depth": self.spool.depth if self.spool else 0,
            "last": self.last_result.as_dict() if self.last_result else None,
        }
