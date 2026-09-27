"""Logging for Sentinel AI.

A single rotating-file + stderr handler is attached to the ``sentinel`` logger
tree. The agent reuses the same module so that agent logs and application logs
are formatted identically and can be shipped to a central sink.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Final

_LOG_FORMAT: Final = "%(asctime)s | %(levelname)-8s | %(name)-28s | %(message)s"
_DATE_FORMAT: Final = "%Y-%m-%d %H:%M:%S"
_MAX_BYTES: Final = 2 * 1024 * 1024
_BACKUP_COUNT: Final = 3

_configured = False


class _RedactingFilter(logging.Filter):
    """Strips anything that looks like a credential out of log records."""

    _SENSITIVE_MARKERS = (
        "supabase_key",
        "service_key",
        "api_key",
        "apikey",
        "ingest_key",
        "authorization",
        "password",
        "secret",
        "token",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        if not any(marker in message.lower() for marker in self._SENSITIVE_MARKERS):
            return True
        redacted = message
        for marker in self._SENSITIVE_MARKERS:
            for sep in ("=", ":"):
                token = f"{marker}{sep}"
                while token in redacted.lower():
                    index = redacted.lower().index(token)
                    value_start = index + len(token)
                    value_start += len(redacted[value_start:]) - len(
                        redacted[value_start:].lstrip(" \"'")
                    )
                    end = value_start
                    while end < len(redacted) and redacted[end] not in " \t,;'\"":
                        end += 1
                    if end > value_start:
                        redacted = f"{redacted[:value_start]}<redacted>{redacted[end:]}"
        record.msg = redacted
        record.args = ()
        return True


def configure_logging(
    level: int | str = logging.INFO, *, log_dir: Path | None = None
) -> logging.Logger:
    """Idempotently configure and return the ``sentinel`` logger."""
    global _configured
    logger = logging.getLogger("sentinel")
    if _configured:
        logger.setLevel(level)
        return logger

    logger.setLevel(level)
    logger.propagate = False

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)
    redactor = _RedactingFilter()

    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(formatter)
    stream.addFilter(redactor)
    logger.addHandler(stream)

    if log_dir is not None:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            rotating = logging.handlers.RotatingFileHandler(
                log_dir / "sentinel.log",
                maxBytes=_MAX_BYTES,
                backupCount=_BACKUP_COUNT,
                encoding="utf-8",
            )
            rotating.setFormatter(formatter)
            rotating.addFilter(redactor)
            logger.addHandler(rotating)
        except OSError:
            logger.warning("File logging unavailable; continuing with stderr only.")

    _configured = True
    return logger


def get_logger(name: str = "sentinel") -> logging.Logger:
    """Return a namespaced child logger, configuring the tree on first use."""
    if not _configured:
        configure_logging()
    if name == "sentinel" or name.startswith("sentinel."):
        return logging.getLogger(name)
    return logging.getLogger(f"sentinel.{name}")
