"""Machine-learning subsystem for Sentinel AI.

An explainable, ensemble-based anomaly detection pipeline over system-health
telemetry. Every verdict is traceable to measured values and a learned baseline.
"""

from __future__ import annotations

from .anomaly_detector import (
    BaseDetector,
    EnsembleDetector,
    EnsembleResult,
    IsolationForestDetector,
    PCADetector,
    StatisticalZScoreDetector,
    build_ensemble,
)
from .explain import build_explanation, top_contributors
from .feature_engineering import FEATURE_NAMES, FeatureMatrix, build_features
from .pipeline import AnomalyPipeline, CycleResult, ModelStatus, TrainReport
from .preprocessing import Preprocessor
from .scoring import (
    AnomalyVerdict,
    DeviceRisk,
    RiskComponent,
    assess_device_risk,
    composite_risk,
    risk_from_score,
    severity_for_risk,
)

__all__ = [
    "FEATURE_NAMES",
    "AnomalyPipeline",
    "AnomalyVerdict",
    "BaseDetector",
    "CycleResult",
    "DeviceRisk",
    "EnsembleDetector",
    "EnsembleResult",
    "FeatureMatrix",
    "IsolationForestDetector",
    "ModelStatus",
    "PCADetector",
    "Preprocessor",
    "RiskComponent",
    "StatisticalZScoreDetector",
    "TrainReport",
    "assess_device_risk",
    "build_ensemble",
    "build_explanation",
    "build_features",
    "composite_risk",
    "risk_from_score",
    "severity_for_risk",
    "top_contributors",
]
