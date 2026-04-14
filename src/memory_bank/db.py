"""Qdrant vector DB wrapper — embedded or server mode with Docker auto-start."""
from __future__ import annotations

import hashlib
import math
import os
import struct
import subprocess
import time
import urllib.request
import warnings
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Generator

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

QDRANT_DOCKER_URL = "http://localhost:6333"
QDRANT_CONTAINER_NAME = "memory-bank-qdrant"
LARGE_COLLECTION_THRESHOLD = 20_000


class DatabaseLockedError(Exception):
    """Raised when the Qdrant storage directory is locked by another process."""


def get_db_path() -> Path:
    env = os.environ.get("MEMORY_BANK_DB")
    return Path(env) if env else DEFAULT_DB_PATH


# ---------------------------------------------------------------------------
# Qdrant server detection and Docker auto-start
# ---------------------------------------------------------------------------

def _ping_qdrant(url: str = QDRANT_DOCKER_URL, timeout: float = 1.0) -> bool:
    """Return True if a Qdrant server is reachable at *url*.

    Tries /healthz first (Qdrant 1.x+), then falls back to the root endpoint
    for older versions where /healthz does not exist.
    """
    for path in ("/healthz", "/"):
        try:
            urllib.request.urlopen(f"{url}{path}", timeout=timeout)
            return True
        except urllib.error.HTTPError:
            # Server responded but with an error status — keep trying other paths.
            pass
        except Exception:
            return False
    return False


def _docker_daemon_running() -> bool:
    """Return True if the Docker daemon is available on this machine."""
    try:
        r = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=2
        )
        return r.returncode == 0
    except Exception:
        return False


def _ensure_qdrant_container(storage_path: Path) -> bool:
    """Start the memory-bank-qdrant container, creating it if needed.

    Mounts *storage_path* at /qdrant/storage — the same path used by embedded
    mode, so no data migration is needed when switching from embedded to Docker.
    Returns True if the server becomes reachable within ~15 s.
    """
    inspect = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Running}}", QDRANT_CONTAINER_NAME],
        capture_output=True, text=True,
    )
    if inspect.returncode == 0 and inspect.stdout.strip() == "true":
        return True  # already running

    if inspect.returncode == 0:
        # Container exists but stopped
        subprocess.run(["docker", "start", QDRANT_CONTAINER_NAME], capture_output=True)
    else:
        # Create and start a new container
        subprocess.run(
            [
                "docker", "run", "-d",
                "--name", QDRANT_CONTAINER_NAME,
                "-p", "6333:6333",
                "--restart", "unless-stopped",
                "-v", f"{storage_path}:/qdrant/storage:z",
                "qdrant/qdrant",
            ],
            check=True,
            capture_output=True,
        )

    # Wait up to 15 s for the health endpoint
    for _ in range(30):
        if _ping_qdrant():
            return True
        time.sleep(0.5)
    return False


