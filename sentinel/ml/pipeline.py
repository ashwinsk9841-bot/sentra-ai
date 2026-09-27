"""Anomaly detection pipeline.

Orchestrates the full path from stored telemetry to persisted, explained
anomalies:

    telemetry -> feature matrix -> preprocessing -> ensemble inference
             -> per-metric verdicts -> risk + severity -> explanation
             -> anomalies / alerts / risk events in the database

Models are trained on the *history already in the database*, persisted with
joblib, and reloaded lazily. Nothing is retrained on a Streamlit rerun.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from ..config import Settings, get_settings
from ..constants import CORE_METRICS, MIN_TRAIN_SAMPLES, SEVERITY_LOW
from ..database.repository import SentinelRepository, utcnow
from ..exceptions import InsufficientDataError, ModelError
from ..logger import get_logger
from .anomaly_detector import EnsembleDetector, EnsembleResult, build_ensemble
from .explain import build_explanation, metric_deviation_contributors, top_contributors
from .feature_engineering import FEATURE_NAMES, FeatureMatrix, build_features
from .preprocessing import Preprocessor
from .scoring import (
    AnomalyVerdict,
    DeviceRisk,
    assess_device_risk,
    clamp,
    composite_risk,
    severity_for_risk,
    threshold_breaches,
)

log = get_logger("ml.pipeline")

#: A metric must be at least this abnormal on its own to be reported.
METRIC_FLAG_THRESHOLD = 0.45

#: ...and the multivariate model must agree, unless the metric is extreme.
ROW_AGREEMENT_THRESHOLD = 0.50
ROW_INDEPENDENT_THRESHOLD = 0.70

#: Refit once the training window has grown by this many samples.
RETRAIN_GROWTH = 400

#: ...or this much time has passed, whichever comes first.
RETRAIN_INTERVAL = timedelta(hours=6)

#: Sensitivity of the per-metric abnormality mapping.
METRIC_SENSITIVITY = 4.0

# How many of the newest samples a cycle is allowed to interpret. Incidents are
# rarely still rising when the operator looks, so judging only the final sample
# would miss a burst that has already peaked and decayed.
CYCLE_WINDOW_SAMPLES = 24


# --------------------------------------------------------------------------- #
# Result types
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class ModelStatus:
    """Everything the Settings / Live Monitor pages need to describe a model."""

    device_id: str
    trained: bool
    trained_at: datetime | None = None
    sample_count: int = 0
    available_samples: int = 0
    models: list[str] = field(default_factory=list)
    artifact: str | None = None
    message: str = "No model trained yet."
    last_error: str | None = None
    feature_count: int = len(FEATURE_NAMES)

    def as_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "trained": self.trained,
            "trained_at": self.trained_at.isoformat() if self.trained_at else None,
            "sample_count": self.sample_count,
            "available_samples": self.available_samples,
            "models": self.models,
            "artifact": self.artifact,
            "message": self.message,
            "last_error": self.last_error,
            "feature_count": self.feature_count,
        }


@dataclass(slots=True)
class TrainReport:
    """Outcome of a training run."""

    device_id: str
    ok: bool
    sample_count: int = 0
    feature_count: int = 0
    models: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    message: str = ""
    skipped_reason: str | None = None
    score_summary: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class CycleResult:
    """Everything one detection cycle produced."""

    device_id: str
    ts: datetime
    verdicts: list[AnomalyVerdict] = field(default_factory=list)
    risk: DeviceRisk | None = None
    trained: bool = False
    status: ModelStatus | None = None
    anomalies_persisted: int = 0
    alerts_persisted: int = 0
    row_score: float = 0.0
    model_scores: dict[str, float] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    used_thresholds_only: bool = False


# --------------------------------------------------------------------------- #
# In-memory model cache
# --------------------------------------------------------------------------- #
class _ModelCache:
    """Loads model artifacts once and revalidates against file mtime."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[float, Any]] = {}

    def get(self, path: Path) -> Any | None:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None
        with self._lock:
            entry = self._entries.get(str(path))
            if entry and entry[0] == mtime:
                return entry[1]
        payload = _read_artifact(path)
        if payload is not None:
            with self._lock:
                self._entries[str(path)] = (mtime, payload)
        return payload

    def put(self, path: Path, payload: Any) -> None:
        with self._lock:
            self._entries[str(path)] = (0.0, payload)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_MODEL_CACHE = _ModelCache()


