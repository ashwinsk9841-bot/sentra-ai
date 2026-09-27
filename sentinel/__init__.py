"""Sentinel AI - Real-Time AI System Monitoring, Anomaly Detection & Security Intelligence Platform.

Sentinel AI observes systems on which an operator has explicitly installed and
authorized the Sentinel Agent. It collects conventional system-health telemetry
(resource utilisation, disk/network counters, process metadata, application and
system log records) and runs explainable anomaly detection over it.

The package intentionally contains no covert-collection, credential-access,
persistence-evasion or offensive capability. See ``README.md`` (Security &
Privacy notes) for the enforced threat model.
"""

from __future__ import annotations

__all__ = [
    "__version__",
    "APP_NAME",
    "APP_TAGLINE",
    "APP_DESCRIPTION",
]

__version__ = "1.0.0"

APP_NAME = "SENTINEL AI"
APP_TAGLINE = "Real-Time AI System Intelligence"
APP_DESCRIPTION = "Monitor. Detect. Explain."
