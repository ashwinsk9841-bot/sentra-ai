"""Retrieval-augmented generation subsystem for Sentinel AI."""

from __future__ import annotations

from .chunking import Chunk, chunk_document, chunk_text, estimate_tokens
from .embeddings import (
    EmbeddingProvider,
    HashingEmbedder,
    RemoteEmbedder,
    describe_provider,
    get_embedder,
)
from .ingestion import ParsedDocument, parse_bytes, parse_path
from .pipeline import IngestionReport, RagAnswer, RagPipeline, RagResult
from .retriever import RetrievedChunk, Retriever
from .store import SearchHit, VectorRecord, VectorStore, get_vector_store

__all__ = [
    "Chunk",
    "EmbeddingProvider",
    "HashingEmbedder",
    "IngestionReport",
    "ParsedDocument",
    "RagAnswer",
    "RagPipeline",
    "RagResult",
    "RemoteEmbedder",
    "RetrievedChunk",
    "Retriever",
    "SearchHit",
    "VectorRecord",
    "VectorStore",
    "chunk_document",
    "chunk_text",
    "describe_provider",
    "estimate_tokens",
    "get_embedder",
    "get_vector_store",
    "parse_bytes",
    "parse_path",
]