def _read_artifact(path: Path) -> Any | None:
    try:
        import joblib

        return joblib.load(path)
    except Exception as exc:
        log.warning("Could not load model artifact %s: %s", path.name, exc)
        return None


def _write_artifact(path: Path, payload: Any) -> None:
    import joblib

    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    joblib.dump(payload, temp, compress=3)
    temp.replace(path)


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
class AnomalyPipeline:
    """Train, score and persist anomaly verdicts for a device."""

    def __init__(
        self,
        repository: SentinelRepository,
        settings: Settings | None = None,
        *,
        models: Sequence[str] | None = None,
        thresholds: Mapping[str, float] | None = None,
    ) -> None:
        self.repo = repository
        self.settings = settings or get_settings()
        self.model_names = tuple(models) if models else None
        self.thresholds = dict(thresholds or {})

    # -- paths ------------------------------------------------------------- #
    def artifact_path(self, device_id: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in device_id)
        return self.settings.models_dir / f"{safe}.anomaly.joblib"

    # -- data -------------------------------------------------------------- #
    def load_history(
        self, device_id: str, *, limit: int | None = None
    ) -> tuple[FeatureMatrix, pd.DataFrame]:
        """Fetch and engineer the telemetry history for a device."""
        raw = self.repo.fetch_system_metrics(
            device_id=device_id,
            limit=limit or self.settings.history_window,
            newest_first=True,
        )
        if raw.empty:
            raw = self.repo.fetch_system_metrics(device_id=device_id, limit=1)
        if not raw.empty:
            raw = raw.sort_values("ts", kind="stable").reset_index(drop=True)
        return build_features(raw), raw

    # -- training ----------------------------------------------------------- #
    def status(self, device_id: str) -> ModelStatus:
        path = self.artifact_path(device_id)
        payload = _MODEL_CACHE.get(path)
        available = 0
        try:
            available = int(len(self.repo.fetch_system_metrics(device_id=device_id, limit=1, newest_first=True)))
        except Exception:
            available = 0
        if not payload:
            try:
                available = int(
                    len(self.repo.fetch_system_metrics(device_id=device_id, limit=self.settings.history_window))
                )
            except Exception:
                pass

        if not payload:
            return ModelStatus(
                device_id=device_id,
                trained=False,
                available_samples=available,
                message=(
                    f"No model artifact yet. {available} telemetry sample(s) stored; "
                    f"{self.settings.min_train_samples} are required to train."
                ),
            )
        ensemble: EnsembleDetector = payload["ensemble"]
        return ModelStatus(
            device_id=device_id,
            trained=True,
            trained_at=_parse(payload.get("trained_at")),
            sample_count=int(payload.get("n_samples") or 0),
            available_samples=available,
            models=[m.name for m in ensemble.members],
            artifact=str(path),
            message=(
                f"Ensemble trained on {payload.get('n_samples')} samples "
                f"({payload.get('feature_count')} features) at "
                f"{_format_dt(payload.get('trained_at'))}."
            ),
        )

    def needs_training(self, device_id: str, available_samples: int) -> tuple[bool, str]:
        """Decide whether a retrain is warranted, with a human-readable reason."""
        if available_samples < self.settings.min_train_samples:
            return False, (
                f"only {available_samples}/{self.settings.min_train_samples} samples collected"
            )
        payload = _MODEL_CACHE.get(self.artifact_path(device_id))
        if payload is None:
            return True, "no trained model found"
        trained_at = _parse(payload.get("trained_at"))
        if trained_at is None:
            return True, "model has no training timestamp"
        if datetime.now(timezone.utc) - trained_at > RETRAIN_INTERVAL:
            return True, f"model is older than {RETRAIN_INTERVAL}"
        trained_on = int(payload.get("n_samples") or 0)
        if available_samples - trained_on >= RETRAIN_GROWTH:
            return True, f"{available_samples - trained_on} new samples since last fit"
        return False, "model is current"

    def train(self, device_id: str, *, force: bool = False) -> TrainReport:
        """Fit the ensemble on stored telemetry and persist the artifact."""
        import time

        started = time.perf_counter()
        features, raw = self.load_history(device_id)
        sample_count = 0 if features.empty else int(len(features.frame))

        if sample_count < self.settings.min_train_samples:
            return TrainReport(
                device_id=device_id,
                ok=False,
                sample_count=sample_count,
                skipped_reason=(
                    f"Need {self.settings.min_train_samples} samples, have {sample_count}. "
                    "Keep monitoring running, or enable Demo Mode to generate synthetic telemetry."
                ),
                message="Training skipped: insufficient data.",
            )

        should, reason = self.needs_training(device_id, sample_count)
        if not should and not force:
            return TrainReport(
                device_id=device_id,
                ok=True,
                sample_count=sample_count,
                feature_count=len(features.frame.columns),
                skipped_reason=reason,
                message=f"Reused existing model ({reason}).",
            )

        try:
            preprocessor = Preprocessor().fit(features.vectors(), features.frame.columns)
            matrix = preprocessor.transform(features.vectors())
            ensemble = build_ensemble(
                self.model_names,
                contamination=self.settings.contamination,
            ).fit(matrix)
        except (ModelError, InsufficientDataError) as exc:
            log.warning("Training failed for %s: %s", device_id, exc)
            return TrainReport(
                device_id=device_id,
                ok=False,
                sample_count=sample_count,
                message=f"Training failed: {exc}",
            )

        calibration = self.evaluate(ensemble, preprocessor, features)
        payload = {
            "version": 1,
            "device_id": device_id,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "n_samples": sample_count,
            "feature_count": int(features.frame.shape[1]),
            "preprocessor": preprocessor.to_dict(),
            "ensemble": ensemble,
            "calibration": calibration,
            "raw_baseline": _raw_baseline(features.raw),
        }
        path = self.artifact_path(device_id)
        try:
            _write_artifact(path, payload)
            _MODEL_CACHE.put(path, payload)
        except Exception as exc:
            log.error("Could not persist model for %s: %s", device_id, exc)
            return TrainReport(
                device_id=device_id,
                ok=False,
                sample_count=sample_count,
                message=f"Model trained but could not be saved: {exc}",
            )

        return TrainReport(
            device_id=device_id,
            ok=True,
            sample_count=sample_count,
            feature_count=int(features.frame.shape[1]),
            models=[m.name for m in ensemble.members],
            duration_ms=(time.perf_counter() - started) * 1000,
            message=f"Trained {len(ensemble.members)} detector(s) on {sample_count} samples ({reason}).",
            score_summary=calibration,
        )

    # -- scoring ------------------------------------------------------------ #
    def evaluate(
        self, ensemble: EnsembleDetector, preprocessor: Preprocessor, features: FeatureMatrix
    ) -> dict[str, float]:
        """Summarise how the freshly trained ensemble scores its own training set."""
        try:
            matrix = preprocessor.transform(features.vectors())
            result = ensemble.evaluate(matrix)
            return {
                "train_combined_mean": round(float(np.mean(result.combined)), 4),
                "train_combined_p95": round(float(np.percentile(result.combined, 95)), 4),
                "train_flagged_pct": round(float((result.combined > ROW_AGREEMENT_THRESHOLD).mean() * 100), 3),
                "train_consensus_mean": round(float(np.mean(result.consensus)), 4),
            }
        except Exception as exc:  # pragma: no cover - diagnostics only
            log.debug("Calibration summary unavailable: %s", exc)
            return {}

    def score_frame(
        self,
        device_id: str,
        features: FeatureMatrix,
        *,
        raw: pd.DataFrame | None = None,
    ) -> tuple[pd.DataFrame, EnsembleResult | None, Preprocessor | None, EnsembleDetector | None]:
        """Score every row of the feature matrix.

        Returns a long-format frame with one row per (timestamp, base metric)
        carrying its abnormality score, plus the raw ensemble evaluation.
        Observed and expected values are reported in the metric's original
        units, never in the log-transformed space used internally.
        """
        if features.empty:
            return pd.DataFrame(), None, None, None

        payload = _MODEL_CACHE.get(self.artifact_path(device_id))
        if payload is None:
            return pd.DataFrame(), None, None, None
        preprocessor = Preprocessor.from_dict(payload["preprocessor"])
        ensemble: EnsembleDetector = payload["ensemble"]
        # Explanations must quote the baseline the *model* learned, not the
        # rolling one: during a sustained incident a rolling median chases the
        # anomaly upwards, which would report "95% against a baseline of 89%"
        # and hide the very thing the operator needs to see.
        raw_baseline = payload.get("raw_baseline") or {}

        matrix = preprocessor.transform(features.vectors())
        result = ensemble.evaluate(matrix)

        # ``raw`` is accepted for API symmetry, but the timestamp-indexed frames
        # inside FeatureMatrix are authoritative: the caller's frame is usually
        # still carrying a positional index.
        raw_frame = _ts_indexed(features.raw, raw)
        report_baseline = features.report_baseline

        model_score_columns = {
            name: values for name, values in result.scores.items()
        }
        records: list[dict[str, Any]] = []
        for row_index, ts in enumerate(features.timestamps):
            raw_row = raw_frame.loc[ts] if ts in raw_frame.index else None
            base_row = report_baseline.loc[ts] if ts in report_baseline.index else None
            for metric in CORE_METRICS:
                dev_feature = f"{metric}__dev"
                if dev_feature not in features.frame.columns:
                    continue
                dev = float(features.frame.iloc[row_index][dev_feature])
                metric_score = float(1.0 - np.exp(-abs(dev) / METRIC_SENSITIVITY))
                observed = _safe(raw_row, metric)
                expected = _float_or_none(raw_baseline.get(f"{metric}__median"))
                std_mad = _float_or_none(raw_baseline.get(f"{metric}__mad"))
                if expected is None and base_row is not None:
                    expected = _safe(base_row, metric)
                if std_mad is None and base_row is not None:
                    std_mad = _safe(base_row, f"{metric}__mad")
                records.append(
                    {
                        "ts": ts,
                        "metric": metric,
                        "deviation": dev,
                        "metric_score": metric_score,
                        "observed": observed,
                        "expected": expected,
                        "baseline_std": None if std_mad is None else float(std_mad) * 1.4826,
                        "row_score": float(result.combined[row_index]),
                        "consensus": float(result.consensus[row_index]),
                        **{
                            f"score__{name}": float(values[row_index])
                            for name, values in model_score_columns.items()
                        },
                    }
                )
        return pd.DataFrame(records), result, preprocessor, ensemble

    def build_verdicts(
        self,
        scores: pd.DataFrame,
        *,
        ensemble: EnsembleDetector | None,
        preprocessor: Preprocessor | None,
        features: FeatureMatrix,
        thresholds: Mapping[str, float] | None = None,
        min_score: float = 0.05,
        target_ts: Any = None,
    ) -> list[AnomalyVerdict]:
        """Turn per-metric scores into explained, severity-tagged verdicts.

        ``target_ts`` selects which timestamp to interpret; the newest sample
        is used when omitted.
        """
        if scores.empty:
            return []

        limits = dict(thresholds or self.thresholds)
        target_ts = pd.Timestamp(target_ts) if target_ts is not None else scores["ts"].max()
        latest = scores[scores["ts"] == target_ts]
        if latest.empty:
            return []
        model_score_columns = [c for c in latest.columns if c.startswith("score__")]
        # Contributors are ranked in raw-metric space: the `deviation` column is
        # a robust z-score per metric, so shares are directly interpretable.
        contributors = metric_deviation_contributors(
            dict(zip(latest["metric"].astype(str), latest["deviation"].astype(float)))
        )

        verdicts: list[AnomalyVerdict] = []
        for _, row in latest.iterrows():
            metric = str(row["metric"])
            metric_score = float(row["metric_score"])
            row_score = float(row["row_score"])
            consensus = float(row["consensus"])
            model_scores = {
                col.removeprefix("score__"): float(row[col]) for col in model_score_columns
            }

            breaches = threshold_breaches(
                {metric: row.get("observed")}, limits
            )
            breach = metric in breaches
            _, _, threshold_ref = breaches.get(metric, ("", None, None))

            flagged = (
                metric_score >= METRIC_FLAG_THRESHOLD
                and (row_score >= ROW_AGREEMENT_THRESHOLD or metric_score >= ROW_INDEPENDENT_THRESHOLD)
            ) or breach
            if not flagged or metric_score < min_score and not breach:
                continue

            observed = _float_or_none(row.get("observed"))
            expected = _float_or_none(row.get("expected"))
            std = _float_or_none(row.get("baseline_std"))
            ratio = None
            if observed is not None and expected not in (None, 0):
                ratio = observed / expected
            delta = None
            if observed is not None and expected is not None:
                delta = observed - expected

            blended = clamp(0.65 * metric_score + 0.35 * row_score)
            risk, combined, consensus_value = composite_risk(
                {**model_scores, "metric_deviation": metric_score},
                consensus=consensus,
                threshold_breach=breach,
            )
            severity = severity_for_risk(risk)
            explanation, evidence = build_explanation(
                metric=metric,
                observed=observed,
                expected=expected,
                baseline_std=std,
                model_scores=model_scores,
                combined_score=combined,
                consensus=consensus_value,
                severity=severity,
                threshold_breach=breach,
                threshold_ref=threshold_ref,
                contributors=contributors,
                sample_count=int(payload_samples(features)),
            )
            evidence["metric_score"] = round(metric_score, 4)
            evidence["row_score"] = round(row_score, 4)
            evidence["delta"] = delta
            evidence["ratio"] = ratio
            evidence["contributors"] = contributors
            verdicts.append(
                AnomalyVerdict(
                    metric=metric,
                    observed_value=observed if observed is not None else float("nan"),
                    expected_value=expected if expected is not None else float("nan"),
                    baseline_std=std if std is not None else float("nan"),
                    delta=delta if delta is not None else float("nan"),
                    ratio=ratio,
                    model="+".join(sorted(model_scores)) or "threshold",
                    model_scores={k: round(v, 4) for k, v in model_scores.items()},
                    anomaly_score=combined,
                    consensus=consensus_value,
                    risk_score=risk,
                    severity=severity,
                    threshold_breach=breach,
                    threshold_ref=threshold_ref,
                    evidence=evidence,
                    explanation=explanation,
                )
            )

        verdicts.sort(key=lambda v: (v.risk_score, v.anomaly_score), reverse=True)
        return verdicts

    # -- cycle --------------------------------------------------------------- #
    def _contributors(
        self,
        ensemble: EnsembleDetector | None,
        preprocessor: Preprocessor | None,
        features: FeatureMatrix,
        target_ts: Any,
    ) -> list[dict[str, Any]]:
        """Feature-level deviation ranking for the sample at ``target_ts``."""
        if ensemble is None or preprocessor is None or features.empty:
            return []
        positions = features.timestamps.get_indexer([pd.Timestamp(target_ts)])[0]
        if positions < 0:
            return []
        vector = features.frame.iloc[positions].to_numpy(dtype="float64").reshape(1, -1)
        try:
            matrix = preprocessor.transform(vector)
            contributions = ensemble.contributions(matrix)[0]
        except ModelError:
            return []
        return top_contributors(
            np.vstack([contributions]), preprocessor.active_feature_names, limit=6
        )

    def scan_history(
        self,
        device_id: str,
        *,
        thresholds: Mapping[str, float] | None = None,
        min_risk: int = 0,
        max_findings: int = 400,
    ) -> list[tuple[Any, AnomalyVerdict]]:
        """Score the whole stored window and return the notable findings.

        Used to backfill history (Demo Mode seeding, or a first analysis after
        telemetry has been collecting while the model was untrained).
        """
        features, raw = self.load_history(device_id)
        scores, _, preprocessor, ensemble = self.score_frame(device_id, features, raw=raw)
        if scores.empty:
            return []
        findings: list[tuple[Any, AnomalyVerdict]] = []
        for ts in scores["ts"].drop_duplicates().sort_values(ascending=False):
            verdicts = self.build_verdicts(
                scores,
                ensemble=ensemble,
                preprocessor=preprocessor,
                features=features,
                thresholds=thresholds,
                target_ts=ts,
            )
            for verdict in verdicts:
                if verdict.risk_score >= min_risk:
                    findings.append((ts, verdict))
            if len(findings) >= max_findings:
                break
        return findings[:max_findings]

    def run_cycle(
        self,
        device_id: str,
        *,
        train: bool = True,
        persist: bool = True,
    ) -> CycleResult:
        """Train if needed, score the newest sample and persist the outcome."""
        errors: list[str] = []
        ts = utcnow()
        device_pk = None
        try:
            device_pk = self.repo.resolve_device_pk(device_id)
        except Exception as exc:
            errors.append(f"Device lookup failed: {exc}")
        if not device_pk:
            return CycleResult(
                device_id=device_id,
                ts=ts,
                errors=errors or [f"Device {device_id} is not registered."],
                status=self.status(device_id),
            )

        features, raw = self.load_history(device_id)
        available = 0 if features.empty else int(len(features.frame))

        trained = False
        if train and available >= self.settings.min_train_samples:
            report = self.train(device_id)
            trained = report.ok and not report.skipped_reason
            if not report.ok and report.message:
                errors.append(report.message)
        elif train:
            errors.append(
                f"Model not trained: {available}/{self.settings.min_train_samples} samples available."
            )

        scores, _, preprocessor, ensemble = self.score_frame(device_id, features, raw=raw)
        findings: list[tuple[Any, AnomalyVerdict]] = []
        if not scores.empty:
            recent = list(scores["ts"].drop_duplicates().sort_values(ascending=False))
            for sample_ts in recent[: max(1, CYCLE_WINDOW_SAMPLES)]:
                for verdict in self.build_verdicts(
                    scores,
                    ensemble=ensemble,
                    preprocessor=preprocessor,
                    features=features,
                    target_ts=sample_ts,
                ):
                    findings.append((sample_ts, verdict))
            findings.sort(key=lambda pair: (pair[1].risk_score, pair[1].anomaly_score), reverse=True)
        else:
            errors.append(
                "No trained model available; anomaly detection is inactive. "
                "Collect more telemetry or run Demo Mode."
            )
        verdicts = [verdict for _sample_ts, verdict in findings]

        recent_logs = self._recent_logs(device_id, ts - timedelta(hours=1))
        risk = assess_device_risk(
            anomaly_risks=[v.risk_score for v in verdicts],
            logs=recent_logs,
            telemetry=raw.tail(60) if not raw.empty else None,
            sample_count=available,
        )

        anomalies_persisted = 0
        alerts_persisted = 0
        threshold = self.settings.alert_risk_threshold

        if persist:
            try:
                fresh = self._unseen(device_id, findings)
                if fresh:
                    rows = [verdict.as_row(device_pk, sample_ts) for sample_ts, verdict in fresh]
                    ids = self.repo.insert_anomalies(rows)
                    anomalies_persisted = len(ids)
                    # ``ids`` is index-aligned with ``fresh``, so the alert must
                    # be matched by position - filtering first and then zipping
                    # would pair an alert with the wrong anomaly.
                    alert_rows = [
                        verdict.as_alert(device_pk, sample_ts, anomaly_id)
                        for index, (sample_ts, verdict) in enumerate(fresh)
                        if (anomaly_id := _id_at(ids, index))
                        and verdict.risk_score >= threshold
                    ]
                    if alert_rows:
                        alerts_persisted = self.repo.insert_alerts(alert_rows)
                self.repo.insert_risk_events(
                    [risk.as_row(device_pk, ts, window_start=ts - timedelta(hours=1), window_end=ts)]
                )
                self.repo.touch_device(
                    device_id,
                    risk_score=risk.risk_score,
                    cpu_percent=_safe_raw(raw, "cpu_percent"),
                    memory_percent=_safe_raw(raw, "memory_percent"),
                    disk_percent=_safe_raw(raw, "disk_percent"),
                )
            except Exception as exc:
                errors.append(f"Could not persist results: {exc}")

        return CycleResult(
            device_id=device_id,
            ts=ts,
            verdicts=verdicts,
            risk=risk,
            trained=trained,
            status=self.status(device_id),
            anomalies_persisted=anomalies_persisted,
            alerts_persisted=alerts_persisted,
            row_score=float(scores["row_score"].iloc[-1]) if not scores.empty else 0.0,
            model_scores={
                c.removeprefix("score__"): float(scores[c].iloc[-1])
                for c in scores.columns
                if c.startswith("score__")
            }
            if not scores.empty
            else {},
            errors=errors,
            used_thresholds_only=ensemble is None,
        )

    def _unseen(
        self, device_id: str, findings: Sequence[tuple[Any, AnomalyVerdict]]
    ) -> list[tuple[Any, AnomalyVerdict]]:
        """Drop findings already recorded for the same (sample, metric).

        A cycle re-interprets a sliding window, so without this every cycle
        would append a fresh copy of the same incident to the anomaly table and
        the history would fill with duplicates of one event.
        """
        if not findings:
            return []
        try:
            history = self.repo.fetch_anomalies(device_id=device_id, limit=1000)
        except Exception as exc:
            log.debug("Could not read anomaly history for dedupe: %s", exc)
            return list(findings)
        if history.empty:
            return list(findings)

        known: set[tuple[str, str]] = set()
        if "metric" in history.columns and "ts" in history.columns:
            for record in history.to_dict("records"):
                known.add((str(record.get("metric")), _format_dt(record.get("ts"))))

        fresh: list[tuple[Any, AnomalyVerdict]] = []
        for sample_ts, verdict in findings:
            key = (verdict.metric, _format_dt(sample_ts))
            if key in known:
                continue
            known.add(key)
            fresh.append((sample_ts, verdict))
        return fresh

    def _recent_logs(self, device_id: str, since: datetime) -> pd.DataFrame:
        try:
            return self.repo.fetch_logs(device_id=device_id, since=since, limit=2000)
        except Exception:
            return pd.DataFrame()

    # -- maintenance ---------------------------------------------------------- #
    def clear_model(self, device_id: str) -> bool:
        path = self.artifact_path(device_id)
        _MODEL_CACHE.clear()
        try:
            path.unlink()
            return True
        except OSError:
            return False

    def clear_cache(self) -> None:
        _MODEL_CACHE.clear()


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _ts_indexed(primary: pd.DataFrame, fallback: pd.DataFrame | None) -> pd.DataFrame:
    """Return a timestamp-indexed frame, preferring ``primary``.

    Callers frequently hold the raw SQL result, which carries a positional
    index. Looking values up by timestamp would silently yield NaN, so the
    engineered (timestamp-indexed) frame is always preferred.
    """
    if primary is not None and isinstance(primary.index, pd.DatetimeIndex) and not primary.empty:
        return primary
    if fallback is not None and isinstance(fallback.index, pd.DatetimeIndex) and not fallback.empty:
        return fallback
    return primary if primary is not None else pd.DataFrame()


