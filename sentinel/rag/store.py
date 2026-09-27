"""Vector store for document chunks.

Primary backend is **Chroma** (persistent, HNSW-backed, supports metadata
filtering). A **NumPy** backend is used when Chroma is unavailable or the
platform cannot create its SQLite side-car, so the RAG pipeline is never
blocked by an optional dependency.

Both backends persist to ``<data_dir>/vectors`` and both support:
* upsert by ``(document_id, chunk_index)``,
* cosine-similarity search with an optional document filter,
* deletion by document.

Chunk *content* always lives in the database; the vector store holds only
vectors plus the identifiers needed to join back, so a rebuilt index can always
be regenerated from ``document_chunks.embedding``.
"""

from __future__ import annotations

import json
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Sequence

import numpy as np

from ..constants import EMBEDDING_DIM
from ..exceptions import EmbeddingError
from ..logger import get_logger

log = get_logger("rag.store")

BackendName = Literal["chroma", "numpy"]


@dataclass(slots=True)
class VectorRecord:
    """One indexed chunk."""

    id: str
    document_id: str
    chunk_index: int
    embedding: np.ndarray
    metadata: dict[str, Any]


@dataclass(slots=True)
class SearchHit:
    """A retrieval result."""

    id: str
    document_id: str
    chunk_index: int
    score: float
    metadata: dict[str, Any]

    @property
    def source_label(self) -> str:
        name = self.metadata.get("filename") or self.metadata.get("title") or self.document_id
        page = self.metadata.get("page")
        return f"{name} - chunk {self.chunk_index + 1}" + (f", p.{page}" if page else "")


def make_id(document_id: str, chunk_index: int) -> str:
    return f"{document_id}::{chunk_index}"


