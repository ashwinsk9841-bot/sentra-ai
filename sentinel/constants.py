"""Domain constants shared by the agent, ML pipeline, services and UI.

Keeping these in one module prevents magic strings from drifting between the
collector, the database layer and the dashboards.
"""

from __future__ import annotations

from typing import Final

# --------------------------------------------------------------------------- #
# Severity / risk
# --------------------------------------------------------------------------- #

SEVERITY_LOW: Final = "LOW"
SEVERITY_MEDIUM: Final = "MEDIUM"
SEVERITY_HIGH: Final = "HIGH"
SEVERITY_CRITICAL: Final = "CRITICAL"

#: Ordered worst-first so that ``max()`` on severities is meaningful.
SEVERITIES: Final[tuple[str, ...]] = (
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    SEVERITY_LOW,
)

#: Inclusive risk-score bands -> severity label.
RISK_BANDS: Final[tuple[tuple[int, str], ...]] = (
    (81, SEVERITY_CRITICAL),
    (61, SEVERITY_HIGH),
    (31, SEVERITY_MEDIUM),
    (0, SEVERITY_LOW),
)

SEVERITY_RANK: Final[dict[str, int]] = {s: i for i, s in enumerate(SEVERITIES)}

#: Statuses used by alert lifecycle.
ALERT_STATUS_NEW: Final = "NEW"
ALERT_STATUS_ACKNOWLEDGED: Final = "ACKNOWLEDGED"
ALERT_STATUS_RESOLVED: Final = "RESOLVED"
ALERT_STATUSES: Final[tuple[str, ...]] = (
    ALERT_STATUS_NEW,
    ALERT_STATUS_ACKNOWLEDGED,
    ALERT_STATUS_RESOLVED,
)

#: Security-posture colours used on the Security Health page.
POSTURE_GREEN: Final = "GREEN"
POSTURE_YELLOW: Final = "YELLOW"
POSTURE_RED: Final = "RED"
POSTURES: Final[tuple[str, ...]] = (POSTURE_GREEN, POSTURE_YELLOW, POSTURE_RED)

# --------------------------------------------------------------------------- #
# Log levels
# --------------------------------------------------------------------------- #

LOG_LEVELS: Final[tuple[str, ...]] = ("INFO", "WARNING", "ERROR", "CRITICAL", "ANOMALY")
LOG_LEVEL_RANK: Final[dict[str, int]] = {name: i for i, name in enumerate(LOG_LEVELS)}

# --------------------------------------------------------------------------- #
# Telemetry
# --------------------------------------------------------------------------- #

#: Metrics that form the feature vector for anomaly detection.
CORE_METRICS: Final[tuple[str, ...]] = (
    "cpu_percent",
    "memory_percent",
    "disk_percent",
    "disk_read_mbps",
    "disk_write_mbps",
    "net_sent_mbps",
    "net_recv_mbps",
    "process_count",
    "thread_count",
    "load_average",
    "disk_free_gb",
    "swap_percent",
    "context_switch_rate",
    "handle_count",
)

#: Human-facing labels for metric keys.
METRIC_LABELS: Final[dict[str, str]] = {
    "cpu_percent": "CPU utilisation",
    "memory_percent": "Memory utilisation",
    "disk_percent": "Disk utilisation",
    "disk_read_mbps": "Disk read throughput",
    "disk_write_mbps": "Disk write throughput",
    "net_sent_mbps": "Network sent",
    "net_recv_mbps": "Network received",
    "process_count": "Active processes",
    "thread_count": "Thread count",
    "load_average": "Load average",
    "disk_free_gb": "Disk free space",
    "swap_percent": "Swap utilisation",
    "context_switch_rate": "Context switch rate",
    "handle_count": "Open handle count",
}

#: Metrics expressed as percentages (used for thresholds + formatting).
PERCENT_METRICS: Final[frozenset[str]] = frozenset(
    {"cpu_percent", "memory_percent", "disk_percent", "swap_percent"}
)

#: Units for display.
METRIC_UNITS: Final[dict[str, str]] = {
    "cpu_percent": "%",
    "memory_percent": "%",
    "disk_percent": "%",
    "swap_percent": "%",
    "disk_read_mbps": "MB/s",
    "disk_write_mbps": "MB/s",
    "net_sent_mbps": "MB/s",
    "net_recv_mbps": "MB/s",
    "process_count": "",
    "thread_count": "",
    "load_average": "",
    "disk_free_gb": "GB",
    "context_switch_rate": "/s",
    "handle_count": "",
}

#: Default alert thresholds, expressed in display units. A breach of any
#: threshold raises an anomaly with at least MEDIUM severity.
DEFAULT_THRESHOLDS: Final[dict[str, float]] = {
    "cpu_percent": 90.0,
    "memory_percent": 90.0,
    "disk_percent": 90.0,
    "swap_percent": 50.0,
    "disk_free_gb": 10.0,  # interpreted as "less than this is bad"
}

#: A device is considered offline when no telemetry arrives for this long.
DEVICE_OFFLINE_AFTER_SECONDS: Final = 90

# --------------------------------------------------------------------------- #
# ML
# --------------------------------------------------------------------------- #

#: Minimum samples required before the detector will train.
MIN_TRAIN_SAMPLES: Final = 60

#: Contamination passed to IsolationForest.
DEFAULT_CONTAMINATION: Final = 0.05

#: Names of the models in the ensemble, in ensemble order.
MODEL_REGISTRY: Final[tuple[str, ...]] = (
    "isolation_forest",
    "pca_reconstruction",
    "statistical_zscore",
)

# --------------------------------------------------------------------------- #
# RAG
# --------------------------------------------------------------------------- #

SUPPORTED_DOC_EXTENSIONS: Final[tuple[str, ...]] = (
    ".pdf",
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".json",
    ".log",
    ".yaml",
    ".yml",
    ".jsonl",
)

DEFAULT_CHUNK_SIZE: Final = 900
DEFAULT_CHUNK_OVERLAP: Final = 150
DEFAULT_TOP_K: Final = 5
EMBEDDING_DIM: Final = 384
