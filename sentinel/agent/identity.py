"""Agent identity and pairing.

A Sentinel agent is authorised, not anonymous: it holds a device id, and it
only becomes ``AUTHORIZED`` after an operator generates a pairing code in the
dashboard and the agent presents it during registration.

The identity file lives in the agent's own state directory and contains no
secret beyond the ingest API key the operator configured.
"""

from __future__ import annotations

import json
import platform
import re
import socket
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..logger import get_logger
from .collector import system_facts

log = get_logger("agent.identity")

__all__ = ["AgentIdentity", "load_or_create_identity", "new_device_id"]

AGENT_VERSION = "1.0.0"

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def new_device_id() -> str:
    """A stable, non-identifying device id (``sent-<short uuid>``)."""
    return f"sent-{uuid.uuid4().hex[:12]}"


def _safe_name(value: str) -> str:
    return _SAFE.sub("-", (value or "").strip())[:48] or "device"


@dataclass(slots=True)
class AgentIdentity:
    """Persistent agent identity plus the facts sent at registration."""

    device_id: str
    state_path: Path
    name: str = ""
    pairing_code: str | None = None
    authorized: bool = False
    registered_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # -- persistence -------------------------------------------------------- #
    def save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "device_id": self.device_id,
            "name": self.name,
            "authorized": self.authorized,
            "registered_at": self.registered_at,
            "agent_version": AGENT_VERSION,
            "metadata": self.metadata,
        }
        self.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        try:
            self.state_path.chmod(0o600)
        except OSError:  # pragma: no cover - Windows ACLs
            pass

    def mark_authorized(self) -> None:
        self.authorized = True
        self.registered_at = datetime.now(timezone.utc).isoformat()
        self.save()

    # -- payloads ------------------------------------------------------------ #
    def registration_payload(self, *, interval_s: int, pairing_code: str | None = None) -> dict[str, Any]:
        facts = system_facts()
        return {
            "device_id": self.device_id,
            "name": self.name or f"sentinel-agent-{self.device_id[-4:]}",
            "os_name": facts["os_name"],
            "os_version": facts["os_version"],
            "hostname": facts["hostname"],
            "arch": facts["arch"],
            "agent_version": AGENT_VERSION,
            "pairing_code": pairing_code or self.pairing_code,
            "python_version": facts["python_version"],
            "interval_s": int(interval_s),
            "metadata": {
                "cpu_count_logical": facts.get("cpu_count_logical"),
                "boot_time": facts.get("boot_time"),
                "platform": platform.platform(),
                "synthetic": False,
            },
        }


def load_or_create_identity(
    state_dir: Path, *, name: str | None = None, device_id: str | None = None
) -> AgentIdentity:
    """Load the stored identity or create a new one."""
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "identity.json"
    if state_path.is_file():
        try:
            stored = json.loads(state_path.read_text(encoding="utf-8"))
            identity = AgentIdentity(
                device_id=str(stored.get("device_id") or device_id or new_device_id()),
                state_path=state_path,
                name=str(stored.get("name") or name or ""),
                authorized=bool(stored.get("authorized")),
                registered_at=stored.get("registered_at"),
                metadata=dict(stored.get("metadata") or {}),
            )
            if device_id and device_id != identity.device_id:
                identity.device_id = device_id
            if name:
                identity.name = _safe_name(name)
            identity.save()
            return identity
        except (OSError, ValueError, TypeError) as exc:
            log.warning("Identity file unreadable (%s); creating a new one.", exc)

    identity = AgentIdentity(
        device_id=device_id or new_device_id(),
        state_path=state_path,
        name=_safe_name(name or f"{socket.gethostname()}-{sys.platform}"),
    )
    identity.save()
    return identity


def device_hint() -> str:
    """A human-friendly default device name."""
    return _safe_name(f"{platform.node() or 'host'}-{platform.system().lower()}")

