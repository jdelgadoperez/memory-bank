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
    PayloadSchemaType,
)

from .schema import ChatMessage, Session

MESSAGES_COLLECTION = "chat_history"
SESSIONS_COLLECTION = "sessions"
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"   # fast, 384-dim, runs locally via fastembed
VECTOR_SIZE = 384

DEFAULT_DB_PATH = Path.home() / ".memory-bank" / "qdrant"

# Keep old name as alias for backward compat in CLI references
COLLECTION = MESSAGES_COLLECTION


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
    """Thin wrapper around embedded Qdrant collections."""

    def __init__(self, path: Path | None = None):
        self.path = path or get_db_path()
        self.path.mkdir(parents=True, exist_ok=True)
        self._client = QdrantClient(path=str(self.path))
        self._embedder = None   # loaded on first call to _embed()
        self._embedder_loaded = False
        self._ensure_collections()

    def _ensure_collections(self) -> None:
        existing = {c.name for c in self._client.get_collections().collections}
        vector_config = VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE)

        if MESSAGES_COLLECTION not in existing:
            self._client.create_collection(
                collection_name=MESSAGES_COLLECTION,
                vectors_config=vector_config,
            )

        if SESSIONS_COLLECTION not in existing:
            self._client.create_collection(
                collection_name=SESSIONS_COLLECTION,
                vectors_config=vector_config,
            )

        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        """Create payload indexes for filter performance (idempotent).

        Note: payload indexes have no effect in embedded Qdrant (local mode).
        They are created here so the code works correctly if switched to
        server mode later.
        """
        import warnings

        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message="Payload indexes have no effect"
            )
            for field_name in ["session_id", "source", "project", "role"]:
                try:
                    self._client.create_payload_index(
                        collection_name=MESSAGES_COLLECTION,
                        field_name=field_name,
                        field_schema=PayloadSchemaType.KEYWORD,
                    )
                except Exception:
                    pass

            for field_name in ["source", "project"]:
                try:
                    self._client.create_payload_index(
                        collection_name=SESSIONS_COLLECTION,
                        field_name=field_name,
                        field_schema=PayloadSchemaType.KEYWORD,
                    )
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Write — messages
    # ------------------------------------------------------------------

    def upsert(self, messages: list[ChatMessage]) -> tuple[int, int]:
        """Insert messages that don't exist yet. Returns (inserted, skipped)."""
        if not messages:
            return 0, 0

        existing_ids = self._existing_ids(
            MESSAGES_COLLECTION, {m.id for m in messages}
        )
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
        self._client.upsert(collection_name=MESSAGES_COLLECTION, points=points)
        return len(new_msgs), len(messages) - len(new_msgs)

    # ------------------------------------------------------------------
    # Write — sessions (unconditional overwrite)
    # ------------------------------------------------------------------

    def upsert_sessions(self, sessions: list[Session]) -> int:
        """Upsert session records (always overwrites). Returns count upserted."""
        if not sessions:
            return 0

        texts = [s.summary for s in sessions]
        vectors = self._embed(texts)

        points = [
            PointStruct(
                id=_id_to_uint(s.id),
                vector=vec,
                payload=s.to_payload(),
            )
            for s, vec in zip(sessions, vectors)
        ]
        self._client.upsert(collection_name=SESSIONS_COLLECTION, points=points)
        return len(sessions)

    # ------------------------------------------------------------------
    # Search — messages
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
        """Semantic search across messages with optional metadata filters."""
        query_vec = self._embed([query])[0]
        flt = self._build_filter(
            source=source, project=project, role=role, session_id=session_id
        )

        response = self._client.query_points(
            collection_name=MESSAGES_COLLECTION,
            query=query_vec,
            query_filter=flt,
            limit=limit,
            with_payload=True,
        )
        results = []
        for r in response.points:
            entry = {"score": r.score, **r.payload}
            # Include the session point ID so the UI can link to the detail view
            sid = r.payload.get("session_id", "")
            src = r.payload.get("source", "")
            if sid and src:
                entry["session_point_id"] = _id_to_uint(
                    Session.make_id(src, sid)
                )
            results.append(entry)
        return results

    # ------------------------------------------------------------------
    # Search — sessions
    # ------------------------------------------------------------------

    def search_sessions(
        self,
        query: str,
        limit: int = 10,
        source: str | None = None,
        project: str | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic search across sessions."""
        query_vec = self._embed([query])[0]
        flt = self._build_filter(source=source, project=project)

        response = self._client.query_points(
            collection_name=SESSIONS_COLLECTION,
            query=query_vec,
            query_filter=flt,
            limit=limit,
            with_payload=True,
        )
        return [
            {"score": r.score, "point_id": r.id, **r.payload}
            for r in response.points
        ]

    # ------------------------------------------------------------------
    # List / get — sessions
    # ------------------------------------------------------------------

    def list_sessions(
        self,
        limit: int = 50,
        source: str | None = None,
        project: str | None = None,
    ) -> list[dict[str, Any]]:
        """List sessions sorted by last_timestamp descending."""
        flt = self._build_filter(source=source, project=project)

        all_sessions: list[dict[str, Any]] = []
        offset = None
        while True:
            records, offset = self._client.scroll(
                collection_name=SESSIONS_COLLECTION,
                limit=min(limit, 1000),
                offset=offset,
                scroll_filter=flt,
                with_payload=True,
            )
            for r in records:
                all_sessions.append({"point_id": r.id, **r.payload})
            if offset is None or len(all_sessions) >= limit:
                break

        all_sessions.sort(
            key=lambda s: s.get("last_timestamp", ""), reverse=True
        )
        return all_sessions[:limit]

    def get_session(self, point_id: int) -> dict[str, Any] | None:
        """Get a single session by its Qdrant point ID."""
        results = self._client.retrieve(
            collection_name=SESSIONS_COLLECTION,
            ids=[point_id],
            with_payload=True,
        )
        if not results:
            return None
        r = results[0]
        return {"point_id": r.id, **r.payload}

    def get_session_messages(
        self,
        session_id: str,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Get all messages for a session, sorted by timestamp."""
        flt = self._build_filter(session_id=session_id)

        messages: list[dict[str, Any]] = []
        offset = None
        while True:
            records, offset = self._client.scroll(
                collection_name=MESSAGES_COLLECTION,
                limit=min(limit, 1000),
                offset=offset,
                scroll_filter=flt,
                with_payload=True,
            )
            for r in records:
                messages.append(r.payload)
            if offset is None or len(messages) >= limit:
                break

        messages.sort(key=lambda m: m.get("timestamp", ""))
        return messages[:limit]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        message_count = self._client.count(MESSAGES_COLLECTION).count
        session_count = self._client.count(SESSIONS_COLLECTION).count

        # Count by source via scroll
        source_counts: dict[str, int] = {}
        offset = None
        while True:
            records, offset = self._client.scroll(
                collection_name=MESSAGES_COLLECTION,
                limit=1000,
                offset=offset,
                with_payload=["source"],
            )
            for r in records:
                src = r.payload.get("source", "unknown")
                source_counts[src] = source_counts.get(src, 0) + 1
            if offset is None:
                break

        embedding_status = (
            "neural (BAAI/bge-small-en-v1.5)"
            if self._embedder
            else "hash-based fallback (offline)"
        )
        return {
            "total_messages": message_count,
            "total_sessions": session_count,
            "by_source": source_counts,
            "db_path": str(self.path),
            "collections": [MESSAGES_COLLECTION, SESSIONS_COLLECTION],
            "embedding_model": embedding_status,
        }

    def delete_by_source(self, source: str) -> int:
        """Delete all messages and sessions from a given source. Returns message count deleted."""
        before = self._client.count(MESSAGES_COLLECTION).count
        source_filter = Filter(
            must=[FieldCondition(key="source", match=MatchValue(value=source))]
        )
        self._client.delete(
            collection_name=MESSAGES_COLLECTION,
            points_selector=source_filter,
        )
        self._client.delete(
            collection_name=SESSIONS_COLLECTION,
            points_selector=source_filter,
        )
        after = self._client.count(MESSAGES_COLLECTION).count
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

    def _existing_ids(self, collection: str, ids: set[str]) -> set[str]:
        uint_ids = [_id_to_uint(i) for i in ids]
        results = self._client.retrieve(
            collection_name=collection,
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
