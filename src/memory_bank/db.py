"""Qdrant vector DB wrapper — embedded, no server required."""
from __future__ import annotations

import hashlib
import math
import os
import struct
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
)

from .schema import ChatMessage

COLLECTION = "chat_history"
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"   # fast, 384-dim, runs locally via fastembed
VECTOR_SIZE = 384

DEFAULT_DB_PATH = Path.home() / ".memory-bank" / "qdrant"


def get_db_path() -> Path:
    env = os.environ.get("MEMORY_BANK_DB")
    return Path(env) if env else DEFAULT_DB_PATH


def _load_embedder():
    """
    Load fastembed TextEmbedding. Downloads the model on first use (~25 MB from HuggingFace).
    Returns None if the network is unavailable or model download fails.
    """
    try:
        from fastembed import TextEmbedding
        return TextEmbedding(EMBEDDING_MODEL)
    except Exception:
        return None


def _hash_embed(text: str, dim: int = VECTOR_SIZE) -> list[float]:
    """
    Offline fallback: deterministic hash-based embedding.
    Not as accurate as neural embeddings but works without internet access.
    Splits text into trigrams, hashes them, and accumulates into a float vector.
    """
    vec = [0.0] * dim
    words = text.lower().split()
    tokens = words + [a + b for a, b in zip(words, words[1:])]
    if not tokens:
        tokens = [text[:64]]
    for token in tokens:
        digest = hashlib.sha256(token.encode()).digest()
        for i in range(0, min(len(digest), dim * 4), 4):
            idx = (i // 4) % dim
            val = struct.unpack_from("<f", digest, i % (len(digest) - 3))[0]
            if math.isfinite(val):
                vec[idx] += val
    # L2 normalize
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


class MemoryDB:
    """Thin wrapper around an embedded Qdrant collection."""

    def __init__(self, path: Path | None = None):
        self.path = path or get_db_path()
        self.path.mkdir(parents=True, exist_ok=True)
        self._client = QdrantClient(path=str(self.path))
        self._embedder = None   # loaded on first call to _embed()
        self._embedder_loaded = False
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        existing = {c.name for c in self._client.get_collections().collections}
        if COLLECTION not in existing:
            self._client.create_collection(
                collection_name=COLLECTION,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            )

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def upsert(self, messages: list[ChatMessage]) -> tuple[int, int]:
        """Insert messages that don't exist yet. Returns (inserted, skipped)."""
        if not messages:
            return 0, 0

        existing_ids = self._existing_ids({m.id for m in messages})
        new_msgs = [m for m in messages if m.id not in existing_ids]

        if not new_msgs:
            return 0, len(messages)

        texts = [m.content for m in new_msgs]
        vectors = self._embed(texts)

        points = [
            PointStruct(
                id=_id_to_uint(m.id),
                vector=vec,
                payload=m.to_payload(),
            )
            for m, vec in zip(new_msgs, vectors)
        ]
        self._client.upsert(collection_name=COLLECTION, points=points)
        return len(new_msgs), len(messages) - len(new_msgs)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        limit: int = 10,
        source: str | None = None,
        project: str | None = None,
        role: str | None = None,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic search with optional metadata filters."""
        query_vec = self._embed([query])[0]
        flt = self._build_filter(source=source, project=project, role=role, session_id=session_id)

        response = self._client.query_points(
            collection_name=COLLECTION,
            query=query_vec,
            query_filter=flt,
            limit=limit,
            with_payload=True,
        )
        return [
            {"score": r.score, **r.payload}
            for r in response.points
        ]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        count = self._client.count(COLLECTION).count

        # Count by source via scroll
        source_counts: dict[str, int] = {}
        offset = None
        while True:
            records, offset = self._client.scroll(
                collection_name=COLLECTION,
                limit=1000,
                offset=offset,
                with_payload=["source"],
            )
            for r in records:
                src = r.payload.get("source", "unknown")
                source_counts[src] = source_counts.get(src, 0) + 1
            if offset is None:
                break

        embedding_status = "neural (BAAI/bge-small-en-v1.5)" if self._embedder else "hash-based fallback (offline)"
        return {
            "total_messages": count,
            "by_source": source_counts,
            "db_path": str(self.path),
            "collection": COLLECTION,
            "embedding_model": embedding_status,
        }

    def delete_by_source(self, source: str) -> int:
        """Delete all messages from a given source. Returns count deleted."""
        before = self._client.count(COLLECTION).count
        self._client.delete(
            collection_name=COLLECTION,
            points_selector=Filter(
                must=[FieldCondition(key="source", match=MatchValue(value=source))]
            ),
        )
        after = self._client.count(COLLECTION).count
        return before - after

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if not self._embedder_loaded:
            self._embedder = _load_embedder()
            self._embedder_loaded = True
            if self._embedder is None:
                import sys
                print(
                    "[warning] fastembed model unavailable (no internet?). "
                    "Using hash-based fallback embeddings — semantic search quality will be reduced. "
                    "Re-ingest once online to get full quality.",
                    file=sys.stderr,
                )
        if self._embedder is not None:
            return [vec.tolist() for vec in self._embedder.embed(texts)]
        return [_hash_embed(t) for t in texts]

    def _existing_ids(self, ids: set[str]) -> set[str]:
        uint_ids = [_id_to_uint(i) for i in ids]
        results = self._client.retrieve(
            collection_name=COLLECTION,
            ids=uint_ids,
            with_payload=["id"],
        )
        return {r.payload["id"] for r in results}

    def _build_filter(self, **kwargs: str | None) -> Filter | None:
        conditions = [
            FieldCondition(key=k, match=MatchValue(value=v))
            for k, v in kwargs.items()
            if v is not None
        ]
        return Filter(must=conditions) if conditions else None


def _id_to_uint(hex_id: str) -> int:
    """Convert a 64-char hex SHA-256 to a uint64 by taking the first 16 hex chars."""
    return int(hex_id[:16], 16)
