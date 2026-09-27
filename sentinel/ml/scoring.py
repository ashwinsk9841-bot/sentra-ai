"""Risk scoring.

Converts model output into the two numbers an analyst actually acts on:

* **anomaly score** - the normalised 0-1 model output.
* **risk score** - a 0-100 operational score blending model confidence,
  cross-model consensus and hard threshold breaches.

The mapping is deliberately conservative and fully deterministic so the same
telemetry always yields the same risk, and so a score can be explained rather
than merely displayed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from ..constants import ALERT_STATUS_NEW, DEFAULT_THRESHOLDS, RISK_BANDS, SEVERITY_LOW
from ..database.repository import severity_for_risk

__all__ = [
    "AnomalyVerdict",
    "DeviceRisk",
    "RiskComponent",
    "apply_uncertainty",
    "assess_device_risk",
    "clamp",
    "composite_risk",
    "empty_verdict",
    "explain_risk",
    "risk_band_labels",
    "risk_from_score",
    "severity_for_risk",
    "threshold_breaches",
]


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


# --------------------------------------------------------------------------- #
# Anomaly verdict
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class AnomalyVerdict:
    """A single metric-level judgement produced by the detector."""

    metric: str
    observed_value: float
    expected_value: float
    baseline_std: float
    delta: float
    ratio: float | None
    model: str
    model_scores: dict[str, float]
    anomaly_score: float
    consensus: float
    risk_score: int
    severity: str
    threshold_breach: bool = False
    threshold_ref: float | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    explanation: str = ""

    def as_row(self, device_pk: str, ts: Any) -> dict[str, Any]:
        """Shape the verdict for insertion into the ``anomalies`` table."""
        return {
            "device_pk": device_pk,
            "ts": ts,
            "metric": self.metric,
            "observed_value": self.observed_value,
            "expected_value": self.expected_value,
            "baseline_std": self.baseline_std,
            "delta": self.delta,
            "ratio": self.ratio,
            "model": self.model,
            "model_scores": self.model_scores,
            "anomaly_score": self.anomaly_score,
            "risk_score": self.risk_score,
            "severity": self.severity,
            "explanation": self.explanation,
            "evidence": self.evidence,
        }

    def as_alert(self, device_pk: str, ts: Any, anomaly_id: str | None = None) -> dict[str, Any]:
        return {
            "device_pk": device_pk,
            "anomaly_id": anomaly_id,
            "ts": ts,
            "title": f"{self.severity.title()} anomaly: {self.metric.replace('_', ' ')}",
            "message": self.explanation,
            "metric": self.metric,
            "severity": self.severity,
            "risk_score": self.risk_score,
            "status": ALERT_STATUS_NEW,
        }


# --------------------------------------------------------------------------- #
# Risk mapping
# --------------------------------------------------------------------------- #
def risk_from_score(
    score: float,
    *,
    consensus: float | None = None,
    threshold_breach: bool = False,
) -> int:
    """Map a 0-1 anomaly score onto a 0-100 risk score.

    The exponent > 1 keeps mild deviations in the LOW band instead of inflating
    them, and consensus adjusts the score towards models that actually agree.
    """
    normalised = clamp(score, 0.0, 1.0)
    risk = 100.0 * (normalised**1.4)

    if consensus is not None:
        consensus = clamp(consensus, 0.0, 1.0)
        if consensus >= 0.99:
            risk *= 1.08
        elif consensus <= 0.34:
            risk *= 0.90

    if threshold_breach:
        risk = max(risk, 50.0)

    return int(round(clamp(risk)))


def composite_risk(
    model_scores: Mapping[str, float],
    *,
    consensus: float | None = None,
    threshold_breach: bool = False,
) -> tuple[int, float, float]:
    """Aggregate per-model scores into ``(risk_score, combined, consensus)``."""
    values = [clamp(v, 0.0, 1.0) for v in model_scores.values()]
    combined = float(np.mean(values)) if values else 0.0
    if consensus is None and values:
        consensus = float(np.mean([1.0 if v > 0.5 else 0.0 for v in values]))
    risk = risk_from_score(combined, consensus=consensus, threshold_breach=threshold_breach)
    return risk, combined, float(consensus if consensus is not None else 0.0)


def threshold_breaches(
    snapshot: Mapping[str, Any], thresholds: Mapping[str, float] | None = None
) -> dict[str, tuple[str, float, float]]:
    """Evaluate hard operational thresholds.

    Returns ``{metric: (direction, threshold, observed)}`` where ``direction`` is
    ``"above"`` or ``"below"``. Thresholds expressed as free space are inverted.
    """
    limits = dict(DEFAULT_THRESHOLDS)
    limits.update(thresholds or {})
    breaches: dict[str, tuple[str, float, float]] = {}
    for metric, limit in limits.items():
        value = snapshot.get(metric)
        if value is None or not np.isfinite(float(value)):
            continue
        value = float(value)
        if metric == "disk_free_gb":
            if value < float(limit):
                breaches[metric] = ("below", float(limit), value)
        elif value > float(limit):
            breaches[metric] = ("above", float(limit), value)
    return breaches


# --------------------------------------------------------------------------- #
# Device posture
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class RiskComponent:
    """One named contribution to a device risk score."""

    name: str
    label: str
    value: float
    weight: float
    detail: str = ""

    @property
    def contribution(self) -> float:
        return self.value * self.weight


@dataclass(slots=True)
class DeviceRisk:
    """Aggregated posture for a device over an analysis window."""

    risk_score: int
    severity: str
    components: list[RiskComponent] = field(default_factory=list)
    summary: str = ""
    sample_count: int = 0

    def as_row(self, device_pk: str, ts: Any, window_start: Any = None, window_end: Any = None) -> dict[str, Any]:
        return {
            "device_pk": device_pk,
            "ts": ts,
            "window_start": window_start,
            "window_end": window_end,
            "risk_score": self.risk_score,
            "severity": self.severity,
            "composite": {c.name: {"value": round(c.value, 2), "weight": c.weight} for c in self.components},
            "summary": self.summary,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "risk_score": self.risk_score,
            "severity": self.severity,
            "summary": self.summary,
            "sample_count": self.sample_count,
            "components": [
                {
                    "name": c.name,
                    "label": c.label,
                    "value": round(c.value, 2),
                    "weight": c.weight,
                    "contribution": round(c.contribution, 2),
                    "detail": c.detail,
                }
                for c in self.components
            ],
        }


_DEVICE_WEIGHTS: dict[str, float] = {
    "peak_anomaly": 0.45,
    "sustained_anomaly": 0.20,
    "error_pressure": 0.20,
    "resource_pressure": 0.15,
}


def assess_device_risk(
    *,
    anomaly_risks: Sequence[float] | pd.Series | None = None,
    logs: pd.DataFrame | None = None,
    telemetry: pd.DataFrame | None = None,
    sample_count: int = 0,
) -> DeviceRisk:
    """Blend anomaly, log-error and resource pressure into one 0-100 score."""
    components: list[RiskComponent] = []

    risks = [float(r) for r in (anomaly_risks if anomaly_risks is not None else []) if np.isfinite(float(r))]
    peak = max(risks) if risks else 0.0
    components.append(
        RiskComponent(
            name="peak_anomaly",
            label="Peak anomaly risk",
            value=clamp(peak),
            weight=_DEVICE_WEIGHTS["peak_anomaly"],
            detail=f"highest single-metric risk: {peak:.0f}/100" if risks else "no anomalies scored",
        )
    )

    if risks:
        top = sorted(risks, reverse=True)[:5]
        sustained = float(np.mean(top))
    else:
        sustained = 0.0
    components.append(
        RiskComponent(
            name="sustained_anomaly",
            label="Sustained anomaly level",
            value=clamp(sustained),
            weight=_DEVICE_WEIGHTS["sustained_anomaly"],
            detail=f"mean of top {min(5, len(risks))} anomaly risk(s)" if risks else "no anomalies scored",
        )
    )

    error_pressure, error_detail = _error_pressure(logs)
    components.append(
        RiskComponent(
            name="error_pressure",
            label="Log error pressure",
            value=error_pressure,
            weight=_DEVICE_WEIGHTS["error_pressure"],
            detail=error_detail,
        )
    )

    resource_pressure, resource_detail = _resource_pressure(telemetry)
    components.append(
        RiskComponent(
            name="resource_pressure",
            label="Resource pressure",
            value=resource_pressure,
            weight=_DEVICE_WEIGHTS["resource_pressure"],
            detail=resource_detail,
        )
    )

    total = clamp(sum(c.contribution for c in components))
    risk = int(round(total))
    return DeviceRisk(
        risk_score=risk,
        severity=severity_for_risk(risk),
        components=components,
        summary=explain_risk(risk, components),
        sample_count=sample_count,
    )


def _error_pressure(logs: pd.DataFrame | None) -> tuple[float, str]:
    """Map the ERROR/CRITICAL log rate onto 0-100."""
    if logs is None or len(logs) == 0:
        return 0.0, "no log records in window"
    if "level" not in logs.columns:
        return 0.0, "log records carry no level field"
    counts = logs["level"].astype(str).str.upper().value_counts()
    total = int(counts.sum()) or 1
    errors = int(counts.get("ERROR", 0))
    critical = int(counts.get("CRITICAL", 0))
    anomaly = int(counts.get("ANOMALY", 0))
    bad = errors + critical + anomaly
    ratio = bad / total
    # 30% error-or-worse saturates the component; 1% is negligible.
    pressure = clamp(ratio / 0.30 * 100.0)
    if critical:
        pressure = max(pressure, 45.0)
    return pressure, f"{bad}/{total} records at ERROR or above ({ratio:.1%})"


def _resource_pressure(telemetry: pd.DataFrame | None) -> tuple[float, str]:
    """Map peak CPU/RAM/DISK utilisation onto 0-100."""
    if telemetry is None or len(telemetry) == 0:
        return 0.0, "no telemetry in window"
    peaks: dict[str, float] = {}
    for column in ("cpu_percent", "memory_percent", "disk_percent", "swap_percent"):
        if column in telemetry.columns:
            series = pd.to_numeric(telemetry[column], errors="coerce").dropna()
            if len(series):
                peaks[column] = float(series.max())
    if not peaks:
        return 0.0, "no resource metrics in window"
    worst_metric, worst_value = max(peaks.items(), key=lambda kv: kv[1])
    pressure = clamp(worst_value)
    detail = ", ".join(f"{k.replace('_percent', '')} {v:.0f}%" for k, v in peaks.items())
    return pressure, f"peak {detail} (worst: {worst_metric.replace('_percent', '')})"


def explain_risk(risk: int, components: Sequence[RiskComponent]) -> str:
    """One-sentence, data-derived summary of a device risk score."""
    if not components:
        return f"Risk score {risk}/100 ({severity_for_risk(risk)})."
    ranked = sorted(components, key=lambda c: c.contribution, reverse=True)
    driver = ranked[0]
    tail = ", ".join(
        f"{c.label.lower()} {c.value:.0f}" for c in ranked[1:3] if c.value > 0
    )
    text = (
        f"Risk score {risk}/100 ({severity_for_risk(risk)}), driven mainly by "
        f"{driver.label.lower()} ({driver.value:.0f}/100)."
    )
    if tail:
        text += f" Secondary signals: {tail}."
    return text


def risk_band_labels() -> list[tuple[int, str]]:
    """``[(floor, severity), ...]`` for UI legends."""
    return list(RISK_BANDS)


def empty_verdict(metric: str, reason: str) -> AnomalyVerdict:
    """A zero-risk verdict, used when a metric cannot be evaluated."""
    return AnomalyVerdict(
        metric=metric,
        observed_value=float("nan"),
        expected_value=float("nan"),
        baseline_std=float("nan"),
        delta=float("nan"),
        ratio=None,
        model="none",
        model_scores={},
        anomaly_score=0.0,
        consensus=0.0,
        risk_score=0,
        severity=SEVERITY_LOW,
        explanation=reason,
    )


def apply_uncertainty(risk: int, *, sample_count: int, min_samples: int = 60) -> int:
    """Shrink risk slightly when the model has seen very little data.

    Prevents a freshly started detector from producing alarming verdicts off a
    handful of samples.
    """
    if sample_count >= min_samples:
        return int(risk)
    confidence = max(0.35, min(1.0, sample_count / max(1, min_samples)))
    return int(round(risk * confidence))
