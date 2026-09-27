"""Anomaly detection model registry.

Three complementary, explainable detectors are combined into an ensemble:

``isolation_forest``
    Learns the shape of "normal" multi-dimensional behaviour. Good at
    catching combinations that are individually plausible but jointly odd.

``pca_reconstruction``
    Projects samples onto the principal subspace of normal behaviour and
    measures the squared reconstruction error (SPE). Gives an exact
    per-feature contribution, which is what makes the explanation concrete.

``statistical_zscore``
    Per-feature robust z-score (median / MAD). The simplest possible
    baseline; it is intentionally naive so it can act as a sanity check on
    the more powerful models.

Every detector exposes a normalised 0-1 score with a stable meaning: *0 is
inside the learned normal range, 1 is at or beyond the training maximum*.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, ClassVar, Sequence

import numpy as np

from ..constants import DEFAULT_CONTAMINATION, MODEL_REGISTRY
from ..exceptions import InsufficientDataError, ModelError
from ..logger import get_logger

log = get_logger("ml.detector")

_EPS = 1e-9


def _as_2d(matrix: Any) -> np.ndarray:
    array = np.asarray(matrix, dtype="float64")
    if array.ndim == 1:
        array = array.reshape(1, -1)
    if array.ndim != 2:
        raise ModelError(f"Expected a 2-D feature matrix, received shape {array.shape}.")
    if not np.isfinite(array).all():
        array = np.where(np.isfinite(array), array, 0.0)
    return array


def _quantile_bounds(values: np.ndarray, low: float = 2.0, high: float = 98.0) -> tuple[float, float]:
    lower = float(np.percentile(values, low))
    upper = float(np.percentile(values, high))
    if upper - lower < _EPS:
        spread = max(abs(upper) * 0.1, 1.0)
        return lower - spread, upper + spread
    return lower, upper


def _tail_anchor(values: np.ndarray, *, start: float = 97.0, end: float = 99.5) -> tuple[float, float]:
    """Anchor a 0-1 abnormality scale on the *upper tail* of the training scores.

    Stretching the score between the 2nd and 98th training percentiles (the
    obvious choice) puts a perfectly average training sample at ~0.5 and clips
    half of all normal traffic at 1.0, which makes any threshold meaningless -
    normal and anomalous rows become indistinguishable.

    Anchoring on the tail instead means "0" for the bulk of the observed
    distribution and "1" only for the extreme, so ``ROW_AGREEMENT_THRESHOLD``
    keeps its intended meaning: *this row is in the top few percent of what this
    device normally does*.
    """
    lower = float(np.percentile(values, start))
    upper = float(np.percentile(values, end))
    if upper - lower < _EPS:
        spread = max(abs(upper) * 0.1, 1.0)
        return lower - spread, upper + spread
    return lower, upper


# --------------------------------------------------------------------------- #
# Base
# --------------------------------------------------------------------------- #
class BaseDetector(abc.ABC):
    """Interface implemented by every detector in the registry."""

    name: ClassVar[str] = "base"
    requires_min_samples: ClassVar[int] = 20

    def __init__(self, **params: Any) -> None:
        self.params: dict[str, Any] = dict(params)
        self.fitted: bool = False
        self.n_features_: int = 0
        self.n_samples_: int = 0
        self.trained_at: str | None = None

    # -- contract ---------------------------------------------------------- #
    @abc.abstractmethod
    def _fit(self, matrix: np.ndarray) -> None: ...

    @abc.abstractmethod
    def _raw_score(self, matrix: np.ndarray) -> np.ndarray: ...

    @abc.abstractmethod
    def _contributions(self, matrix: np.ndarray) -> np.ndarray: ...

    @abc.abstractmethod
    def to_dict(self) -> dict[str, Any]: ...

    @classmethod
    @abc.abstractmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BaseDetector": ...

    # -- public ------------------------------------------------------------ #
    def fit(self, matrix: np.ndarray) -> "BaseDetector":
        data = _as_2d(matrix)
        if data.shape[0] < self.requires_min_samples:
            raise InsufficientDataError(
                f"{self.name} needs at least {self.requires_min_samples} samples, "
                f"received {data.shape[0]}."
            )
        self.n_features_ = int(data.shape[1])
        self.n_samples_ = int(data.shape[0])
        self._fit(data)
        self.fitted = True
        self.trained_at = datetime.now(timezone.utc).isoformat()
        return self

    def score(self, matrix: np.ndarray) -> np.ndarray:
        """Normalised 0-1 abnormality score (higher = more unusual)."""
        if not self.fitted:
            raise ModelError(f"{self.name} has not been fitted.")
        data = _as_2d(matrix)
        return np.clip(self._raw_score(data), 0.0, 1.0)

    def contributions(self, matrix: np.ndarray) -> np.ndarray:
        """Per-feature importance for each row, shaped ``(n_samples, n_features)``."""
        if not self.fitted:
            raise ModelError(f"{self.name} has not been fitted.")
        return np.abs(self._contributions(_as_2d(matrix)))

    def _base_state(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "params": self.params,
            "n_features": self.n_features_,
            "n_samples": self.n_samples_,
            "trained_at": self.trained_at,
        }

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<{type(self).__name__} fitted={self.fitted} n={self.n_samples_}>"


# --------------------------------------------------------------------------- #
# Isolation Forest
# --------------------------------------------------------------------------- #
class IsolationForestDetector(BaseDetector):
    """Tree-based isolation detector (``sklearn.ensemble.IsolationForest``)."""

    name: ClassVar[str] = "isolation_forest"
    requires_min_samples: ClassVar[int] = 30

    def __init__(self, contamination: float = DEFAULT_CONTAMINATION, n_estimators: int = 200,
                 random_state: int = 42, **params: Any) -> None:
        super().__init__(
            contamination=contamination, n_estimators=n_estimators, random_state=random_state, **params
        )
        self._model: Any | None = None
        self._low = 0.0
        self._high = 1.0
        self._centre = np.zeros(0)
        self._scale = np.ones(0)

    def _fit(self, matrix: np.ndarray) -> None:
        from sklearn.ensemble import IsolationForest

        contamination = float(np.clip(self.params.get("contamination", DEFAULT_CONTAMINATION), 1e-4, 0.5))
        model = IsolationForest(
            n_estimators=int(self.params.get("n_estimators", 200)),
            contamination=contamination,
            max_samples="auto",
            random_state=int(self.params.get("random_state", 42)),
            n_jobs=-1,
        )
        model.fit(matrix)
        self._model = model
        train_raw = -model.score_samples(matrix)
        self._low, self._high = _tail_anchor(train_raw)
        self._centre = np.median(matrix, axis=0)
        mad = np.median(np.abs(matrix - self._centre), axis=0) * 1.4826
        self._scale = np.where(mad < _EPS, 1.0, mad)

    def _raw_score(self, matrix: np.ndarray) -> np.ndarray:
        if self._model is None:  # pragma: no cover - guarded by score()
            raise ModelError("IsolationForestDetector is not fitted.")
        raw = -self._model.score_samples(matrix)
        return (raw - self._low) / max(self._high - self._low, _EPS)

    def _contributions(self, matrix: np.ndarray) -> np.ndarray:
        """Per-feature robust deviation.

        Isolation Forest has no closed-form feature attribution. This is the
        standardised distance of each feature from its training median, which
        is a faithful *description* of where the sample sits - not a Shapley
        attribution of the model's decision.
        """
        return (matrix - self._centre) / self._scale

    def to_dict(self) -> dict[str, Any]:
        from sklearn.ensemble import IsolationForest

        payload = self._base_state()
        payload.update(
            {
                "low": self._low,
                "high": self._high,
                "centre": self._centre.tolist(),
                "scale": self._scale.tolist(),
                "model": self._model,
            }
        )
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "IsolationForestDetector":
        from sklearn.ensemble import IsolationForest  # noqa: F401  (validates availability)

        instance = cls(**payload.get("params", {}))
        instance.n_features_ = int(payload.get("n_features") or 0)
        instance.n_samples_ = int(payload.get("n_samples") or 0)
        instance.trained_at = payload.get("trained_at")
        instance.fitted = True
        instance._low = float(payload.get("low") or 0.0)
        instance._high = float(payload.get("high") or 1.0)
        instance._centre = np.asarray(payload.get("centre") or [], dtype="float64")
        instance._scale = np.asarray(payload.get("scale") or [1.0], dtype="float64")
        instance._model = payload.get("model")
        return instance


# --------------------------------------------------------------------------- #
# PCA reconstruction
# --------------------------------------------------------------------------- #
class PCADetector(BaseDetector):
    """Reconstruction-error detector over the principal subspace of normal data."""

    name: ClassVar[str] = "pca_reconstruction"
    requires_min_samples: ClassVar[int] = 25

    def __init__(self, variance_target: float = 0.95, max_components: int = 12, **params: Any) -> None:
        super().__init__(variance_target=variance_target, max_components=max_components, **params)
        self._model: Any | None = None
        self._low = 0.0
        self._high = 1.0

    def _fit(self, matrix: np.ndarray) -> None:
        from sklearn.decomposition import PCA

        n_features = matrix.shape[1]
        max_components = int(min(self.params.get("max_components", 12), n_features, matrix.shape[0] - 1))
        max_components = max(1, max_components)
        model = PCA(n_components=max_components, svd_solver="full")
        model.fit(matrix)
        self._model = model
        reconstructed = model.inverse_transform(model.transform(matrix))
        spe = np.sum((matrix - reconstructed) ** 2, axis=1)
        self._low, self._high = _tail_anchor(spe)

    def _residual(self, matrix: np.ndarray) -> np.ndarray:
        if self._model is None:  # pragma: no cover
            raise ModelError("PCADetector is not fitted.")
        reconstructed = self._model.inverse_transform(self._model.transform(matrix))
        return matrix - reconstructed

    def _raw_score(self, matrix: np.ndarray) -> np.ndarray:
        spe = np.sum(self._residual(matrix) ** 2, axis=1)
        return (spe - self._low) / max(self._high - self._low, _EPS)

    def _contributions(self, matrix: np.ndarray) -> np.ndarray:
        """Exact per-feature squared reconstruction error."""
        return self._residual(matrix) ** 2

    def to_dict(self) -> dict[str, Any]:
        payload = self._base_state()
        payload.update({"low": self._low, "high": self._high, "model": self._model})
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PCADetector":
        instance = cls(**payload.get("params", {}))
        instance.n_features_ = int(payload.get("n_features") or 0)
        instance.n_samples_ = int(payload.get("n_samples") or 0)
        instance.trained_at = payload.get("trained_at")
        instance.fitted = True
        instance._low = float(payload.get("low") or 0.0)
        instance._high = float(payload.get("high") or 1.0)
        instance._model = payload.get("model")
        return instance


# --------------------------------------------------------------------------- #
# Statistical robust z-score
# --------------------------------------------------------------------------- #
class StatisticalZScoreDetector(BaseDetector):
    """Per-feature robust z-score; the transparent baseline detector."""

    name: ClassVar[str] = "statistical_zscore"
    requires_min_samples: ClassVar[int] = 20

    def __init__(self, sensitivity: float = 4.0, **params: Any) -> None:
        super().__init__(sensitivity=sensitivity, **params)
        self._centre = np.zeros(0)
        self._scale = np.ones(0)

    def _fit(self, matrix: np.ndarray) -> None:
        self._centre = np.median(matrix, axis=0)
        mad = np.median(np.abs(matrix - self._centre), axis=0) * 1.4826
        self._scale = np.where(mad < _EPS, 1.0, mad)

    def _z(self, matrix: np.ndarray) -> np.ndarray:
        return (matrix - self._centre) / self._scale

    def _raw_score(self, matrix: np.ndarray) -> np.ndarray:
        z = np.abs(self._z(matrix))
        worst = np.max(z, axis=1)
        # 1 - exp(-z/s) saturates smoothly at 1.0 and is ~0.63 at z = s.
        sensitivity = float(self.params.get("sensitivity", 4.0))
        return 1.0 - np.exp(-worst / max(sensitivity, _EPS))

    def _contributions(self, matrix: np.ndarray) -> np.ndarray:
        return self._z(matrix)

    def to_dict(self) -> dict[str, Any]:
        payload = self._base_state()
        payload.update({"centre": self._centre.tolist(), "scale": self._scale.tolist()})
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StatisticalZScoreDetector":
        instance = cls(**payload.get("params", {}))
        instance.n_features_ = int(payload.get("n_features") or 0)
        instance.n_samples_ = int(payload.get("n_samples") or 0)
        instance.trained_at = payload.get("trained_at")
        instance.fitted = True
        instance._centre = np.asarray(payload.get("centre") or [], dtype="float64")
        instance._scale = np.asarray(payload.get("scale") or [1.0], dtype="float64")
        return instance


# --------------------------------------------------------------------------- #
# Ensemble
# --------------------------------------------------------------------------- #
_REGISTRY: dict[str, type[BaseDetector]] = {
    IsolationForestDetector.name: IsolationForestDetector,
    PCADetector.name: PCADetector,
    StatisticalZScoreDetector.name: StatisticalZScoreDetector,
}

DEFAULT_WEIGHTS: dict[str, float] = {
    IsolationForestDetector.name: 0.45,
    PCADetector.name: 0.35,
    StatisticalZScoreDetector.name: 0.20,
}


@dataclass(slots=True)
class EnsembleResult:
    """Per-model scores plus the combined decision for a batch of samples."""

    scores: dict[str, np.ndarray]
    combined: np.ndarray
    consensus: np.ndarray
    contributions: np.ndarray
    active_models: list[str] = field(default_factory=list)


class EnsembleDetector(BaseDetector):
    """Weighted combination of the registered detectors."""

    name: ClassVar[str] = "ensemble"
    requires_min_samples: ClassVar[int] = 30

    def __init__(
        self,
        models: Sequence[str] = MODEL_REGISTRY,
        weights: dict[str, float] | None = None,
        contamination: float = DEFAULT_CONTAMINATION,
        **params: Any,
    ) -> None:
        resolved_weights = dict(DEFAULT_WEIGHTS)
        if weights:
            resolved_weights.update(weights)
        super().__init__(models=list(models), weights=resolved_weights, contamination=contamination, **params)
        self._members: list[BaseDetector] = []

    # -- contract ---------------------------------------------------------- #
    def _build_members(self) -> list[BaseDetector]:
        members: list[BaseDetector] = []
        for model_name in self.params.get("models", MODEL_REGISTRY):
            factory = _REGISTRY.get(model_name)
            if factory is None:
                log.warning("Unknown detector %r requested; skipping.", model_name)
                continue
            if factory is IsolationForestDetector:
                members.append(
                    factory(contamination=float(self.params.get("contamination", DEFAULT_CONTAMINATION)))
                )
            else:
                members.append(factory())
        return members

    def _fit(self, matrix: np.ndarray) -> None:
        self._members = []
        for member in self._build_members():
            try:
                member.fit(matrix)
            except (InsufficientDataError, ModelError) as exc:
                log.warning("Detector %s could not be trained: %s", member.name, exc)
                continue
            self._members.append(member)
        if not self._members:
            raise ModelError("No detector in the ensemble could be trained on this data.")

    def _raw_score(self, matrix: np.ndarray) -> np.ndarray:
        combined = np.zeros(matrix.shape[0], dtype="float64")
        total_weight = 0.0
        for member in self._members:
            weight = float(self.params.get("weights", {}).get(member.name, 1.0))
            if weight <= 0:
                continue
            try:
                combined += weight * member.score(matrix)
            except ModelError:  # pragma: no cover - defensive
                continue
            total_weight += weight
        return combined / max(total_weight, _EPS)

    def _contributions(self, matrix: np.ndarray) -> np.ndarray:
        total = np.zeros_like(matrix, dtype="float64")
        weight_sum = 0.0
        for member in self._members:
            weight = float(self.params.get("weights", {}).get(member.name, 1.0))
            if weight <= 0:
                continue
            try:
                total += weight * member.contributions(matrix)
            except ModelError:  # pragma: no cover
                continue
            weight_sum += weight
        return total / max(weight_sum, _EPS)

    # -- richer API --------------------------------------------------------- #
    def evaluate(self, matrix: np.ndarray) -> EnsembleResult:
        """Score a batch and expose the individual model opinions."""
        data = _as_2d(matrix)
        scores: dict[str, np.ndarray] = {}
        for member in self._members:
            try:
                scores[member.name] = member.score(data)
            except ModelError:  # pragma: no cover - defensive
                continue
        combined = self.score(data)
        stack = np.vstack(list(scores.values())) if scores else np.zeros((1, data.shape[0]))
        consensus = (stack > 0.5).mean(axis=0) if scores else np.zeros(data.shape[0])
        return EnsembleResult(
            scores=scores,
            combined=combined,
            consensus=consensus,
            contributions=self.contributions(data),
            active_models=[m.name for m in self._members],
        )

    @property
    def members(self) -> list[BaseDetector]:
        return list(self._members)

    def to_dict(self) -> dict[str, Any]:
        payload = self._base_state()
        payload["members"] = [member.to_dict() for member in self._members]
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EnsembleDetector":
        instance = cls(
            models=list(payload.get("params", {}).get("models", MODEL_REGISTRY)),
            weights=payload.get("params", {}).get("weights"),
            contamination=float(payload.get("params", {}).get("contamination", DEFAULT_CONTAMINATION)),
        )
        instance.n_features_ = int(payload.get("n_features") or 0)
        instance.n_samples_ = int(payload.get("n_samples") or 0)
        instance.trained_at = payload.get("trained_at")
        instance.fitted = True
        instance._members = [_detector_from_dict(m) for m in payload.get("members", [])]
        return instance


def _detector_from_dict(payload: dict[str, Any]) -> BaseDetector:
    name = payload.get("name")
    factory = _REGISTRY.get(str(name))
    if factory is None:
        raise ModelError(f"Cannot restore detector {name!r}.")
    return factory.from_dict(payload)


def build_ensemble(
    models: Sequence[str] | None = None,
    *,
    contamination: float = DEFAULT_CONTAMINATION,
    weights: dict[str, float] | None = None,
) -> EnsembleDetector:
    """Instantiate the ensemble with the requested detectors."""
    return EnsembleDetector(
        models=tuple(models or MODEL_REGISTRY),
        weights=weights,
        contamination=contamination,
    )


__all__ = [
    "BaseDetector",
    "EnsembleDetector",
    "EnsembleResult",
    "IsolationForestDetector",
    "PCADetector",
    "StatisticalZScoreDetector",
    "build_ensemble",
]