# --------------------------------------------------------------------------- #
# Base
# --------------------------------------------------------------------------- #
class VectorStore:
    """Interface implemented by both backends."""

    name: BackendName = "numpy"

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)

    def upsert(self, records: Sequence[VectorRecord]) -> int:  # pragma: no cover - interface
        raise NotImplementedError

    def search(
        self, vector: np.ndarray, *, top_k: int = 5, document_id: str | None = None
    ) -> list[SearchHit]:  # pragma: no cover - interface
        raise NotImplementedError

    def delete_document(self, document_id: str) -> int:  # pragma: no cover - interface
        raise NotImplementedError

    def count(self, document_id: str | None = None) -> int:  # pragma: no cover - interface
        raise NotImplementedError

    def reset(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# NumPy backend
# --------------------------------------------------------------------------- #
class NumpyVectorStore(VectorStore):
    """Flat in-memory index persisted as a single ``.npz`` archive."""

    name: BackendName = "numpy"

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self._lock = threading.RLock()
        self._ids: list[str] = []
        self._doc_ids: list[str] = []
        self._chunk_index: list[int] = []
        self._metadata: list[dict[str, Any]] = []
        self._matrix: np.ndarray = np.zeros((0, EMBEDDING_DIM), dtype="float32")
        self._load()

    # -- persistence -------------------------------------------------------- #
    @property
    def _archive(self) -> Path:
        return self.path / "index.npz"

    @property
    def _sidecar(self) -> Path:
        return self.path / "index_meta.json"

    def _load(self) -> None:
        if not self._archive.is_file() or not self._sidecar.is_file():
            return
        try:
            with np.load(self._archive, allow_pickle=False) as archive:
                self._matrix = archive["matrix"].astype("float32")
                self._ids = [str(x) for x in archive["ids"]]
                self._doc_ids = [str(x) for x in archive["doc_ids"]]
                self._chunk_index = [int(x) for x in archive["chunk_index"]]
            self._metadata = json.loads(self._sidecar.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("Could not load NumPy vector index; starting empty: %s", exc)
            self._clear_memory()

    def _save(self) -> None:
        try:
            np.savez_compressed(
                self._archive,
                matrix=self._matrix,
                ids=np.array(self._ids, dtype=object).astype("U"),
                doc_ids=np.array(self._doc_ids, dtype=object).astype("U"),
                chunk_index=np.array(self._chunk_index, dtype="int64"),
            )
            self._sidecar.write_text(
                json.dumps(self._metadata, separators=(",", ":")), encoding="utf-8"
            )
        except OSError as exc:  # pragma: no cover - disk issues
            log.warning("Could not persist NumPy vector index: %s", exc)

    def _clear_memory(self) -> None:
        self._ids = []
        self._doc_ids = []
        self._chunk_index = []
        self._metadata = []
        self._matrix = np.zeros((0, EMBEDDING_DIM), dtype="float32")

    # -- API ---------------------------------------------------------------- #
    def upsert(self, records: Sequence[VectorRecord]) -> int:
        if not records:
            return 0
        with self._lock:
            incoming = {record.id: record for record in records}
            keep = [i for i, rid in enumerate(self._ids) if rid not in incoming]
            new_ids = [record.id for record in records]
            vectors = np.vstack(
                [self._as_vector(record.embedding) for record in records]
            ).astype("float32")
            self._ids = [self._ids[i] for i in keep] + new_ids
            self._doc_ids = [self._doc_ids[i] for i in keep] + [r.document_id for r in records]
            self._chunk_index = [self._chunk_index[i] for i in keep] + [r.chunk_index for r in records]
            self._metadata = [self._metadata[i] for i in keep] + [dict(r.metadata) for r in records]
            if keep:
                self._matrix = np.vstack([self._matrix[keep], vectors])
            else:
                self._matrix = vectors
            self._save()
        return len(records)

    def search(
        self, vector: np.ndarray, *, top_k: int = 5, document_id: str | None = None
    ) -> list[SearchHit]:
        with self._lock:
            if self._matrix.size == 0:
                return []
            query = self._as_vector(vector).reshape(-1)
            if query.shape[0] != self._matrix.shape[1]:
                raise EmbeddingError(
                    f"Query width {query.shape[0]} does not match index width {self._matrix.shape[1]}."
                )
            matrix = self._matrix
            indices = list(range(len(self._ids)))
            metadata = self._metadata
            if document_id:
                indices = [i for i in indices if self._doc_ids[i] == document_id]
            if not indices:
                return []
            subset = matrix[indices]
            scores = subset @ query
            order = np.argsort(scores)[::-1][: max(1, top_k)]
            return [
                SearchHit(
                    id=self._ids[indices[int(position)]],
                    document_id=self._doc_ids[indices[int(position)]],
                    chunk_index=self._chunk_index[indices[int(position)]],
                    score=float(scores[int(position)]),
                    metadata=dict(metadata[indices[int(position)]]),
                )
                for position in order
            ]

    def delete_document(self, document_id: str) -> int:
        with self._lock:
            keep = [i for i, doc in enumerate(self._doc_ids) if doc != document_id]
            removed = len(self._doc_ids) - len(keep)
            if removed:
                self._ids = [self._ids[i] for i in keep]
                self._doc_ids = [self._doc_ids[i] for i in keep]
                self._chunk_index = [self._chunk_index[i] for i in keep]
                self._metadata = [self._metadata[i] for i in keep]
                self._matrix = (
                    self._matrix[keep] if keep else np.zeros((0, self._matrix.shape[1]), dtype="float32")
                )
                self._save()
        return removed

    def count(self, document_id: str | None = None) -> int:
        with self._lock:
            if document_id is None:
                return len(self._ids)
            return sum(1 for doc in self._doc_ids if doc == document_id)

    def reset(self) -> None:
        with self._lock:
            self._clear_memory()
            for candidate in (self._archive, self._sidecar):
                try:
                    candidate.unlink()
                except OSError:
                    pass

    @staticmethod
    def _as_vector(vector: Any) -> np.ndarray:
        array = np.asarray(vector, dtype="float32").reshape(-1)
        norm = float(np.linalg.norm(array))
        return array / norm if norm else array


# --------------------------------------------------------------------------- #
# Chroma backend
# --------------------------------------------------------------------------- #
class ChromaVectorStore(VectorStore):
    """Persistent Chroma collection with cosine distance."""

    name: BackendName = "chroma"
    COLLECTION = "sentinel_documents"

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self._lock = threading.RLock()
        self._client: Any | None = None
        self._collection: Any | None = None

    @property
    def collection(self) -> Any:
        if self._collection is None:
            with self._lock:
                if self._collection is None:
                    self._collection = self._get_collection()
        return self._collection

    def _get_collection(self) -> Any:
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        self._client = chromadb.PersistentClient(
            path=str(self.path),
            settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True),
        )
        return self._client.get_or_create_collection(
            name=self.COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert(self, records: Sequence[VectorRecord]) -> int:
        if not records:
            return 0
        with self._lock:
            collection = self.collection
            vectors = [NumpyVectorStore._as_vector(r.embedding).tolist() for r in records]
            metadatas = [
                {
                    "document_id": r.document_id,
                    "chunk_index": int(r.chunk_index),
                    **{k: _scalar(v) for k, v in (r.metadata or {}).items()},
                }
                for r in records
            ]
            collection.upsert(
                ids=[r.id for r in records],
                embeddings=vectors,
                metadatas=metadatas,
                documents=[str(r.metadata.get("preview", "")) for r in records],
            )
        return len(records)

    def search(
        self, vector: np.ndarray, *, top_k: int = 5, document_id: str | None = None
    ) -> list[SearchHit]:
        with self._lock:
            collection = self.collection
            total = collection.count()
            if not total:
                return []
            where = {"document_id": document_id} if document_id else None
            result = collection.query(
                query_embeddings=[NumpyVectorStore._as_vector(vector).tolist()],
                n_results=min(max(1, top_k), max(1, total)),
                where=where,
                include=["metadatas", "distances"],
            )
        ids = (result.get("ids") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        hits: list[SearchHit] = []
        for position, identifier in enumerate(ids):
            metadata = dict(metadatas[position] or {}) if position < len(metadatas) else {}
            distance = float(distances[position]) if position < len(distances) else 1.0
            hits.append(
                SearchHit(
                    id=str(identifier),
                    document_id=str(metadata.get("document_id") or ""),
                    chunk_index=int(metadata.get("chunk_index") or 0),
                    # Chroma reports cosine distance; similarity = 1 - distance.
                    score=max(0.0, 1.0 - distance),
                    metadata=metadata,
                )
            )
        return hits

    def delete_document(self, document_id: str) -> int:
        with self._lock:
            collection = self.collection
            existing = collection.get(where={"document_id": document_id}, include=[])
            ids = existing.get("ids") or []
            if ids:
                collection.delete(ids=list(ids))
            return len(ids)

    def count(self, document_id: str | None = None) -> int:
        with self._lock:
            collection = self.collection
            if document_id is None:
                return int(collection.count())
            return int(len(collection.get(where={"document_id": document_id}, include=[]).get("ids") or []))

    def reset(self) -> None:
        with self._lock:
            try:
                self._client.delete_collection(self.COLLECTION)
            except Exception:  # pragma: no cover - already gone
                pass
            self._collection = None
            self._client = None
            shutil.rmtree(self.path, ignore_errors=True)
            self.path.mkdir(parents=True, exist_ok=True)


def _scalar(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)):
        return value
    if value is None:
        return ""
    return str(value)[:512]


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #
_store_cache: dict[str, VectorStore] = {}
_store_lock = threading.Lock()


def get_vector_store(
    path: Path, *, prefer: BackendName | None = None, allow_fallback: bool = True
) -> VectorStore:
    """Return a cached vector store, preferring Chroma when it is usable."""
    key = str(path)
    with _store_lock:
        cached = _store_cache.get(key)
    if cached is not None and (prefer is None or cached.name == prefer):
        return cached

    order: list[BackendName]
    if prefer:
        order = [prefer]
    else:
        order = ["chroma", "numpy"]
    if not allow_fallback:
        order = order[:1]

    last_error: Exception | None = None
    for backend in order:
        try:
            store = ChromaVectorStore(path) if backend == "chroma" else NumpyVectorStore(path)
            if backend == "chroma":
                store.count()  # force initialisation so failures surface here
            with _store_lock:
                _store_cache[key] = store
            log.info("Vector store backend: %s (%s)", store.name, path)
            return store
        except Exception as exc:
            last_error = exc
            log.warning("Vector backend %s unavailable: %s", backend, exc)

    store = NumpyVectorStore(path)
    with _store_lock:
        _store_cache[key] = store
    log.info("Vector store backend: numpy (%s). Last error: %s", path, last_error)
    return store


def clear_cache() -> None:
    with _store_lock:
        _store_cache.clear()


def records_from_rows(rows: Iterable[dict[str, Any]]) -> list[VectorRecord]:
    """Build :class:`VectorRecord` objects from ``document_chunks`` rows."""
    records: list[VectorRecord] = []
    for row in rows:
        embedding = row.get("embedding")
        if embedding is None:
            continue
        document_id = str(row.get("document_id") or "")
        chunk_index = int(row.get("chunk_index") or 0)
        metadata = {
            "filename": row.get("filename"),
            "title": row.get("title"),
            "page": row.get("page"),
            "heading": row.get("heading"),
            "char_start": row.get("char_start"),
            "char_end": row.get("char_end"),
        }
        metadata = {k: v for k, v in metadata.items() if v is not None}
        records.append(
            VectorRecord(
                id=make_id(document_id, chunk_index),
                document_id=document_id,
                chunk_index=chunk_index,
                embedding=np.asarray(embedding, dtype="float32"),
                metadata=metadata,
            )
        )
    return records


__all__ = [
    "BackendName",
    "ChromaVectorStore",
    "NumpyVectorStore",
    "SearchHit",
    "VectorRecord",
    "VectorStore",
    "clear_cache",
    "get_vector_store",
    "make_id",
    "records_from_rows",
]
