"""
Ingestor for ChatGPT data exports.

To export from ChatGPT:
  Settings > Data Controls > Export Data

This produces a directory containing:
  - conversations.json  — all chat conversations (tree-structured messages)
  - user.json           — account info (not ingested)
  - message_feedback.json — thumbs up/down on messages (not ingested)
  - Various uploaded files and DALL-E generations

Point the CLI at the export directory or the conversations.json file directly:
  memory-bank ingest chatgpt -p '~/Documents/ai/ChatGPT Backup Sept 22 2025'
  memory-bank ingest chatgpt -p conversations.json
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from ..schema import ChatMessage
from .base import BaseIngestor

_ROLE_ALLOWLIST = {"user", "assistant"}


def _extract_text_parts(content: dict) -> str:
    """Extract plain text from a ChatGPT message content object.

    ChatGPT stores content as {"content_type": "text", "parts": [...]}.
    Parts are usually strings but can be dicts (image/audio references).
    """
    content_type = content.get("content_type", "")
    if content_type not in ("text", "code"):
        return ""

    parts: list[str] = []
    for part in content.get("parts", []):
        if isinstance(part, str) and part.strip():
            parts.append(part.strip())
    return "\n".join(parts)


def _unix_to_iso(ts: float | int | None) -> str:
    """Convert a Unix timestamp to ISO 8601 string."""
    if ts is None or ts == 0:
        return ""
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except (OSError, ValueError, OverflowError):
        return ""


class ChatGPTIngestor(BaseIngestor):
    """
    Ingests ChatGPT conversations from an exported directory or JSON file.

    ChatGPT exports use a tree structure (mapping) where each node has a
    message, parent, and children. Messages are extracted and sorted by
    creation time to produce a linear conversation.
    """

    source_name = "chatgpt"

    def __init__(self, path: Path | None = None):
        self.path = path or Path(".")

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.path.exists():
            errors.append(
                f"ChatGPT export path not found: {self.path}\n"
                "  Export data from ChatGPT: "
                "Settings > Data Controls > Export Data\n"
                "  Then run: memory-bank ingest chatgpt -p /path/to/export/dir"
            )
            return errors

        target = self._find_conversations_file()
        if target is None:
            errors.append(
                f"No conversations.json found in: {self.path}\n"
                "  Expected a ChatGPT data export directory or conversations.json file."
            )
        return errors

    def _find_conversations_file(self) -> Path | None:
        if self.path.is_file() and self.path.suffix == ".json":
            return self.path
        if self.path.is_dir():
            candidate = self.path / "conversations.json"
            if candidate.exists():
                return candidate
        return None

    def iter_messages(self) -> Iterator[ChatMessage]:
        target = self._find_conversations_file()
        if target is None:
            return

        data = _load_json(target)
        if not isinstance(data, list):
            return

        for conv in data:
            if not isinstance(conv, dict):
                continue
            yield from self._parse_conversation(conv)

    def _parse_conversation(self, conv: dict) -> Iterator[ChatMessage]:
        conv_id = conv.get("conversation_id") or conv.get("id", "")
        if not conv_id:
            return

        title = conv.get("title", "")
        default_model = conv.get("default_model_slug", "")
        mapping = conv.get("mapping", {})

        if not isinstance(mapping, dict):
            return

        # Collect all user/assistant text messages and sort by create_time
        messages: list[tuple[float, ChatMessage]] = []

        for node in mapping.values():
            msg = node.get("message") if isinstance(node, dict) else None
            if not isinstance(msg, dict):
                continue

            author = msg.get("author", {})
            role = author.get("role", "") if isinstance(author, dict) else ""
            if role not in _ROLE_ALLOWLIST:
                continue

            content = msg.get("content", {})
            if not isinstance(content, dict):
                continue

            text = _extract_text_parts(content)
            if not text:
                continue

            create_time: float = msg.get("create_time") or 0
            timestamp = _unix_to_iso(create_time)

            metadata = msg.get("metadata", {})
            model = metadata.get("model_slug", "") if isinstance(metadata, dict) else ""

            msg_id = ChatMessage.make_id(
                self.source_name, conv_id, role, text, timestamp,
            )
            chat_msg = ChatMessage(
                id=msg_id,
                source=self.source_name,
                session_id=conv_id,
                project="",
                role=role,
                content=text,
                timestamp=timestamp,
                metadata={
                    "title": title,
                    "model": model or default_model,
                    "content_type": "conversation",
                },
            )
            messages.append((create_time, chat_msg))

        # Yield in chronological order
        messages.sort(key=lambda pair: pair[0])
        for _, chat_msg in messages:
            yield chat_msg


def _load_json(path: Path) -> list | dict | None:
    """Load a JSON file, returning None on error."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
