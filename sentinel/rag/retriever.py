"""Hybrid retrieval over the vector index.

Combines three complementary signals so retrieval stays useful even with the
offline lexical embedder:

1. **Dense similarity** - cosine similarity of the query embedding against each
   chunk embedding (the vector-store search).
2. **Lexical overlap** - a BM25-style score over the chunk text, which catches
   exact identifiers (metric names, error codes, PIDs) that a hashed embedder
   can blur.
3. **Metadata boost** - small bonus for chunks whose heading or filename
   matches query terms.

Scores are normalised to 0-1 and the components are reported alongside the
final score so the RAG Test Lab can show *why* a chunk was retrieved.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import pandas as pd

from ..config import Settings, get_settings
from ..constants import METRIC_LABELS
from ..logger import get_logger
from .store import SearchHit, VectorStore, get_vector_store, records_from_rows

log = get_logger("rag.retriever")

_WORD = re.compile(r"[a-z0-9_.\-/]+")

DENSE_WEIGHT = 0.6
LEXICAL_WEIGHT = 0.32
META_WEIGHT = 0.08

__all__ = ["RetrievedChunk", "Retriever", "tokenize"]


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens, with camelCase and snake_case split."""
    if not text:
        return []
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    spaced = spaced.replace("_", " ").replace("-", " ")
    return [t for t in _WORD.findall(spaced.lower()) if len(t) > 1]


@dataclass(slots=True)
class RetrievedChunk:
    """A chunk plus its provenance and retrieval diagnostics."""

    document_id: str
    chunk_index: int
    content: str
    score: float
    dense_score: float = 0.0
    lexical_score: float = 0.0
    meta_score: float = 0.0
    page: int | None = None
    heading: str | None = None
    filename: str | None = None
    title: str | None = None
    char_start: int | None = None
    char_end: int | None = None

    @property
    def source_label(self) -> str:
        name = self.filename or self.title or self.document_id[:8]
        parts = [f"{name} - chunk {self.chunk_index + 1}"]
        if self.heading:
            parts.append(f"section '{self.heading}'")
        if self.page:
            parts.append(f"p.{self.page}")
        return " | ".join(parts)

    def as_source(self, rank: int) -> dict[str, Any]:
        """Compact reference record persisted alongside answers."""
        return {
            "rank": rank,
            "document_id": self.document_id,
            "chunk_index": self.chunk_index,
            "score": round(self.score, 4),
            "dense_score": round(self.dense_score, 4),
            "lexical_score": round(self.lexical_score, 4),
            "label": self.source_label,
            "preview": self.content[:280],
        }


