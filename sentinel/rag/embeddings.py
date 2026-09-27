"""Embedding generation.

Two providers, selected automatically:

``remote``
    Any OpenAI-compatible ``/embeddings`` endpoint (OpenAI, Azure via
    ``EMBEDDING_BASE_URL``, Ollama, LiteLLM, vLLM, ...). Used when
    ``EMBEDDING_API_KEY`` is configured.

``local``
    A deterministic, dependency-free hashed n-gram embedder. It is a genuine
    vector representation (not a stub): character 3-5 grams and word unigrams
    are hashed into a fixed 384-dimensional space, TF-IDF weighted and L2
    normalised. It keeps the whole RAG pipeline functional and testable with
    no external service, while being clearly labelled in the UI as the local
    provider so nobody mistakes it for a semantic model.

Both providers return L2-normalised float32 vectors, so cosine similarity is a
plain dot product in the retriever.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
import threading
from collections import Counter
from typing import Any, Iterable, Protocol, Sequence

import numpy as np

from ..config import Settings, get_settings
from ..constants import EMBEDDING_DIM
from ..exceptions import EmbeddingError
from ..logger import get_logger

log = get_logger("rag.embeddings")

_WORD = re.compile(r"[a-z0-9_]+")
_STOPWORDS = frozenset(
    """a an and are as at be but by for if in into is it no not of on or such that the
    their then there these they this to was will with i we you he she them our your what
    when where which who whom how""".split()
)

__all__ = [
    "EmbeddingProvider",
    "HashingEmbedder",
    "RemoteEmbedder",
    "cosine_similarity",
    "get_embedder",
]


class EmbeddingProvider(Protocol):
    """Interface implemented by both providers."""

    name: str
    dimension: int

    def embed(self, texts: Sequence[str]) -> np.ndarray: ...

    def embed_one(self, text: str) -> np.ndarray: ...


# --------------------------------------------------------------------------- #
# Local hashed embedder
# --------------------------------------------------------------------------- #
class HashingEmbedder:
    """Deterministic hashed bag-of-features embedder (offline provider)."""

    name = "local-hashing"

    def __init__(self, dimension: int = EMBEDDING_DIM, *, ngram_range: tuple[int, int] = (3, 5)) -> None:
        self.dimension = int(dimension)
        self.ngram_range = ngram_range

    # -- feature extraction ------------------------------------------------ #
    def _terms(self, text: str) -> Counter:
        lowered = text.lower()
        terms: Counter = Counter()
        for word in _WORD.findall(lowered):
            if word in _STOPWORDS or len(word) < 2:
                continue
            terms[f"w:{word}"] += 1
        padded = f" {re.sub(r'[^a-z0-9]+', ' ', lowered).strip()} "
        low, high = self.ngram_range
        for n in range(low, high + 1):
            for index in range(len(padded) - n + 1):
                gram = padded[index : index + n].strip()
                if len(gram) == n:
                    terms[f"g:{gram}"] += 1
        return terms

    def _bucket(self, term: str) -> tuple[int, float]:
        digest = hashlib.blake2b(term.encode("utf-8"), digest_size=8).digest()
        value = struct.unpack("<Q", digest)[0]
        index = value % self.dimension
        # Signed hashing keeps collisions unbiased.
        sign = 1.0 if (value >> 63) & 1 else -1.0
        return index, sign

    def _vector(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dimension, dtype="float32")
        terms = self._terms(text or "")
        if not terms:
            return vector
        for term, count in terms.items():
            index, sign = self._bucket(term)
            # Sublinear TF damping + sign hashing: standard hashing-trick setup.
            vector[index] += sign * (1.0 + math.log(count))
        norm = float(np.linalg.norm(vector))
        if norm > 0:
            vector /= norm
        return vector

    # -- provider API ------------------------------------------------------- #
    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype="float32")
        return np.vstack([self._vector(t) for t in texts]).astype("float32")

    def embed_one(self, text: str) -> np.ndarray:
        return self._vector(text)


# --------------------------------------------------------------------------- #
# Remote embedder
# --------------------------------------------------------------------------- #
class RemoteEmbedder:
    """OpenAI-compatible ``/embeddings`` client built on ``urllib``."""

    name = "remote-api"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        dimension: int = EMBEDDING_DIM,
        timeout: float = 60.0,
        batch_size: int = 64,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        # Providers report their true width only after the first call; the
        # configured value is the best prior until then.
        self.dimension = int(dimension)
        self.timeout = float(timeout)
        self.batch_size = max(1, int(batch_size))
        self._lock = threading.Lock()

    def _endpoint(self) -> str:
        if self.base_url.endswith("/embeddings"):
            return self.base_url
        return f"{self.base_url}/embeddings"

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype="float32")
        vectors: list[np.ndarray] = []
        for start in range(0, len(texts), self.batch_size):
            batch = [t or " " for t in texts[start : start + self.batch_size]]
            vectors.extend(self._request(batch))
        stacked = np.vstack(vectors).astype("float32")
        self._remember_dimension(stacked.shape[1])
        norms = np.linalg.norm(stacked, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return stacked / norms

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]

    def _remember_dimension(self, dimension: int) -> None:
        with self._lock:
            if dimension and dimension != self.dimension:
                log.info("Embedding provider reported width %d (configured %d).", dimension, self.dimension)
                self.dimension = int(dimension)

    def _request(self, batch: Sequence[str]) -> list[np.ndarray]:
        import urllib.error
        import urllib.request

        payload = json.dumps({"model": self.model, "input": list(batch)}).encode("utf-8")
        request = urllib.request.Request(
            self._endpoint(),
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise EmbeddingError(
                f"Embedding provider returned HTTP {exc.code}: {detail}"
            ) from exc
        except Exception as exc:
            raise EmbeddingError(f"Could not reach the embedding provider: {exc}") from exc

        items = body.get("data") or []
        if len(items) != len(batch):
            raise EmbeddingError(
                f"Embedding provider returned {len(items)} vector(s) for {len(batch)} input(s)."
            )
        # The API may return results out of order; ``index`` is authoritative.
        ordered = sorted(items, key=lambda item: int(item.get("index", 0)))
        out: list[np.ndarray] = []
        for item in ordered:
            vector = item.get("embedding")
            if not isinstance(vector, list) or not vector:
                raise EmbeddingError("Embedding provider returned an empty vector.")
            out.append(np.asarray(vector, dtype="float32"))
        return out


# --------------------------------------------------------------------------- #
# Similarity helper
# --------------------------------------------------------------------------- #
def cosine_similarity(matrix: np.ndarray, vector: np.ndarray) -> np.ndarray:
    """Cosine similarity of ``vector`` against every row of ``matrix``."""
    left = np.atleast_2d(np.asarray(matrix, dtype="float32"))
    right = np.asarray(vector, dtype="float32").reshape(1, -1)
    if left.size == 0:
        return np.zeros(0, dtype="float32")
    if left.shape[1] != right.shape[1]:
        raise EmbeddingError(
            f"Embedding width mismatch: index has {left.shape[1]}, query has {right.shape[1]}."
        )
    left_norms = np.linalg.norm(left, axis=1)
    left_norms[left_norms == 0] = 1.0
    right_norm = float(np.linalg.norm(right)) or 1.0
    return (left @ right.T).reshape(-1) / (left_norms * right_norm)


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #
_embedder_cache: dict[tuple[str, str, str, int], EmbeddingProvider] = {}
_cache_lock = threading.Lock()


def get_embedder(settings: Settings | None = None, *, force_local: bool = False) -> EmbeddingProvider:
    """Return the configured embedding provider (cached per configuration)."""
    cfg = settings or get_settings()
    if force_local or not cfg.remote_embeddings_configured:
        key = ("local", "", "", EMBEDDING_DIM)
    else:
        key = (
            "remote",
            cfg.embedding_base_url,
            cfg.embedding_model,
            EMBEDDING_DIM,
        )
    with _cache_lock:
        cached = _embedder_cache.get(key)
        if cached is not None:
            return cached

    if key[0] == "local":
        provider: EmbeddingProvider = HashingEmbedder(EMBEDDING_DIM)
    else:
        provider = RemoteEmbedder(
            api_key=cfg.embedding_api_key or "",
            base_url=cfg.embedding_base_url,
            model=cfg.embedding_model,
            dimension=EMBEDDING_DIM,
        )
    with _cache_lock:
        _embedder_cache[key] = provider
    return provider


def describe_provider(provider: EmbeddingProvider) -> dict[str, Any]:
    """UI-facing description of the active provider."""
    if isinstance(provider, RemoteEmbedder):
        return {
            "provider": provider.name,
            "model": provider.model,
            "dimension": provider.dimension,
            "semantic": True,
            "note": "Remote embedding API. Vectors capture semantic similarity.",
        }
    return {
        "provider": provider.name,
        "model": "hashed-ngram-tfidf",
        "dimension": provider.dimension,
        "semantic": False,
        "note": (
            "Offline lexical embedder. Retrieval works fully offline but matches on "
            "surface word/n-gram overlap rather than deep semantics. Set "
            "EMBEDDING_API_KEY for semantic retrieval."
        ),
    }


def clear_cache() -> None:
    with _cache_lock:
        _embedder_cache.clear()