def _safe(row: Any, column: str) -> float | None:
    if row is None or column not in getattr(row, "index", []):
        return None
    try:
        value = float(row[column])
    except (TypeError, ValueError):
        return None
    if not np.isfinite(value):
        return None
    return value


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _raw_baseline(raw: pd.DataFrame) -> dict[str, float]:
    """Median and MAD of each raw metric over the training window.

    Stored in the model artifact so explanations can quote the same baseline
    the detectors were fitted on.
    """
    if raw is None or raw.empty:
        return {}
    baseline: dict[str, float] = {}
    for metric in CORE_METRICS:
        if metric not in raw.columns:
            continue
        series = pd.to_numeric(raw[metric], errors="coerce").dropna()
        if series.empty:
            continue
        median = float(series.median())
        mad = float((series - median).abs().median() * 1.4826)
        baseline[f"{metric}__median"] = round(median, 6)
        baseline[f"{metric}__mad"] = round(mad, 6)
    return baseline


def _id_at(ids: Sequence[str | None], index: int) -> str | None:
    """Defensive positional lookup for a returned id list."""
    if index < 0 or index >= len(ids):
        return None
    return ids[index]


def _safe_raw(raw: pd.DataFrame, column: str) -> float | None:
    if raw is None or raw.empty or column not in raw.columns:
        return None
    return _float_or_none(raw[column].iloc[-1])


def payload_samples(features: FeatureMatrix) -> int:
    return 0 if features.empty else int(len(features.frame))


def _parse(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _format_dt(value: Any) -> str:
    parsed = _parse(value)
    return parsed.strftime("%Y-%m-%d %H:%M UTC") if parsed else "unknown"


def severity_summary(severities: Sequence[str]) -> str:
    """Human-readable severity tally, worst first."""
    order = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
    parts = [f"{count} {name}" for name in order if (count := severities.count(name))]
    return ", ".join(parts) if parts else f"none ({SEVERITY_LOW} band)"


def risk_label(risk: int) -> str:
    return severity_for_risk(risk)


def model_cache_stats() -> dict[str, int]:
    """Diagnostics for the Settings page."""
    return {"cached_models": len(_MODEL_CACHE._entries)}


__all__ = [
    "AnomalyPipeline",
    "CycleResult",
    "METRIC_FLAG_THRESHOLD",
    "ModelStatus",
    "ROW_AGREEMENT_THRESHOLD",
    "TrainReport",
    "severity_summary",
]