class Retriever:
    """Loads chunks from the database, keeps the index fresh, and searches."""

    def __init__(
        self,
        repository: Any,
        settings: Settings | None = None,
        *,
        store: VectorStore | None = None,
        embedder: Any | None = None,
    ) -> None:
        self.repo = repository
        self.settings = settings or get_settings()
        self._store = store
        self._embedder = embedder

    # -- lazily constructed dependencies ------------------------------------ #
    @property
    def store(self) -> VectorStore:
        if self._store is None:
            self._store = get_vector_store(self.settings.vector_store_dir)
        return self._store

    @property
    def embedder(self) -> Any:
        if self._embedder is None:
            from .embeddings import get_embedder

            self._embedder = get_embedder(self.settings)
        return self._embedder

    # -- corpus ------------------------------------------------------------- #
    def load_corpus(self, document_id: str | None = None) -> pd.DataFrame:
        """All indexed chunks (optionally for one document) with document meta."""
        chunks = self.repo.fetch_chunks(document_id=document_id)
        if chunks.empty:
            return chunks
        documents = self.repo.list_documents()
        if not documents.empty and "id" in documents.columns:
            meta = documents.set_index("id")[["filename", "title"]].to_dict("index")
            chunks["filename"] = chunks["document_id"].map(lambda d: meta.get(d, {}).get("filename"))
            chunks["title"] = chunks["document_id"].map(lambda d: meta.get(d, {}).get("title"))
        return chunks

    def ensure_indexed(self, document_id: str | None = None, *, rebuild: bool = False) -> int:
        """Bring the vector index in line with the stored chunks.

        Returns the number of vectors written. Chunks whose embeddings are
        missing in the database are (re-)embedded here, so the index survives a
        cold start or a wiped vector directory.
        """
        corpus = self.load_corpus(document_id)
        if corpus.empty:
            return 0
        if rebuild:
            self.store.reset()
        rows = corpus.to_dict("records")
        missing = [r for r in rows if r.get("embedding") is None]
        if missing:
            self._embed_missing(missing)
            rows = [
                {**r, "embedding": r.get("embedding")}
                for r in rows
            ]
        records = records_from_rows(rows)
        if not records:
            return 0
        written = self.store.upsert(records)
        log.info("Indexed %d chunk vector(s) via %s", written, self.store.name)
        return written

    def _embed_missing(self, rows: Sequence[dict[str, Any]]) -> None:
        texts = [str(r.get("content") or "") for r in rows]
        try:
            vectors = self.embedder.embed(texts)
        except Exception as exc:
            log.warning("Could not embed %d chunk(s): %s", len(texts), exc)
            return
        payloads = []
        for row, vector in zip(rows, vectors):
            row["embedding"] = [float(x) for x in vector]
            payloads.append(
                {
                    "document_id": row["document_id"],
                    "chunk_index": int(row["chunk_index"]),
                    "embedding": row["embedding"],
                }
            )
        if payloads:
            try:
                self.repo.insert_chunks(payloads, include_embeddings=True)
            except Exception as exc:  # pragma: no cover - DB write failure
                log.warning("Could not persist chunk embeddings: %s", exc)

    def drop_document(self, document_id: str) -> int:
        removed = 0
        try:
            removed = self.store.delete_document(document_id)
        except Exception as exc:
            log.warning("Vector delete failed for %s: %s", document_id, exc)
        try:
            self.repo.delete_chunks(document_id)
        except Exception as exc:
            log.warning("Chunk delete failed for %s: %s", document_id, exc)
        return removed

    def index_stats(self) -> dict[str, Any]:
        corpus = self.load_corpus()
        return {
            "backend": self.store.name,
            "chunks": int(len(corpus)),
            "vectors": int(self.store.count()),
            "documents": int(corpus["document_id"].nunique()) if not corpus.empty else 0,
            "dimension": int(getattr(self.embedder, "dimension", 0) or 0),
        }

    # -- search -------------------------------------------------------------- #
    def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        document_id: str | None = None,
        min_score: float | None = None,
        candidate_multiplier: int = 6,
    ) -> list[RetrievedChunk]:
        """Rank chunks against ``query`` using dense + lexical + metadata."""
        cleaned = (query or "").strip()
        if not cleaned:
            return []
        limit = max(1, int(top_k or self.settings.rag_top_k))
        floor = self.settings.rag_min_score if min_score is None else float(min_score)

        corpus = self.load_corpus(document_id)
        if corpus.empty:
            return []

        query_vector = self.embedder.embed_one(cleaned)
        hits = self.store.search(query_vector, top_k=limit * candidate_multiplier, document_id=document_id)

        by_key: dict[str, RetrievedChunk] = {}
        for hit in hits:
            by_key[f"{hit.document_id}::{hit.chunk_index}"] = self._to_chunk(hit, corpus)

        # BM25 over the (possibly much larger) chunk set.
        lexical = self._bm25(cleaned, corpus, document_id)
        query_terms = set(tokenize(cleaned))

        results: list[RetrievedChunk] = []
        for row in corpus.to_dict("records"):
            key = f"{row['document_id']}::{int(row['chunk_index'])}"
            chunk = by_key.pop(key, None)
            if chunk is None:
                chunk = self._chunk_from_row(row)
            chunk.lexical_score = lexical.get(key, 0.0)
            haystack = " ".join(
                str(v) for v in (chunk.heading, chunk.filename, chunk.title) if v
            ).lower()
            hits_terms = sum(1 for term in query_terms if term and term in haystack)
            chunk.meta_score = min(1.0, hits_terms / max(1, len(query_terms))) if query_terms else 0.0
            chunk.score = (
                DENSE_WEIGHT * chunk.dense_score
                + LEXICAL_WEIGHT * chunk.lexical_score
                + META_WEIGHT * chunk.meta_score
            )
            results.append(chunk)

        results.sort(key=lambda c: c.score, reverse=True)
        selected = [c for c in results if c.score >= floor][:limit]
        if not selected and results:
            # Never return an empty result for a non-empty corpus: fall back to
            # the best available matches and let the caller show the low scores.
            selected = results[:limit]
        return selected

    # -- internals ------------------------------------------------------------ #
    @staticmethod
    def _to_chunk(hit: SearchHit, corpus: pd.DataFrame) -> RetrievedChunk:
        row = _row_for(corpus, hit.document_id, hit.chunk_index)
        return RetrievedChunk(
            document_id=hit.document_id,
            chunk_index=hit.chunk_index,
            content=str(row.get("content") or "") if row else "",
            score=hit.score,
            dense_score=hit.score,
            page=_as_int(row.get("page")) if row else None,
            heading=row.get("heading") if row else None,
            filename=row.get("filename") if row else hit.metadata.get("filename"),
            title=row.get("title") if row else hit.metadata.get("title"),
            char_start=_as_int(row.get("char_start")) if row else None,
            char_end=_as_int(row.get("char_end")) if row else None,
        )

    @staticmethod
    def _chunk_from_row(row: Mapping[str, Any]) -> RetrievedChunk:
        return RetrievedChunk(
            document_id=str(row["document_id"]),
            chunk_index=int(row["chunk_index"]),
            content=str(row.get("content") or ""),
            score=0.0,
            page=_as_int(row.get("page")),
            heading=row.get("heading"),
            filename=row.get("filename"),
            title=row.get("title"),
            char_start=_as_int(row.get("char_start")),
            char_end=_as_int(row.get("char_end")),
        )

    @staticmethod
    def _bm25(query: str, corpus: pd.DataFrame, document_id: str | None) -> dict[str, float]:
        """Okapi BM25 with a small metric-name synonym table."""
        expanded = _expand_query(query)
        terms = tokenize(expanded)
        if not terms or corpus.empty:
            return {}
        term_counts = [Counter(tokenize(str(c or ""))) for c in corpus["content"].tolist()]
        doc_lengths = [sum(c.values()) or 1 for c in term_counts]
        avg_length = sum(doc_lengths) / max(1, len(doc_lengths))
        total_docs = len(term_counts)
        document_frequency: Counter = Counter()
        for counts in term_counts:
            for term in set(counts):
                document_frequency[term] += 1

        scores: dict[str, float] = {}
        k1, b = 1.5, 0.75
        for index, counts in enumerate(term_counts):
            score = 0.0
            length = doc_lengths[index]
            for term in terms:
                frequency = counts.get(term, 0)
                if not frequency:
                    continue
                df = document_frequency.get(term, 0)
                idf = math.log(1 + (total_docs - df + 0.5) / (df + 0.5))
                score += idf * (frequency * (k1 + 1)) / (
                    frequency + k1 * (1 - b + b * length / avg_length)
                )
            if score > 0:
                key = f"{corpus.iloc[index]['document_id']}::{int(corpus.iloc[index]['chunk_index'])}"
                scores[key] = score
        if not scores:
            return {}
        ceiling = max(scores.values()) or 1.0
        return {key: value / ceiling for key, value in scores.items()}


