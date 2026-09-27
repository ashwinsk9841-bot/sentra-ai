"""Exception hierarchy for Sentinel AI.

Every failure mode the platform can encounter is represented here so that the UI
and services can degrade gracefully instead of crashing the whole dashboard.
"""

from __future__ import annotations


class SentinelError(Exception):
    """Base class for every Sentinel AI error."""


class ConfigurationError(SentinelError):
    """Raised when required configuration is missing or malformed.

    Carries a ``hint`` with the exact remediation step so the UI can show an
    actionable message rather than a traceback.
    """

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:  # pragma: no cover - trivial
        if self.hint:
            return f"{self.message} -> {self.hint}"
        return self.message


class DatabaseError(SentinelError):
    """Supabase (or the local store) is unreachable or returned an error."""


class NotConfiguredError(DatabaseError):
    """A remote dependency is required for this operation but is not configured."""


class EmbeddingError(SentinelError):
    """Embedding generation failed."""


class IngestionError(SentinelError):
    """A document could not be parsed, cleaned or chunked."""


class LLMError(SentinelError):
    """The configured LLM provider returned an error or is unreachable."""


class ModelError(SentinelError):
    """An ML model is missing, untrained or failed during inference."""


class InsufficientDataError(ModelError):
    """Not enough observations to train or score a model."""


class AgentError(SentinelError):
    """The Sentinel Agent could not complete a collection or upload cycle."""


class DeviceNotAuthorizedError(SentinelError):
    """A device attempted to report telemetry before being registered."""
