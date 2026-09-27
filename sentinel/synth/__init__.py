"""Synthetic data generation for Demo Mode and the test-suite.

Everything produced here is explicitly marked as synthetic and uses reserved
``SENTINEL-DEMO-*`` device identifiers so demo data can never be confused with
telemetry from a real, authorized device.
"""

from __future__ import annotations

from .generator import (
    DEMO_DEVICE_ID,
    DEMO_DEVICE_NAME,
    SCENARIOS,
    SyntheticProfile,
    demo_device,
    describe_scenario,
    generate_logs,
    generate_network,
    generate_processes,
    generate_telemetry,
    incident_windows,
    levels_for_scenario,
    profile_for,
    sample_document,
    scenario_thresholds,
)

__all__ = [
    "DEMO_DEVICE_ID",
    "DEMO_DEVICE_NAME",
    "SCENARIOS",
    "SyntheticProfile",
    "demo_device",
    "describe_scenario",
    "generate_logs",
    "generate_network",
    "generate_processes",
    "generate_telemetry",
    "incident_windows",
    "levels_for_scenario",
    "profile_for",
    "sample_document",
    "scenario_thresholds",
]