def _row_for(corpus: pd.DataFrame, document_id: str, chunk_index: int) -> dict[str, Any] | None:
    if corpus.empty:
        return None
    mask = (corpus["document_id"] == document_id) & (corpus["chunk_index"] == chunk_index)
    matched = corpus[mask]
    if matched.empty:
        return None
    return matched.iloc[0].to_dict()


def _as_int(value: Any) -> int | None:
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


#: Domain synonyms so "cpu spike" can match a chunk that says "processor".
_SYNONYMS: dict[str, str] = {
    "cpu": "processor",
    "anomaly": "anomalous deviation",
    "alert": "alerting",
    "severity": "severity band",
    "risk": "risk score",
    "network": "network interface",
    "memory": "memory utilisation",
    "disk": "disk utilisation",
    "runbook": "runbook procedure response",
    "escalation": "escalate severity",
    "log": "logs logging",
    "process": "processes",
    "response": "response procedure runbook",
    "investigate": "investigation",
    "triage": "triage procedure",
}

_METRIC_SYNONYMS: dict[str, str] = {
    key: label.lower() for key, label in METRIC_LABELS.items()
}


def _expand_query(query: str) -> str:
    """Add domain synonyms and metric names so recall improves."""
    text = query.strip()
    lowered = text.lower()
    additions: list[str] = []
    for token, expansion in _SYNONYMS.items():
        if token in lowered and expansion not in lowered:
            additions.append(expansion)
    for key, label in _METRIC_SYNONYMS.items():
        if key in lowered:
            additions.append(label)
    if re.search(r"\b(anomal|deviat|spike|surg|unusual)\w*\b", lowered):
        additions.append("anomalous behaviour detected baseline")
    return f"{text} {' '.join(additions)}".strip() if additions else text


__all__.append("VectorRecord")
