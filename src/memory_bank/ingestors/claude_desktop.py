"""
Ingestor for Claude Desktop chat history (macOS).

Claude Desktop stores conversations in:
  ~/Library/Application Support/Claude/

The storage format is a LevelDB/IndexedDB database (Electron app).
We support two extraction strategies:
  1. JSON export files  — if you've exported conversations as JSON
  2. Auto-detection     — scan for known file patterns

To export from Claude Desktop:
  Settings > Data & Privacy > Export Conversations → saves conversations.json

Expected JSON export format (Claude Desktop export):
  {
    "conversations": [
      {
        "id": "conv_abc123",
        "title": "My conversation",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-02T00:00:00Z",
        "messages": [
          {"id": "msg_1", "role": "user", "content": "Hello", "created_at": "..."},
          {"id": "msg_2", "role": "assistant", "content": "Hi there!", "created_at": "..."}
        ]
      }
    ]
  }

If the format differs, use the CustomIngestor with a mapper function instead.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterator

from ..schema import ChatMessage
from .base import BaseIngestor

DEFAULT_DESKTOP_EXPORT = Path.home() / "Library" / "Application Support" / "Claude"


class ClaudeDesktopIngestor(BaseIngestor):
    """
    Ingests Claude Desktop conversations from an exported JSON file or directory.

    Pass the path to either:
    - A single JSON export file (conversations.json)
    - A directory containing multiple JSON export files
    """

    source_name = "claude-desktop"

    def __init__(self, path: Path | None = None):
        env = os.environ.get("CLAUDE_DESKTOP_PATH")
        self.path = Path(env) if env else (path or DEFAULT_DESKTOP_EXPORT)

    def validate(self) -> list[str]:
        errors = []
        if not self.path.exists():
            errors.append(
                f"Claude Desktop path not found: {self.path}\n"
                "  Export conversations from Claude Desktop: "
                "Settings > Data & Privacy > Export Conversations\n"
                "  Then run: memory-bank ingest claude-desktop --path /path/to/conversations.json"
            )
        return errors

    def iter_messages(self) -> Iterator[ChatMessage]:
        target = self.path
        if target.is_dir():
            files = list(target.rglob("*.json"))
        else:
            files = [target]

        for f in files:
            yield from self._parse_file(f)

    def _parse_file(self, path: Path) -> Iterator[ChatMessage]:
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return

        # Handle both {"conversations": [...]} and a bare list
        conversations = data if isinstance(data, list) else data.get("conversations", [])

        for conv in conversations:
            conv_id = str(conv.get("id", ""))
            title = conv.get("title", "")
            messages = conv.get("messages", [])

            for msg in messages:
                role = msg.get("role", "")
                if role not in ("user", "assistant", "system"):
                    continue

                content = msg.get("content", "")
                if isinstance(content, list):
                    # Handle content blocks (same structure as API)
                    parts = [
                        b.get("text", "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    ]
                    content = "\n".join(parts)
                content = str(content).strip()
                if not content:
                    continue

                timestamp = msg.get("created_at", conv.get("created_at", ""))
                msg_id = ChatMessage.make_id(
                    self.source_name, conv_id, role, content, timestamp
                )
                yield ChatMessage(
                    id=msg_id,
                    source=self.source_name,
                    session_id=conv_id,
                    project="",
                    role=role,
                    content=content,
                    timestamp=timestamp,
                    metadata={
                        "title": title,
                        "conv_updated_at": conv.get("updated_at", ""),
                    },
                )
