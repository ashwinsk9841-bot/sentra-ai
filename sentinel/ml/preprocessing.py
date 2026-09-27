"""Preprocessing: cleaning, imputation and robust scaling.

The scaler is persisted alongside the model so inference applies exactly the
same transformation that was used at training time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.preprocessing import RobustScaler

from ..exceptions import ModelError
from .feature_engineering import FEATURE_NAMES

_EPS = 1e-9


def clean_matrix(matrix: np.ndarray) -> np.ndarray:
    """Replace non-finite values with NaN so imputation can handle them."""
    array = np.asarray(matrix, dtype="float64")
    if array.size == 0:
        return array
    return np.where(np.isfinite(array), array, np.nan)


def drop_dead_columns(matrix: np.ndarray, feature_names: tuple[str, ...]) -> tuple[np.ndarray, list[int]]:
    """Drop columns that are entirely NaN/constant in the training window."""
    if matrix.size == 0:
        return matrix, list(range(matrix.shape[1] if matrix.ndim == 2 else 0))
    keep: list[int] = []
    for index in range(matrix.shape[1]):
        column = matrix[:, index]
        finite = column[np.isfinite(column)]
        if finite.size == 0:
            continue
        if float(np.nanstd(finite)) < _EPS:
            continue
        keep.append(index)
    if not keep:
        raise ModelError(
            "Every feature column is constant or empty in the training window.",
            hint="Collect more varied telemetry, or lower MIN_TRAIN_SAMPLES.",
        )
    return matrix[:, keep], keep


@dataclass(slots=True)
class Preprocessor:
    """Median imputation + robust scaling, fitted on the training window."""

    feature_names: tuple[str, ...] = FEATURE_NAMES
    medians: np.ndarray = field(default_factory=lambda: np.full(len(FEATURE_NAMES), np.nan))
    kept_indices: list[int] = field(default_factory=list)
    centre_: np.ndarray | None = None
    scale_: np.ndarray | None = None
    fitted: bool = False

    # -- fitting ------------------------------------------------------------ #
    def fit(self, matrix: np.ndarray, feature_names: tuple[str, ...] | None = None) -> "Preprocessor":
        if feature_names is not None:
            self.feature_names = tuple(feature_names)
        data = clean_matrix(np.asarray(matrix, dtype="float64"))
        if data.ndim != 2 or data.shape[0] == 0:
            raise ModelError("Cannot fit the preprocessor on an empty matrix.")
        if data.shape[1] != len(self.feature_names):
            raise ModelError(
                f"Feature width {data.shape[1]} does not match the expected "
                f"{len(self.feature_names)} columns."
            )
        self.kept_indices, self.medians = _column_stats(data)
        reduced = data[:, self.kept_indices]
        scaler = RobustScaler(quantile_range=(25.0, 75.0), with_centering=True)
        scaler.fit(reduced)
        self.centre_ = scaler.center_.astype("float64")
        scale = scaler.scale_.astype("float64")
        # A zero IQR means a constant column; map it to zero rather than NaN.
        self.scale_ = np.where(scale < _EPS, 1.0, scale)
        self.fitted = True
        return self

    # -- transform ---------------------------------------------------------- #
    def transform(self, matrix: np.ndarray) -> np.ndarray:
        if not self.fitted:
            raise ModelError("Preprocessor used before fit().")
        data = clean_matrix(np.asarray(matrix, dtype="float64"))
        if data.ndim == 1:
            data = data.reshape(1, -1)
        if data.shape[1] != len(self.feature_names):
            raise ModelError(
                f"Expected {len(self.feature_names)} feature columns, received {data.shape[1]}."
            )
        reduced = data[:, self.kept_indices]
        # Forward/backward fill within the batch, then fall back to train medians.
        reduced = _fill_nan(reduced, self.medians[self.kept_indices])
        return (reduced - self.centre_) / self.scale_

    def fit_transform(self, matrix: np.ndarray) -> np.ndarray:
        return self.fit(matrix).transform(matrix)

    # -- persistence -------------------------------------------------------- #
    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_names": list(self.feature_names),
            "medians": self.medians.tolist(),
            "kept_indices": list(self.kept_indices),
            "centre": None if self.centre_ is None else self.centre_.tolist(),
            "scale": None if self.scale_ is None else self.scale_.tolist(),
            "fitted": self.fitted,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Preprocessor":
        instance = cls(
            feature_names=tuple(payload.get("feature_names") or FEATURE_NAMES),
            medians=np.asarray(payload.get("medians") or [], dtype="float64"),
            kept_indices=list(payload.get("kept_indices") or []),
        )
        centre = payload.get("centre")
        scale = payload.get("scale")
        instance.centre_ = np.asarray(centre, dtype="float64") if centre is not None else None
        instance.scale_ = np.asarray(scale, dtype="float64") if scale is not None else None
        instance.fitted = bool(payload.get("fitted")) and instance.centre_ is not None
        if instance.fitted and instance.medians.size != len(instance.feature_names):
            instance.medians = np.full(len(instance.feature_names), np.nan)
        return instance

    @property
    def active_feature_names(self) -> tuple[str, ...]:
        return tuple(self.feature_names[i] for i in self.kept_indices)


def _column_stats(data: np.ndarray) -> tuple[list[int], np.ndarray]:
    """Indices of usable columns plus a per-column median for imputation."""
    medians = np.full(data.shape[1], np.nan)
    keep: list[int] = []
    for index in range(data.shape[1]):
        column = data[:, index]
        finite = column[np.isfinite(column)]
        if finite.size < max(3, data.shape[0] * 0.05):
            continue
        if float(np.std(finite)) < _EPS:
            continue
        medians[index] = float(np.median(finite))
        keep.append(index)
    return keep, medians


def _fill_nan(data: np.ndarray, fallback: np.ndarray) -> np.ndarray:
    """Forward/backward fill inside the batch, then substitute the fallback."""
    frame = pd.DataFrame(data)
    frame = frame.ffill().bfill()
    if frame.isna().to_numpy().any():
        frame = frame.fillna(pd.Series(fallback[: frame.shape[1]]))
    return frame.to_numpy(dtype="float64")


__all__ = ["Preprocessor", "clean_matrix", "drop_dead_columns"]
