"""Document parsing and cleaning.

Converts an uploaded file into normalised text plus per-page boundaries.
Supported formats mirror ``constants.SUPPORTED_DOC_EXTENSIONS``.

Design notes
------------
* A malformed or binary file raises :class:`IngestionError` with the underlying
  reason, so the UI can tell the user what to fix instead of failing silently.
* CSV / JSON are converted to readable text rather than being embedded raw, so
  retrieval works over the *content* and not over syntax.
* Whitespace is collapsed but line structure is preserved for code blocks and
  log files, because indentation carries meaning there.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from ..constants import SUPPORTED_DOC_EXTENSIONS
from ..exceptions import IngestionError
from ..logger import get_logger

log = get_logger("rag.ingestion")

_ENCODINGS = ("utf-8", "utf-8-sig", "cp1252", "latin-1")

_WS_RUN = re.compile(r"[ \t]{2,}")
_BLANK_RUN = re.compile(r"\n{4,}")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass(slots=True)
class ParsedDocument:
    """Normalised text plus structural metadata."""

    text: str
    pages: list[str] = field(default_factory=list)
    title: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def page_count(self) -> int:
        return len(self.pages) or 1

    @property
    def line_count(self) -> int:
        return self.text.count("\n") + 1 if self.text else 0


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #
def parse_bytes(data: bytes, filename: str) -> ParsedDocument:
    """Parse raw uploaded bytes into text. Raises on unusable input."""
    if not data:
        raise IngestionError(f"'{filename}' is empty (0 bytes).")

    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_DOC_EXTENSIONS and extension not in (".yaml", ".yml", ".jsonl"):
        raise IngestionError(
            f"Unsupported file type '{extension or 'unknown'}'. "
            f"Supported: {', '.join(SUPPORTED_DOC_EXTENSIONS)}"
        )

    if extension == ".pdf":
        return _parse_pdf(data, filename)
    if extension in (".csv",):
        return _parse_csv(data, filename)
    if extension in (".json",):
        return _parse_json(data, filename)
    if extension in (".jsonl",):
        return _parse_jsonl(data, filename)
    return _parse_text(data, filename)


def parse_path(path: str | Path) -> ParsedDocument:
    """Parse a document from disk (used by the agent log shipper)."""
    file_path = Path(path)
    if not file_path.is_file():
        raise IngestionError(f"No such file: {file_path}")
    try:
        data = file_path.read_bytes()
    except OSError as exc:
        raise IngestionError(f"Could not read {file_path.name}: {exc}") from exc
    return parse_bytes(data, file_path.name)


# --------------------------------------------------------------------------- #
# Format handlers
# --------------------------------------------------------------------------- #
def _decode(data: bytes, filename: str) -> str:
    for encoding in _ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise IngestionError(
        f"Could not decode '{filename}' as text. If it is a binary file, "
        "convert it to PDF, TXT, MD, CSV or JSON first."
    )


def _parse_pdf(data: bytes, filename: str) -> ParsedDocument:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency missing
        raise IngestionError(
            "PDF support requires the 'pypdf' package.",
            hint="Run: pip install pypdf",
        ) from exc
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:
                raise IngestionError(
                    f"'{filename}' is password protected and cannot be indexed."
                ) from exc
        pages = [(page.extract_text() or "") for page in reader.pages]
    except IngestionError:
        raise
    except Exception as exc:
        raise IngestionError(f"Could not read PDF '{filename}': {exc}") from exc

    pages = [clean_text(p) for p in pages]
    pages = [p for p in pages if p.strip()]
    if not pages:
        raise IngestionError(
            f"No extractable text found in '{filename}'. Scanned PDFs need OCR before upload."
        )
    return ParsedDocument(
        text="\n\n".join(pages),
        pages=pages,
        title=_pdf_title(reader, filename),
        metadata={"parser": "pypdf", "page_count": len(pages)},
    )


def _pdf_title(reader: Any, filename: str) -> str:
    try:
        info = reader.metadata or {}
        for key in ("/Title", "title", "Title"):
            value = info.get(key) if hasattr(info, "get") else None
            if value:
                return str(value).strip() or filename
    except Exception:  # pragma: no cover - metadata is best-effort
        pass
    return filename


def _parse_text(data: bytes, filename: str) -> ParsedDocument:
    text = clean_text(_decode(data, filename))
    if not text.strip():
        raise IngestionError(f"'{filename}' contains no readable text.")
    # Split on form feeds (classic .txt/.log convention) into pseudo-pages.
    pages = [clean_text(p) for p in text.split("\f")] if "\f" in text else []
    pages = [p for p in pages if p.strip()]
    return ParsedDocument(
        text=text,
        pages=pages,
        title=filename,
        metadata={"parser": "plaintext", "line_count": text.count("\n") + 1},
    )


def _parse_csv(data: bytes, filename: str) -> ParsedDocument:
    raw = _decode(data, filename)
    try:
        dialect = csv.Sniffer().sniff(raw[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(raw), dialect)
    rows = [row for row in reader if any(str(cell).strip() for cell in row)]
    if not rows:
        raise IngestionError(f"'{filename}' contains no data rows.")

    header = [str(cell).strip() for cell in rows[0]]
    lines = [" | ".join(header)]
    for row in rows[1:]:
        lines.append(" | ".join(str(cell).strip() for cell in row))
    body = "\n".join(lines)
    preamble = (
        f"CSV table '{filename}' with {len(rows) - 1} data row(s).\n"
        f"Columns: {', '.join(header)}\n\n"
    )
    return ParsedDocument(
        text=preamble + body,
        pages=[preamble + body],
        title=filename,
        metadata={
            "parser": "csv",
            "rows": len(rows) - 1,
            "columns": header,
            "delimiter": dialect.delimiter,
        },
    )


def _parse_json(data: bytes, filename: str) -> ParsedDocument:
    raw = _decode(data, filename)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IngestionError(
            f"'{filename}' is not valid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno})."
        ) from exc
    return ParsedDocument(
        text=_flatten_json(payload),
        pages=[_flatten_json(payload)],
        title=filename,
        metadata={"parser": "json", "root_type": type(payload).__name__},
    )


def _parse_jsonl(data: bytes, filename: str) -> ParsedDocument:
    raw = _decode(data, filename)
    lines: list[str] = []
    for number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            lines.append(_flatten_json(json.loads(line)))
        except json.JSONDecodeError as exc:
            log.warning("Skipping malformed JSONL line %d in %s: %s", number, filename, exc.msg)
    if not lines:
        raise IngestionError(f"'{filename}' contains no valid JSON lines.")
    text = "\n".join(lines)
    return ParsedDocument(
        text=text, pages=[text], title=filename, metadata={"parser": "jsonl", "records": len(lines)}
    )


def _flatten_json(payload: Any, prefix: str = "", depth: int = 0) -> str:
    """Render JSON as ``path: value`` lines so retrieval sees real content."""
    if depth > 12:
        return f"{prefix}: <max depth reached>"
    if isinstance(payload, dict):
        rows = []
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            rows.append(_flatten_json(value, path, depth + 1))
        return "\n".join(rows)
    if isinstance(payload, list):
        if not payload:
            return f"{prefix}: <empty list>"
        head = payload[:50]
        rows = [f"{prefix}[{i}]: {_scalar(value)}" for i, value in enumerate(head)]
        if len(payload) > len(head):
            rows.append(f"{prefix}[...]: <{len(payload) - len(head)} more items>")
        return "\n".join(rows)
    return f"{prefix}: {_scalar(payload)}"


def _scalar(value: Any) -> str:
    if isinstance(value, str):
        return clean_text(value)
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


# --------------------------------------------------------------------------- #
# Cleaning
# --------------------------------------------------------------------------- #
def clean_text(text: str) -> str:
    """Normalise whitespace and strip control characters."""
    if not text:
        return ""
    cleaned = _CONTROL.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    cleaned = "\n".join(_WS_RUN.sub(" ", line).rstrip() for line in cleaned.split("\n"))
    cleaned = _BLANK_RUN.sub("\n\n\n", cleaned)
    return cleaned.strip()


def guess_title(filename: str, first_lines: Sequence[str] | None = None) -> str:
    """Derive a human title from the filename or the first markdown heading."""
    for line in first_lines or []:
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or Path(filename).stem
    return Path(filename).stem.replace("_", " ").replace("-", " ").strip().title()


def supported_extensions() -> Iterable[str]:
    return SUPPORTED_DOC_EXTENSIONS
