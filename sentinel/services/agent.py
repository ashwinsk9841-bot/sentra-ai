"""Agent management: pairing, fleet view, and the agent console feed.

This is the operator-facing half of the agent. The agent half collects and
ships; this service authorises, lists and explains.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from ..config import Settings, get_settings
from ..database.repository import SentinelRepository
from ..logger import get_logger
from .monitoring import MonitoringService

log = get_logger("services.agent")

__all__ = ["AgentService"]


class AgentService:
    """Pairing codes, device fleet, and the agent readiness report."""

    def __init__(
        self,
        repository: SentinelRepository | None = None,
        settings: Settings | None = None,
        *,
        service: MonitoringService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.service = service or MonitoringService(repository, self.settings)
        self.repo = self.service.repo

    # ------------------------------------------------------------------ #
    # Pairing
    # ------------------------------------------------------------------ #
    def create_pairing_code(self, *, ttl_minutes: int = 30) -> dict[str, Any]:
        """Issue a short-lived pairing code for an agent to present."""
        code, expires = self.repo.create_pairing_code(ttl_minutes=ttl_minutes)
        self.service.record_event(
            "INFO",
            "agent",
            f"Pairing code issued (expires {expires.isoformat() if hasattr(expires, 'isoformat') else expires}).",
            {"ttl_minutes": ttl_minutes},
        )
        return {
            "code": code,
            "expires_at": expires.isoformat() if hasattr(expires, "isoformat") else str(expires),
            "ttl_minutes": int(ttl_minutes),
            "instructions": (
                "Run: python -m sentinel.agent --register --pairing-code <CODE> "
                "--name <device-name>"
            ),
        }

    def revoke_device(self, device_id: str) -> bool:
        """Remove a device and stop accepting its telemetry."""
        return self.repo.delete_device(device_id)

    def set_status(self, device_id: str, status: str) -> bool:
        return self.repo.set_device_status(device_id, status)

    # ------------------------------------------------------------------ #
    # Fleet
    # ------------------------------------------------------------------ #
    def fleet(self) -> pd.DataFrame:
        """All registered devices with liveness and risk."""
        devices = self.repo.list_devices()
        if devices.empty:
            return devices
        now = datetime.now(timezone.utc)
        rows: list[dict[str, Any]] = []
        for record in devices.to_dict("records"):
            last_seen = record.get("last_seen")
            age_s = None
            if last_seen is not None and not (isinstance(last_seen, float) and last_seen != last_seen):
                stamp = pd.Timestamp(last_seen)
                stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
                age_s = (now - stamp).total_seconds()
            rows.append(
                {
                    **record,
                    "last_seen_age_s": round(age_s, 1) if age_s is not None else None,
                    "online": bool(age_s is not None and age_s <= max(60, self.settings.agent_update_interval * 4)),
                }
            )
        return pd.DataFrame(rows)

    def status(self, device_id: str | None = None) -> dict[str, Any]:
        """Agent readiness for the Agent Console page."""
        target = self.service.resolve_device_id(device_id)
        device = self.service.device(target) or {}
        health = self.repo.health()
        return {
            "transport": {
                "mode": "http" if self.settings.agent_ingest_configured else "local-repository",
                "url": self.settings.agent_ingest_url,
                "key_configured": bool(self.settings.agent_ingest_key),
                "max_retries": self.settings.agent_max_retries,
            },
            "collection": {
                "interval_s": self.settings.agent_update_interval,
                "psutil_available": _psutil(),
                "metrics": [
                    "cpu_percent",
                    "memory_percent",
                    "disk_percent",
                    "swap_percent",
                    "load_average",
                    "process_count",
                    "thread_count",
                    "disk_free_gb",
                    "network throughput",
                ],
                "excluded": [
                    "command lines",
                    "environment variables",
                    "keystrokes",
                    "clipboard",
                    "browser data",
                    "packet payloads",
                ],
            },
            "device": {
                "device_id": target,
                "name": device.get("name"),
                "status": device.get("status"),
                "last_seen": _iso(device.get("last_seen")),
                "agent_version": device.get("agent_version"),
                "interval_s": device.get("interval_s"),
            },
            "backend": health.as_dict(),
            "data_boundary": [
                "Aggregate metrics only - no user content is collected.",
                "Process identity and resource use only; no command lines or env vars.",
                "Network interface counters only; no packet capture or inspection.",
                "Log tailing limited to files the operator lists explicitly.",
                "Credential-shaped strings are masked before transmission.",
                "The agent writes only to its own state directory.",
            ],
        }

    def recent_events(self, *, limit: int = 50) -> pd.DataFrame:
        return self.repo.fetch_system_events(limit=limit)


def _psutil() -> bool:
    try:
        import psutil  # noqa: F401

        return True
    except Exception:  # pragma: no cover
        return False


def _iso(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
