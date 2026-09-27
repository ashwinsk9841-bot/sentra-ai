"""Bounded log tailing for explicitly configured files.

Design constraints:

* A file is only ever read if the operator listed it in the agent
  configuration. There is no directory walking and no glob discovery.
* Reading is line-oriented and bounded per cycle (``max_lines``).
* State is a byte offset, so a restart re-reads at most a bounded tail.
* Messages are passed through :func:`redact` before they leave the host, which
  masks anything that looks like a credential.

This is log monitoring of the operator's own systems - it never opens
keystroke, clipboard or browser stores.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from ..logger import get_logger

log = get_logger("agent.log_tail")

__all__ = ["LogTailer", "LogTarget", "TailedLine", "redact"]

#: Patterns masked before a message is transmitted.
_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]{8,}", ), r"\1 [REDACTED]"),
    (re.compile(r"(?i)\b(authorization)\s*[:=]\s*\S+"), r"\1=[REDACTED]"),
    (re.compile(r"(?i)\b(api[_-]?key|apikey|secret|token|password|passwd|pwd)\b(\s*[:=]\s*)\S+"), r"\1\2[REDACTED]"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{4,}"), "[REDACTED_JWT]"),
    (re.compile(r"\b(sk|pk|rk)-[A-Za-z0-9_\-]{12,}\b"), "[REDACTED_KEY]"),
    (re.compile(r"-----BEGIN[A-Z ]*PRIVATE KEY-----[\s\S]*?-----END[A-Z ]*PRIVATE KEY-----"), "[REDACTED_PRIVATE_KEY]"),
)

_LEVEL = re.compile(r"\b(TRACE|DEBUG|INFO|NOTICE|WARN|WARNING|ERROR|ERR|FATAL|CRITICAL|CRIT)\b", re.IGNORECASE)

_LEVEL_MAP = {
    "TRACE": "INFO",
    "DEBUG": "INFO",
    "INFO": "INFO",
    "NOTICE": "INFO",
    "WARN": "WARNING",
    "WARNING": "WARNING",
    "ERROR": "ERROR",
    "ERR": "ERROR",
    "FATAL": "CRITICAL",
    "CRIT": "CRITICAL",
    "CRITICAL": "CRITICAL",
}


def redact(message: str) -> str:
    """Mask credential-looking substrings. Applied to every shipped message."""
    if not message:
        return message
    out = message
    for pattern, replacement in _SECRET_PATTERNS:
        out = pattern.sub(replacement, out)
    return out


def _level_of(message: str, default: str = "INFO") -> str:
    match = _LEVEL.search(message)
    if not match:
        return default
    return _LEVEL_MAP.get(match.group(1).upper(), default)


@dataclass(slots=True)
class TailedLine:
    """One log line ready to be shipped."""

    ts: str
    source: str
    level: str
    message: str
    logger_name: str | None = None
    module: str | None = None
    line_no: int | None = None
    fingerprint: str = ""
    occurrences: int = 1
    attributes: dict[str, Any] = field(default_factory=dict)

    def as_row(self, device_pk: str) -> dict[str, Any]:
        return {
            "device_pk": device_pk,
            "ts": self.ts,
            "source": self.source,
            "level": self.level,
            "message": self.message,
            "logger_name": self.logger_name,
            "module": self.module,
            "line_no": self.line_no,
            "fingerprint": self.fingerprint,
            "occurrences": self.occurrences,
            "attributes": self.attributes,
        }


@dataclass(slots=True)
class LogTarget:
    """One operator-configured log file."""

    path: str
    source: str
    level: str = "INFO"
    max_lines: int = 200

    def resolved(self) -> Path:
        return Path(self.path).expanduser()


class LogTailer:
    """Follows the configured files and yields redacted, fingerprinted lines."""

    def __init__(self, targets: Sequence[LogTarget], *, from_end: bool = True) -> None:
        self.targets = list(targets)
        self.from_end = from_end
        self._offsets: dict[str, int] = {}
        self._fingerprints: dict[str, int] = {}

    # -- helpers ------------------------------------------------------------ #
    def usable_targets(self) -> list[LogTarget]:
        """Targets that exist and are readable right now."""
        ready: list[LogTarget] = []
        for target in self.targets:
            path = target.resolved()
            try:
                if path.is_file():
                    ready.append(target)
                else:
                    log.debug("Log target not available yet: %s", path)
            except OSError as exc:
                log.warning("Cannot inspect log target %s: %s", path, exc)
        return ready

    def _initial_offset(self, path: Path) -> int:
        if self.from_end:
            try:
                return path.stat().st_size
            except OSError:
                return 0
        return 0

    # -- reading ------------------------------------------------------------ #
    def poll(self) -> list[TailedLine]:
        """Read new lines from every configured file."""
        lines: list[TailedLine] = []
        for target in self.usable_targets():
            lines.extend(self._read(target))
        return lines

    def _read(self, target: LogTarget) -> list[TailedLine]:
        path = target.resolved()
        key = str(path)
        try:
            size = path.stat().st_size
        except OSError:
            return []

        offset = self._offsets.get(key)
        if offset is None:
            offset = self._initial_offset(path)
        if size < offset:  # truncated or rotated
            offset = 0
        if size == offset:
            return []

        out: list[TailedLine] = []
        budget = max(1, int(target.max_lines))
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(offset)
                for raw in handle:
                    if not raw.strip():
                        offset = handle.tell()
                        continue
                    text = redact(raw.rstrip("\n"))[:2000]
                    level = _level_of(text, target.level)
                    fingerprint = hashlib.sha1(
                        f"{level}|{target.source}|{_normalise(text)}".encode()
                    ).hexdigest()[:16]
                    out.append(
                        TailedLine(
                            ts=_now_iso(),
                            source=target.source,
                            level=level,
                            message=text,
                            logger_name=f"{target.source}.tailer",
                            module=target.source,
                            fingerprint=fingerprint,
                            attributes={"file": path.name},
                        )
                    )
                    offset = handle.tell()
                    if len(out) >= budget:
                        break
        except OSError as exc:
            log.warning("Could not read %s: %s", path, exc)
            return out

        self._offsets[key] = offset
        return out

    def status(self) -> list[dict[str, Any]]:
        """Per-target health for the Agent Console."""
        report: list[dict[str, Any]] = []
        for target in self.targets:
            path = target.resolved()
            exists = path.is_file()
            report.append(
                {
                    "source": target.source,
                    "path": str(path),
                    "exists": exists,
                    "offset": self._offsets.get(str(path), 0),
                    "size_bytes": path.stat().st_size if exists else 0,
                    "min_level": target.level,
                }
            )
        return report


def _normalise(message: str) -> str:
    """Collapse numbers/ids so repeated messages share a fingerprint."""
    return re.sub(r"\d+", "#", message).strip().lower()[:160]


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def targets_from_env(raw: Iterable[str]) -> list[LogTarget]:
    """Parse ``source=/path/to/file.log`` entries."""
    parsed: list[LogTarget] = []
    for item in raw:
        if "=" in item:
            source, _, path = item.partition("=")
        else:
            source, path = Path(item).stem, item
        if source and path:
            parsed.append(LogTarget(path=path.strip(), source=source.strip()))
    return parsed
