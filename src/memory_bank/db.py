"""Qdrant vector DB wrapper — embedded, no server required."""
from __future__ import annotations

import hashlib
import math
import os
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    Range,
    VectorParams,
)

from .schema import ChatMessage

COLLECTION = "chat_history"
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"   # fast, 384-dim, runs locally via fastembed
VECTOR_SIZE = 384

DEFAULT_DB_PATH = Path.home() / ".memory-bank" / "qdrant"


def get_db_path() -> Path:
    env = os.environ.get("MEMORY_BANK_DB")
    return Path(env) if env else DEFAULT_DB_PATH


def parse_time_expr(expr: str) -> str:
    """
    Parse a time expression to an ISO 8601 UTC string.

    Accepts:
      - Relative: "7d", "30d", "2w", "1y"
      - Absolute: "2025-01-01", "2025-01-01T12:00:00", or any dateutil-parseable string
    Returns an ISO 8601 string like "2025-01-01T00:00:00+00:00".
    """
    import re

    expr = expr.strip()
    m = re.fullmatch(r"(\d+)([dwmy])", expr, re.IGNORECASE)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        delta_map = {"d": 1, "w": 7, "m": 30, "y": 365}
        dt = datetime.now(timezone.utc) - timedelta(days=n * delta_map[unit])
        return dt.isoformat()
    # Absolute date — parse with dateutil
    from dateutil import parser as dtp
    dt = dtp.parse(expr)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


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
        # Payload index on source speeds up stats/filter queries.
        # No-op in local (embedded) mode but good practice for server deployments.
        try:
            self._client.create_payload_index(
                collection_name=COLLECTION,
                field_name="source",
                field_schema="keyword",
            )
        except Exception:
            pass  # Already exists or unsupported — harmless

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
        since: str | None = None,
        before: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Semantic search with optional metadata and time filters.

        ``since`` and ``before`` are ISO 8601 strings (use :func:`parse_time_expr`
        to convert human-friendly expressions first).  Timestamps are stored as
        ISO strings so comparison is lexicographic — which works correctly as long
        as all timestamps share the same format (guaranteed by the ingestors).
        """
        query_vec = self._embed([query])[0]
        flt = self._build_filter(
            source=source, project=project, role=role, session_id=session_id
        )

        # When time filters are active, over-fetch to compensate for post-filtering.
        fetch_limit = limit * 8 if (since or before) else limit

        response = self._client.query_points(
            collection_name=COLLECTION,
            query=query_vec,
            query_filter=flt,
            limit=fetch_limit,
            with_payload=True,
        )
        results = [{"score": r.score, **r.payload} for r in response.points]

        # Post-filter by timestamp (ISO string lexicographic comparison is correct
        # for consistently-formatted timestamps from our ingestors).
        if since:
            results = [r for r in results if (r.get("timestamp") or "") >= since]
        if before:
            results = [r for r in results if (r.get("timestamp") or "") <= before]

        return results[:limit]

    # ------------------------------------------------------------------
    # Context fetch (for --context N in search)
    # ------------------------------------------------------------------

    def get_context(
        self,
        session_id: str,
        timestamp: str,
        n: int = 3,
    ) -> list[dict[str, Any]]:
        """
        Return the N messages before and N messages after *timestamp* within
        *session_id*, ordered chronologically.  The matched message itself is
        NOT included (the caller already has it).
        """
        all_msgs = self.get_session(session_id)
        if not all_msgs:
            return []

        timestamps = [m.get("timestamp", "") for m in all_msgs]
        # Find the index of the closest message
        try:
            idx = timestamps.index(timestamp)
        except ValueError:
            # Timestamp not found exactly — find nearest
            idx = min(range(len(timestamps)), key=lambda i: abs(timestamps[i] != timestamp))

        start = max(0, idx - n)
        end = min(len(all_msgs), idx + n + 1)
        return [m for i, m in enumerate(all_msgs[start:end]) if (start + i) != idx]

    # ------------------------------------------------------------------
    # Session operations
    # ------------------------------------------------------------------

    def get_session(self, session_id: str) -> list[dict[str, Any]]:
        """Return all messages from a session, sorted chronologically."""
        flt = Filter(
            must=[FieldCondition(key="session_id", match=MatchValue(value=session_id))]
        )
        records: list[dict[str, Any]] = []
        offset = None
        while True:
            batch, offset = self._client.scroll(
                collection_name=COLLECTION,
                scroll_filter=flt,
                limit=500,
                offset=offset,
                with_payload=True,
            )
            records.extend(r.payload for r in batch)
            if offset is None:
                break
        records.sort(key=lambda r: r.get("timestamp", ""))
        return records

    def list_sessions(
        self,
        source: str | None = None,
        project: str | None = None,
        since: str | None = None,
        before: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        List all sessions with metadata (id, project, source, date, message count).
        Returns sessions sorted newest-first.
        """
        flt = self._build_filter(source=source, project=project)

        sessions: dict[str, dict[str, Any]] = {}
        offset = None
        while True:
            batch, offset = self._client.scroll(
                collection_name=COLLECTION,
                scroll_filter=flt,
                limit=1000,
                offset=offset,
                with_payload=["session_id", "source", "project", "timestamp"],
            )
            for r in batch:
                p = r.payload
                ts = p.get("timestamp", "")
                # Apply time filters
                if since and ts < since:
                    continue
                if before and ts > before:
                    continue
                sid = p.get("session_id", "")
                if sid not in sessions:
                    sessions[sid] = {
                        "session_id": sid,
                        "source": p.get("source", ""),
                        "project": p.get("project", ""),
                        "first_ts": ts,
                        "last_ts": ts,
                        "message_count": 0,
                    }
                s = sessions[sid]
                s["message_count"] += 1
                if ts < s["first_ts"]:
                    s["first_ts"] = ts
                if ts > s["last_ts"]:
                    s["last_ts"] = ts
            if offset is None:
                break

        result = sorted(sessions.values(), key=lambda s: s["last_ts"], reverse=True)
        if limit:
            result = result[:limit]
        return result

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

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

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

    def delete_before(
        self,
        timestamp_iso: str,
        source: str | None = None,
    ) -> int:
        """
        Delete messages with timestamp < *timestamp_iso*.
        Optionally scope to a single source.  Returns count deleted.
        """
        # Collect IDs to delete via scroll (timestamp comparison is string-lexicographic)
        conditions: list[FieldCondition] = []
        if source:
            conditions.append(FieldCondition(key="source", match=MatchValue(value=source)))
        flt = Filter(must=conditions) if conditions else None

        to_delete: list[int] = []
        offset = None
        while True:
            batch, offset = self._client.scroll(
                collection_name=COLLECTION,
                scroll_filter=flt,
                limit=1000,
                offset=offset,
                with_payload=["timestamp"],
                with_vectors=False,
            )
            for r in batch:
                ts = r.payload.get("timestamp", "")
                if ts < timestamp_iso:
                    to_delete.append(r.id)
            if offset is None:
                break

        if not to_delete:
            return 0

        # Delete in batches of 1000
        for i in range(0, len(to_delete), 1000):
            self._client.delete(
                collection_name=COLLECTION,
                points_selector=to_delete[i : i + 1000],
            )
        return len(to_delete)

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
