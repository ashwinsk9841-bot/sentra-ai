"""Anomaly-detection models.

Re-exports the detector registry so callers can import from a single, stable
path. Trained artifacts are written to ``<data_dir>/models`` (see
``Settings.models_dir``) and are never committed to version control.
"""

from __future__ import annotations

from ..anomaly_detector import (
    DEFAULT_WEIGHTS,
    BaseDetector,
    EnsembleDetector,
    EnsembleResult,
    IsolationForestDetector,
    PCADetector,
    StatisticalZScoreDetector,
    build_ensemble,
)

__all__ = [
    "DEFAULT_WEIGHTS",
    "BaseDetector",
    "EnsembleDetector",
    "EnsembleResult",
    "IsolationForestDetector",
    "PCADetector",
    "StatisticalZScoreDetector",
    "build_ensemble",
]
