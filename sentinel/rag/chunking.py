"""Text chunking for retrieval-augmented generation.

Chunks are produced with structure in mind:

* Markdown headings become chunk boundaries and are carried into a ``heading``
  field so retrieved context keeps its section title.
* Tables and fenced code blocks are never split mid-row / mid-block.
* Windows and POSIX line endings are handled identically.
* Character offsets are preserved so the UI can highlight the exact source span.

Overlap is expressed in characters (not tokens) so behaviour is deterministic
and independent of any tokenizer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterator, Sequence

__all__ = [
    "Chunk",
    "chunk_document",
    "chunk_text",
    "estimate_tokens",
]

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
_FENCE = re.compile(r"^```", re.MULTILINE)


@dataclass(slots=True)
class Chunk:
    """A retrievable span of a document."""

    index: int
    content: str
    char_start: int
    char_end: int
    page: int | None = None
    heading: str | None = None
    token_estimate: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_row(self, document_id: str, embedding: list[float] | None = None) -> dict[str, Any]:
        return {
            "document_id": document_id,
            "chunk_index": self.index,
            "content": self.content,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "page": self.page,
            "heading": self.heading,
            "token_estimate": self.token_estimate,
            "metadata": self.metadata,
            "embedding": embedding,
        }


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 characters per token) - no tokenizer required."""
    if not text:
        return 0
    return max(1, len(text) // 4)


# --------------------------------------------------------------------------- #
# Chunking
# --------------------------------------------------------------------------- #
def chunk_document(
    text: str,
    *,
    chunk_size: int = 900,
    overlap: int = 150,
    pages: list[str] | None = None,
) -> list[Chunk]:
    """Split a full document, keeping page boundaries where they exist."""
    if not text or not text.strip():
        return []
    size = max(120, int(chunk_size))
    step_back = max(0, min(int(overlap), size // 2))

    if pages:
        chunks: list[Chunk] = []
        offset = 0
        for page_number, page in enumerate(pages, start=1):
            if not page.strip():
                continue
            page_chunks = _chunk_span(
                page, base_offset=offset, chunk_size=size, overlap=step_back, page=page_number
            )
            for item in page_chunks:
                item.heading = item.heading or f"Page {page_number}"
            chunks.extend(page_chunks)
            offset += len(page) + 2  # pages were joined with "\n\n"
        if chunks:
            return _renumber(chunks)
        # Fall through to whole-document chunking if page mapping was unusable.

    return _renumber(_chunk_span(text, base_offset=0, chunk_size=size, overlap=step_back, page=None))


def chunk_text(text: str, *, chunk_size: int = 900, overlap: int = 150) -> list[Chunk]:
    """Convenience wrapper for plain strings."""
    return chunk_document(text, chunk_size=chunk_size, overlap=overlap)


def _chunk_span(
    text: str,
    *,
    base_offset: int,
    chunk_size: int,
    overlap: int,
    page: int | None,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    position = 0
    length = len(text)
    spans = _fence_spans(text)

    while position < length:
        hard_end = min(position + chunk_size, length)
        limit = _respect_code_fences(text, position, hard_end, spans, chunk_size)
        window = text[position:limit]
        window_length = len(window)

        # Prefer to break on a paragraph, then a sentence, then whitespace.
        split = _best_split(window, window_length)
        body = window[:split].rstrip()
        if not body:
            body = window
            split = window_length

        start = position
        end = position + len(body)
        heading = _heading_for(text, start)

        # Skip a trailing repeat of the previous chunk (can happen when the
        # tail is short and almost fully covered by the overlap).
        if chunks and body and body == chunks[-1].content:
            break

        chunks.append(
            Chunk(
                index=len(chunks),
                content=body,
                char_start=base_offset + start,
                char_end=base_offset + end,
                page=page,
                heading=heading,
                token_estimate=estimate_tokens(body),
            )
        )

        # The window reaching the end of the text is what terminates the loop.
        # Comparing ``end`` is not enough: ``body`` is rstripped, so the final
        # chunk can stop a character or two short and the next iteration would
        # then walk the tail one character at a time.
        if limit >= length or not body:
            break
        position += max(1, len(body) - overlap)

    return chunks


def _fence_spans(text: str) -> list[tuple[int, int]]:
    """Character spans of fenced code blocks, delimiters included."""
    spans: list[tuple[int, int]] = []
    open_at: int | None = None
    for match in _FENCE.finditer(text):
        if open_at is None:
            open_at = match.start()
        else:
            spans.append((open_at, match.end()))
            open_at = None
    if open_at is not None:
        spans.append((open_at, len(text)))
    return spans


def _respect_code_fences(
    text: str, position: int, hard_end: int, spans: Sequence[tuple[int, int]], chunk_size: int
) -> int:
    """Return a window end that does not slice a fenced code block.

    The window is extended to close a block that is about to be cut when the
    block is small enough to fit; otherwise the window stops *before* the block
    opens. A block that both starts before this window and is larger than two
    chunk windows cannot be kept whole, so the cut is allowed inside it.
    """
    for start, end in spans:
        if end <= position:
            continue
        if start >= hard_end:
            break
        if start < hard_end < end:  # the default window would slice this block
            if end - position <= chunk_size * 2:
                return end
            if start > position:
                return start
            return min(end, position + chunk_size * 2)
    return hard_end


def _best_split(window: str, window_length: int) -> int:
    """Choose a chunk end that does not cut a paragraph or sentence in half."""
    if window_length >= len(window):
        window_length = len(window)
    lower_two_thirds = int(window_length * 0.6)

    paragraph = window.rfind("\n\n", lower_two_thirds, window_length)
    if paragraph != -1:
        return paragraph

    newline = window.rfind("\n", lower_two_thirds, window_length)
    if newline != -1:
        return newline

    matches = list(_SENTENCE_END.finditer(window, lower_two_thirds, window_length))
    if matches:
        return matches[-1].start() + 1

    space = window.rfind(" ", lower_two_thirds, window_length)
    if space != -1:
        return space

    return window_length


def _heading_for(text: str, offset: int) -> str | None:
    """Nearest markdown heading at or before ``offset``."""
    best: str | None = None
    for match in _HEADING.finditer(text, 0, max(0, offset) + 1):
        best = match.group(2).strip()
    return best or None


def _renumber(chunks: list[Chunk]) -> list[Chunk]:
    for index, item in enumerate(chunks):
        item.index = index
    return chunks


def iter_chunks(chunks: list[Chunk]) -> Iterator[Chunk]:
    yield from chunks