def _resolve_qdrant_url(storage_path: Path) -> str | None:
    """Determine the Qdrant server URL to use, or None for embedded mode.

    Priority:
      1. QDRANT_URL env var — explicit override (custom server / Qdrant Cloud)
      2. localhost:6333 already responding — use it (user running Qdrant manually)
      3. Docker daemon available — start memory-bank-qdrant container and use it
      4. None — fall back to embedded mode
    """
    env_url = os.environ.get("QDRANT_URL")
    if env_url:
        return env_url

    if _ping_qdrant():
        return QDRANT_DOCKER_URL

    if _docker_daemon_running():
        from rich.console import Console
        Console().print(
            "[dim]→ Starting Qdrant via Docker "
            f"({QDRANT_CONTAINER_NAME} on localhost:6333)…[/dim]"
        )
        if _ensure_qdrant_container(storage_path):
            return QDRANT_DOCKER_URL
        Console().print(
            "[yellow]⚠ Docker container failed to start — "
            "falling back to embedded Qdrant.[/yellow]"
        )

    return None  # embedded fallback


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
    """Qdrant collection wrapper supporting embedded and server (Docker) mode.

    On construction, ``_resolve_qdrant_url`` checks for a running Qdrant server
    and auto-starts a Docker container if Docker is available.  If neither is
    possible, embedded mode is used as a fallback.

    The Qdrant client is opened and closed per operation via ``_connect()``,
    allowing the CLI and UI server to share storage without holding long locks.
    The fastembed model is cached on the instance so it only loads once.
    """

    def __init__(self, path: Path | None = None):
        self.path = path or get_db_path()
        self.path.mkdir(parents=True, exist_ok=True)
        self._url: str | None = _resolve_qdrant_url(self.path)
        self._embedder = None   # loaded on first call to _embed()
        self._embedder_loaded = False
        self._collections_verified = False

    @property
    def mode(self) -> str:
        """Return 'server' or 'embedded'."""
        return "server" if self._url else "embedded"

    @contextmanager
    def _connect(self) -> Generator[QdrantClient, None, None]:
        """Acquire the Qdrant client for the duration of an operation."""
        if self._url:
            client = QdrantClient(url=self._url, timeout=3)
        else:
            # Embedded mode — intercept the 20k UserWarning and surface it cleanly
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                try:
                    client = QdrantClient(path=str(self.path))
                except RuntimeError as exc:
                    if "already accessed by another instance" in str(exc):
                        raise DatabaseLockedError(
                            f"Database is locked by another process.\n"
                            f"Storage path: {self.path}\n"
                            f"If the UI server is running, stop it with "
                            f"'memory-bank ui stop' or Ctrl+C,\n"
                            f"or use the UI's built-in search at http://127.0.0.1:6333."
                        ) from exc
                    raise
            for w in caught:
                if (
                    issubclass(w.category, UserWarning)
                    and "Local mode is not recommended" in str(w.message)
                ):
                    from rich.console import Console
                    Console().print(
                        "[yellow]⚠ Collection exceeds 20k points — embedded Qdrant "
                        "may be slow. Install Docker to enable automatic server mode.[/yellow]"
                    )
                else:
                    warnings.warn_explicit(
                        w.message, w.category, w.filename, w.lineno
                    )
        try:
            if not self._collections_verified:
                self._ensure_collection(client)
                self._collections_verified = True
            yield client
        finally:
            client.close()

    def _ensure_collection(self, client: QdrantClient) -> None:
        existing = {c.name for c in client.get_collections().collections}
        if COLLECTION not in existing:
            client.create_collection(
                collection_name=COLLECTION,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            )
        # Payload indexes speed up filtered queries and only work in server mode.
        if self._url:
            from qdrant_client.models import PayloadSchemaType
            for field in ("source", "project", "role", "session_id", "category"):
                try:
                    client.create_payload_index(
                        collection_name=COLLECTION,
                        field_name=field,
                        field_schema=PayloadSchemaType.KEYWORD,
                    )
                except Exception:
                    pass  # index already exists — safe to ignore

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def upsert(self, messages: list[ChatMessage]) -> tuple[int, int]:
        """Insert messages that don't exist yet. Returns (inserted, skipped)."""
        if not messages:
            return 0, 0

        # Check which IDs already exist (brief lock)
        with self._connect() as client:
            existing_ids = self._existing_ids(client, {m.id for m in messages})

        new_msgs = [m for m in messages if m.id not in existing_ids]

        if not new_msgs:
            return 0, len(messages)

        # Embed outside the lock — this is the slow part
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

        # Write points (brief lock)
        with self._connect() as client:
            client.upsert(collection_name=COLLECTION, points=points)

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
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Semantic search with optional metadata and time filters.

        ``since`` and ``before`` are ISO 8601 strings (use :func:`parse_time_expr`
        to convert human-friendly expressions first).  Timestamps are stored as
        ISO strings so comparison is lexicographic — which works correctly as long
        as all timestamps share the same format (guaranteed by the ingestors).
        """
        # Embed outside the lock
        query_vec = self._embed([query])[0]
        flt = self._build_filter(
            source=source, project=project, role=role, session_id=session_id,
            category=category,
        )

        # When time filters are active, over-fetch to compensate for post-filtering.
        fetch_limit = limit * 8 if (since or before) else limit

        with self._connect() as client:
            response = client.query_points(
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
        with self._connect() as client:
            offset = None
            while True:
                batch, offset = client.scroll(
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
        with self._connect() as client:
            offset = None
            while True:
                batch, offset = client.scroll(
                    collection_name=COLLECTION,
                    scroll_filter=flt,
                    limit=1000,
                    offset=offset,
                    with_payload=[
                        "session_id", "source", "project", "timestamp",
                        "role", "content", "model", "git_branch",
                    ],
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
                            "title": "",
                            "title_ts": "",
                            "model": "",
                        }
                    s = sessions[sid]
                    s["message_count"] += 1
                    if ts < s["first_ts"]:
                        s["first_ts"] = ts
                    if ts > s["last_ts"]:
                        s["last_ts"] = ts
                    # Grab title from chronologically first user message
                    if p.get("role") == "user" and ts and (not s["title_ts"] or ts < s["title_ts"]):
                        text = (p.get("content") or "").strip()
                        if text:
                            s["title"] = text[:120] + ("..." if len(text) > 120 else "")
                            s["title_ts"] = ts
                    # Grab model from first message that has it
                    if not s["model"] and p.get("model"):
                        s["model"] = p["model"]
                if offset is None:
                    break

        result = sorted(sessions.values(), key=lambda s: s["last_ts"], reverse=True)
        if limit:
            result = result[:limit]
        for s in result:
            s.pop("title_ts", None)
        return result

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        with self._connect() as client:
            count = client.count(COLLECTION).count

            # Count by source via scroll
            source_counts: dict[str, int] = {}
            offset = None
            while True:
                records, offset = client.scroll(
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
        with self._connect() as client:
            before_count = client.count(COLLECTION).count
            client.delete(
                collection_name=COLLECTION,
                points_selector=Filter(
                    must=[FieldCondition(key="source", match=MatchValue(value=source))]
                ),
            )
            after_count = client.count(COLLECTION).count
        return before_count - after_count

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
        with self._connect() as client:
            offset = None
            while True:
                batch, offset = client.scroll(
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
        with self._connect() as client:
            for i in range(0, len(to_delete), 1000):
                client.delete(
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

    def _existing_ids(self, client: QdrantClient, ids: set[str]) -> set[str]:
        uint_ids = [_id_to_uint(i) for i in ids]
        results = client.retrieve(
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
