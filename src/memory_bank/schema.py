"""Common data schema for all ingested chat messages."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any


@dataclass
class ChatMessage:
    """Canonical representation of a single chat turn stored in the vector DB."""

    # Identity
    id: str                          # Deterministic SHA-256 hash of source+session+role+content
    source: str                      # "claude-code" | "claude-desktop" | custom string
    session_id: str                  # Conversation/session identifier
    project: str                     # Project name or path (empty string if unknown)

    # Content
    role: str                        # "user" | "assistant" | "system"
    content: str                     # Plain text content of the message

    # Timestamps
    timestamp: str                   # ISO 8601 string

    # Extras stored as Qdrant payload (filterable)
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def make_id(source: str, session_id: str, role: str, content: str, timestamp: str) -> str:
        """Deterministic ID so re-ingesting the same message is idempotent."""
        raw = f"{source}:{session_id}:{role}:{timestamp}:{content[:256]}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def to_payload(self) -> dict[str, Any]:
        """Flat dict for Qdrant payload (no nested dicts for top-level filterable fields)."""
        return {
            "id": self.id,
            "source": self.source,
            "session_id": self.session_id,
            "project": self.project,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            **self.metadata,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ChatMessage":
        known = {"id", "source", "session_id", "project", "role", "content", "timestamp"}
        metadata = {k: v for k, v in payload.items() if k not in known}
        return cls(
            id=payload["id"],
            source=payload["source"],
            session_id=payload["session_id"],
            project=payload["project"],
            role=payload["role"],
            content=payload["content"],
            timestamp=payload["timestamp"],
            metadata=metadata,
        )


@dataclass
class Session:
    """A conversation session — groups related ChatMessages together."""

    # Identity
    id: str                          # Deterministic hash from source + session_id
    source: str                      # "claude-code" | "claude-desktop" | custom string
    session_id: str                  # Original session UUID (from JSONL filename)
    project: str                     # Decoded project name (leaf component)

    # Display / search
    title: str                       # slug if available, else truncated first user message
    summary: str                     # Text used for vector embedding

    # Aggregates
    message_count: int
    first_timestamp: str             # ISO 8601
    last_timestamp: str              # ISO 8601

    # Top-level filterable field
    model: str                       # Primary model used in session

    # Extras
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def make_id(source: str, session_id: str) -> str:
        """Deterministic ID from source + session UUID."""
        raw = f"{source}:{session_id}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def to_payload(self) -> dict[str, Any]:
        """Flat dict for Qdrant payload."""
        return {
            "id": self.id,
            "source": self.source,
            "session_id": self.session_id,
            "project": self.project,
            "title": self.title,
            "summary": self.summary,
            "message_count": self.message_count,
            "first_timestamp": self.first_timestamp,
            "last_timestamp": self.last_timestamp,
            "model": self.model,
            **self.metadata,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Session":
        known = {
            "id", "source", "session_id", "project", "title", "summary",
            "message_count", "first_timestamp", "last_timestamp", "model",
        }
        metadata = {k: v for k, v in payload.items() if k not in known}
        return cls(
            id=payload["id"],
            source=payload["source"],
            session_id=payload["session_id"],
            project=payload["project"],
            title=payload.get("title", ""),
            summary=payload.get("summary", ""),
            message_count=payload.get("message_count", 0),
            first_timestamp=payload.get("first_timestamp", ""),
            last_timestamp=payload.get("last_timestamp", ""),
            model=payload.get("model", ""),
            metadata=metadata,
        )


@dataclass
class IngestResult:
    """Summary returned after an ingest run."""
    source: str
    total_found: int = 0
    inserted: int = 0
    skipped: int = 0       # already existed (idempotent)
    sessions_upserted: int = 0
    errors: int = 0
    error_details: list[str] = field(default_factory=list)
