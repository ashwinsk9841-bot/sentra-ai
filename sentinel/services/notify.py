"""Alert routing.

Sentinel does not page anyone by itself. It records alerts, and this service
turns them into operator-facing notifications through channels the operator
explicitly configures:

* **In-app feed** - always on, backed by the ``alerts`` table.
* **Webhook** - optional; a plain HTTPS POST of a JSON summary.

No channel is enabled unless its URL is configured, no channel is contacted
during a demo seed, and every payload is bounded. Nothing is ever sent to a
hard-coded third party.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import pandas as pd

from ..config import Settings, get_settings
from ..constants import ALERT_STATUS_NEW, SEVERITIES
from ..database.repository import SentinelRepository
from ..logger import get_logger
from .monitoring import MonitoringService

log = get_logger("services.notify")

__all__ = ["Notification", "NotificationService"]

MAX_MESSAGE = 2000
SEVERITY_ICON = {
    "CRITICAL": "🛑",
    "HIGH": "⚠️",
    "MEDIUM": "⚡",
    "LOW": "ℹ️",
}


@dataclass(slots=True)
class Notification:
    """One operator-facing alert notification."""

    severity: str
    title: str
    message: str
    device_id: str | None = None
    alert_id: str | None = None
    anomaly_id: str | None = None
    metric: str | None = None
    risk_score: int = 0
    ts: str = ""
    delivered: bool = False
    detail: str | None = None

    @property
    def icon(self) -> str:
        return SEVERITY_ICON.get(self.severity.upper(), "ℹ️")

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "title": self.title,
            "message": self.message[:MAX_MESSAGE],
            "device_id": self.device_id,
            "alert_id": self.alert_id,
            "anomaly_id": self.anomaly_id,
            "metric": self.metric,
            "risk_score": self.risk_score,
            "ts": self.ts,
            "icon": self.icon,
        }


class NotificationService:
    """Builds the notification feed and delivers to configured channels."""

    def __init__(
        self,
        repository: SentinelRepository | None = None,
        settings: Settings | None = None,
        *,
        service: MonitoringService | None = None,
        webhook_url: str | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.service = service or MonitoringService(repository, self.settings)
        self.repo = self.service.repo
        self.webhook_url = webhook_url

    # ------------------------------------------------------------------ #
    def feed(
        self,
        device_id: str | None = None,
        *,
        window: str = "24h",
        limit: int = 50,
        min_severity: str = "LOW",
    ) -> list[Notification]:
        """Alerts at or above ``min_severity``, worst first."""
        target = self.service.resolve_device_id(device_id)
        alerts = self.service.alerts(target, window=window, limit=limit * 2)
        if alerts.empty:
            return []
        threshold = SEVERITIES.index(min_severity) if min_severity in SEVERITIES else len(SEVERITIES)
        notifications = [_from_alert(record) for record in alerts.to_dict("records")]
        keep = [
            n
            for n in notifications
            if n.severity in SEVERITIES and SEVERITIES.index(n.severity) <= threshold
        ]
        # SEVERITIES is ordered most-severe-first, so the index has to be
        # negated to put CRITICAL at the top rather than LOW.
        keep.sort(key=lambda n: (SEVERITIES.index(n.severity), -n.risk_score))
        return keep[:limit]

    def unread_count(self, device_id: str | None = None) -> int:
        target = self.service.resolve_device_id(device_id)
        alerts = self.service.alerts(target, statuses=[ALERT_STATUS_NEW], window="24h", limit=500)
        return int(len(alerts))

    def acknowledge(self, alert_id: str) -> bool:
        return self.repo.set_alert_status(alert_id, "ACKNOWLEDGED")

    def resolve(self, alert_id: str) -> bool:
        return self.repo.set_alert_status(alert_id, "RESOLVED")

    # ------------------------------------------------------------------ #
    def channels(self) -> list[dict[str, Any]]:
        """Which channels are available right now."""
        return [
            {
                "id": "in_app",
                "name": "In-app feed",
                "enabled": True,
                "detail": f"{self.unread_count()} unacknowledged alert(s)",
            },
            {
                "id": "webhook",
                "name": "Webhook",
                "enabled": bool(self.webhook_url),
                "detail": self.webhook_url or "Not configured (set a URL in Settings).",
            },
        ]

    def deliver(self, notification: Notification) -> Notification:
        """Send to every enabled channel. Never raises."""
        if not self.webhook_url:
            return notification
        payload = json.dumps(
            {
                "text": f"{notification.icon} {notification.severity}: {notification.title}",
                "notification": notification.as_dict(),
            },
            default=str,
        ).encode("utf-8")
        request = urllib.request.Request(
            self.webhook_url,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "SentinelAI/1.0"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                notification.delivered = 200 <= response.getcode() < 300
                notification.detail = f"webhook HTTP {response.getcode()}"
        except urllib.error.HTTPError as exc:
            notification.detail = f"webhook HTTP {exc.code}"
        except Exception as exc:
            notification.detail = f"webhook failed: {str(exc)[:120]}"
        return notification

    def broadcast(self, notifications: Sequence[Notification]) -> dict[str, Any]:
        delivered = 0
        for notification in notifications:
            if self.deliver(notification).delivered:
                delivered += 1
        return {"attempted": len(notifications), "delivered": delivered, "at": datetime.now(timezone.utc).isoformat()}

    def recent(self, device_id: str | None = None, *, limit: int = 100) -> pd.DataFrame:
        target = self.service.resolve_device_id(device_id)
        return self.service.alerts(target, window="7d", limit=limit)


def _from_alert(record: Mapping[str, Any]) -> Notification:
    severity = str(record.get("severity") or "LOW").upper()
    metric = record.get("metric")
    title = str(record.get("title") or (f"{metric} anomaly" if metric else "System alert"))
    return Notification(
        severity=severity if severity in SEVERITIES else "LOW",
        title=title,
        message=str(record.get("message") or ""),
        device_id=record.get("device_id"),
        alert_id=record.get("id"),
        anomaly_id=record.get("anomaly_id"),
        metric=metric,
        risk_score=int(record.get("risk_score") or 0),
        ts=_iso(record.get("ts")),
    )


def _iso(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value or "")
