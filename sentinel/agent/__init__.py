"""Sentinel AI monitoring agent.

Authorised, aggregate-only telemetry collection for systems you own or have
permission to monitor. See :mod:`sentinel.agent.collector` for the enforced
data boundary and :mod:`sentinel.agent.runner` for the CLI.
"""

from __future__ import annotations

from .collector import (
    Collector,
    PSUTIL_AVAILABLE,
    Sample,
    agent_facts,
    collect_network,
    collect_processes,
    collect_system,
    system_facts,
)
from .identity import AGENT_VERSION, AgentIdentity, load_or_create_identity, new_device_id
from .log_tail import LogTailer, LogTarget, TailedLine, redact, targets_from_env
from .runner import AgentRunner, CycleSummary, main
from .sender import DeliveryResult, HttpSender, LocalSender, Sender, Spool

__all__ = [
    "AGENT_VERSION",
    "AgentIdentity",
    "AgentRunner",
    "Collector",
    "CycleSummary",
    "DeliveryResult",
    "HttpSender",
    "LocalSender",
    "LogTailer",
    "LogTarget",
    "PSUTIL_AVAILABLE",
    "Sample",
    "Sender",
    "Spool",
    "TailedLine",
    "agent_facts",
    "collect_network",
    "collect_processes",
    "collect_system",
    "load_or_create_identity",
    "main",
    "new_device_id",
    "redact",
    "system_facts",
    "targets_from_env",
]
