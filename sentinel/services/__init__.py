"""Service layer.

Page code and the CLI talk to these services, never to the database, the ML
pipeline or the RAG pipeline directly. That keeps the UI thin, the logic
testable, and the storage backend swappable.
"""

from __future__ import annotations

from .agent import AgentService
from .analytics import AnalyticsService
from .demo import DemoResult, DemoService
from .monitoring import MonitoringService
from .notify import Notification, NotificationService

__all__ = [
    "AgentService",
    "AnalyticsService",
    "DemoResult",
    "DemoService",
    "MonitoringService",
    "Notification",
    "NotificationService",
]
