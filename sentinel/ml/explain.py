"""Data-derived anomaly explanations.

Every sentence produced here is computed from the actual numbers that triggered
the detection: observed value, learned baseline, dispersion, ratio, per-model
opinions and any breached operational threshold. Nothing is templated fiction -
if a number is unavailable the text says so instead of inventing one.

The wording is deliberately calibrated: the platform reports *anomalous
behaviour*, never a confirmed attack, because telemetry alone cannot establish
malicious intent.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np

from ..constants import METRIC_LABELS, METRIC_UNITS, SEVERITY_CRITICAL, SEVERITY_HIGH

__all__ = [
    "CAVEAT_TEXT",
    "INVESTIGATION_HINTS",
    "build_explanation",
    "format_value",
    "metric_deviation_contributors",
    "metric_label",
    "metric_unit",
    "top_contributors",
]

CAVEAT_TEXT = (
    "Anomalous behaviour detected. Telemetry alone does not establish a cause; "
    "correlate with deployment activity, scheduled jobs and workload changes "
    "before drawing conclusions."
)

#: Metric-specific first investigative step. Keeps advice concrete and useful.
INVESTIGATION_HINTS: dict[str, str] = {
    "cpu_percent": "Inspect the top CPU consumers on the process monitor and check for a recent deployment or batch job.",
    "memory_percent": "Check for memory growth in long-running processes and confirm swap headroom.",
    "disk_percent": "Review what is consuming free space and confirm retention/backup jobs are behaving.",
    "disk_free_gb": "Free space is low; identify the largest recent growth and confirm backups can still complete.",
    "swap_percent": "Swap activity suggests memory pressure; check for a leak or an undersized memory limit.",
    "disk_read_mbps": "Correlate read throughput with database query volume and backup windows.",
    "disk_write_mbps": "Correlate write throughput with log shipping, database commits and backup jobs.",
    "net_sent_mbps": "Identify which workload is transmitting; confirm it matches expected traffic patterns.",
    "net_recv_mbps": "Identify which workload is receiving data and whether an expected service is syncing.",
    "process_count": "Compare the process count against the baseline and look for unexpected services.",
    "thread_count": "Check for thread proliferation or a workload that has grown beyond its usual shape.",
    "handle_count": "Look for handle leaks; compare with the process monitor's oldest processes.",
    "load_average": "Check whether runnable work exceeds available CPU capacity.",
    "context_switch_rate": "High context switching usually means CPU oversubscription; check load and runnable queues.",
    "temperature_c": "Check chassis/ambient conditions and fan status.",
}

_METRIC_FAMILY: dict[str, str] = {
    "cpu_percent": "compute",
    "load_average": "compute",
    "context_switch_rate": "compute",
    "memory_percent": "memory",
    "swap_percent": "memory",
    "disk_percent": "storage",
    "disk_free_gb": "storage",
    "disk_read_mbps": "storage",
    "disk_write_mbps": "storage",
    "net_sent_mbps": "network",
    "net_recv_mbps": "network",
    "process_count": "workload",
    "thread_count": "workload",
    "handle_count": "workload",
    "temperature_c": "hardware",
}


def metric_label(metric: str) -> str:
    return METRIC_LABELS.get(metric, metric.replace("_", " ").capitalize())


def metric_unit(metric: str) -> str:
    return METRIC_UNITS.get(metric, "")


def format_value(value: Any, metric: str = "", *, precision: int = 2) -> str:
    """Render a metric value with its unit, tolerating NaN/inf."""
    if value is None:
        return "unavailable"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isnan(number):
        return "unavailable"
    if math.isinf(number):
        return "unbounded"
    unit = metric_unit(metric)
    if abs(number) >= 1000:
        return f"{number:,.0f}{(' ' + unit) if unit else ''}"
    if abs(number) >= 100:
        return f"{number:.1f}{(' ' + unit) if unit else ''}"
    return f"{number:.{precision}f}{(' ' + unit) if unit else ''}"


def _direction(delta: float) -> str:
    if delta > 0:
        return "increased"
    if delta < 0:
        return "decreased"
    return "held steady"


def _factor_text(ratio: float | None) -> str:
    """Describe how far a value sits from baseline, in multiples.

    Returns an empty string when the value is close enough to baseline that a
    multiplier would contradict a subsequent "anomaly detected" sentence. The
    standard-deviation clause carries the detail in that case.
    """
    if ratio is None or not math.isfinite(ratio) or ratio <= 0:
        return ""
    if ratio >= 1.25:
        return f"{ratio:.1f}x above"
    if ratio <= 0.8:
        return f"{1 / ratio:.1f}x below"
    return ""


def top_contributors(
    contributions: np.ndarray,
    feature_names: Sequence[str],
    *,
    limit: int = 5,
    describe: bool = True,
) -> list[dict[str, Any]]:
    """Rank features by their contribution to the most recent sample.

    ``contributions`` is ``(n_samples, n_features)``; the final row is used.
    """
    from .feature_engineering import describe_feature

    array = np.asarray(contributions, dtype="float64")
    if array.ndim != 2 or array.size == 0:
        return []
    row = np.abs(array[-1])
    if not np.isfinite(row).all():
        row = np.where(np.isfinite(row), row, 0.0)
    total = float(row.sum()) or 1.0
    order = np.argsort(row)[::-1][: max(1, limit)]
    names = list(feature_names)
    results: list[dict[str, Any]] = []
    for index in order:
        if row[index] <= 0:
            continue
        feature = names[index] if index < len(names) else f"f{index}"
        results.append(
            {
                "feature": feature,
                "label": describe_feature(feature) if describe else feature,
                "score": float(row[index]),
                "share": float(row[index] / total * 100.0),
            }
        )
    return results


def metric_deviation_contributors(
    deviations: Mapping[str, Any], *, limit: int = 4
) -> list[dict[str, Any]]:
    """Rank *metrics* by absolute deviation, expressed as a share of the total.

    This is the operator-facing view of "what moved": the ``__dev`` features
    are robust z-scores in the metric's own units, so their absolute values
    are directly comparable and their shares are meaningful.
    """
    values: list[tuple[str, float]] = []
    for metric, value in deviations.items():
        try:
            number = abs(float(value))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(number) or number <= 1e-6:
            continue
        values.append((metric, number))
    if not values:
        return []
    total = sum(v for _, v in values) or 1.0
    values.sort(key=lambda item: item[1], reverse=True)
    return [
        {
            "metric": metric,
            "feature": f"{metric}__dev",
            "label": metric_label(metric),
            "score": round(score, 3),
            "share": round(score / total * 100.0, 1),
        }
        for metric, score in values[: max(1, limit)]
    ]


def build_explanation(
    *,
    metric: str,
    observed: Any,
    expected: Any,
    baseline_std: Any,
    model_scores: Mapping[str, float],
    combined_score: float,
    consensus: float,
    severity: str,
    threshold_breach: bool = False,
    threshold_ref: float | None = None,
    contributors: Sequence[Mapping[str, Any]] | None = None,
    sample_count: int = 0,
) -> tuple[str, dict[str, Any]]:
    """Compose the explanation text and a machine-readable evidence bundle."""
    label = metric_label(metric)
    evidence: dict[str, Any] = {
        "metric": metric,
        "label": label,
        "family": _METRIC_FAMILY.get(metric, "system"),
        "observed": _num(observed),
        "expected": _num(expected),
        "baseline_std": _num(baseline_std),
        "model_scores": {k: round(float(v), 4) for k, v in model_scores.items()},
        "combined_score": round(float(combined_score), 4),
        "consensus": round(float(consensus), 4),
        "severity": severity,
        "threshold_breach": bool(threshold_breach),
        "threshold_ref": _num(threshold_ref),
        "sample_count": int(sample_count),
        "generated_from": "measured telemetry + learned baseline",
    }

    observed_f = _num(observed)
    expected_f = _num(expected)
    std_f = _num(baseline_std)

    sentences: list[str] = []

    # 1. Headline: what changed, by how much.
    if observed_f is None:
        sentences.append(f"{label} could not be evaluated for this sample.")
    elif expected_f is None:
        sentences.append(
            f"{label} measured {format_value(observed_f, metric)}; no learned baseline is available yet."
        )
    else:
        delta = observed_f - expected_f
        factor = _factor_text(observed_f / expected_f if expected_f else None)
        sentence = (
            f"{label} {_direction(delta)} to {format_value(observed_f, metric)} "
            f"against a learned baseline of {format_value(expected_f, metric)}"
        )
        if factor:
            sentence += f" ({factor} baseline)"
        if std_f not in (None, 0) and not math.isnan(std_f):
            z = delta / std_f
            sentence += f", a deviation of {z:+.1f} baseline standard deviations"
        elif std_f in (None, 0) or (isinstance(std_f, float) and math.isnan(std_f)):
            sentence += "; baseline dispersion is not yet established"
        sentences.append(sentence + ".")

    # 2. Model consensus.
    agreeing = [name for name, value in model_scores.items() if float(value) > 0.5]
    if model_scores:
        if len(agreeing) == len(model_scores):
            sentences.append(
                f"All {len(model_scores)} detectors scored this sample as unusual "
                f"(combined score {combined_score:.2f}/1.00)."
            )
        elif agreeing:
            sentences.append(
                f"{len(agreeing)} of {len(model_scores)} detectors flagged this sample "
                f"({', '.join(sorted(agreeing))}); combined score {combined_score:.2f}/1.00."
            )
        else:
            sentences.append(
                f"No detector exceeded its normal range on this sample; the combined score is "
                f"{combined_score:.2f}/1.00."
            )
    else:
        sentences.append("No trained model was available; this verdict is threshold-based only.")

    # 3. Threshold context.
    if threshold_breach and threshold_ref is not None:
        comparison = "below" if metric == "disk_free_gb" else "above"
        sentences.append(
            f"This also breaches the configured operational threshold "
            f"({comparison} {format_value(threshold_ref, metric)})."
        )

    # 4. Dominant feature drivers.
    if contributors:
        top = [c for c in list(contributors)[:3] if float(c.get("score", 0)) > 0]
        if top:
            joined = ", ".join(
                f"{c.get('label', c.get('feature'))} ({float(c.get('share', 0)):.0f}% of the deviation)"
                for c in top
            )
            sentences.append(f"Largest contributors to the deviation: {joined}.")

    # 5. Data sufficiency.
    if 0 < sample_count < 60:
        sentences.append(
            f"Only {sample_count} sample(s) were available when scoring; the baseline is still forming."
        )

    # 6. Calibration and next step.
    if severity in (SEVERITY_HIGH, SEVERITY_CRITICAL):
        sentences.append(CAVEAT_TEXT)
    hint = INVESTIGATION_HINTS.get(metric)
    if hint:
        sentences.append(f"Suggested first step: {hint}")

    return " ".join(s for s in sentences if s), evidence


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) or math.isinf(number) else number
