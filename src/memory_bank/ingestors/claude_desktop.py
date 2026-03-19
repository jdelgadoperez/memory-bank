"""
Ingestor for Claude Desktop data exports.

To export from Claude Desktop:
  Settings > Data & Privacy > Export Data

This produces a directory containing:
  - conversations.json  — chat messages (sender: human/assistant)
  - projects.json       — project prompts and uploaded docs
  - memories.json       — Claude's saved memories about you
  - users.json          — account info (not ingested)

Point the CLI at the export directory or a single JSON file:
  memory-bank ingest claude-desktop -p '~/Downloads/Claude Data Mar 6 2026'
  memory-bank ingest claude-desktop -p conversations.json
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterator

from ..schema import ChatMessage
from .base import BaseIngestor

DEFAULT_DESKTOP_EXPORT = Path.home() / "Library" / "Application Support" / "Claude"

# Sender values in the export → normalized roles
_SENDER_TO_ROLE = {
    "human": "user",
    "assistant": "assistant",
}


def _extract_text_blocks(content: list | str | None) -> str:
    """Extract plain text from Claude Desktop content blocks."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type", "")
        if btype == "text":
            parts.append(block.get("text", ""))
        # Skip thinking blocks — they're internal reasoning
    return "\n".join(p for p in parts if p).strip()


class ClaudeDesktopIngestor(BaseIngestor):
    """
    Ingests Claude Desktop data from an exported directory or JSON file.

    Handles three data types:
    - Conversations (chat_messages with sender/text)
    - Projects (prompt templates and uploaded docs)
    - Memories (Claude's saved knowledge about you)
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
                "  Export data from Claude Desktop: "
                "Settings > Data & Privacy > Export Data\n"
                "  Then run: memory-bank ingest claude-desktop -p /path/to/export/dir"
            )
        return errors

    def iter_messages(self) -> Iterator[ChatMessage]:
        target = self.path

        if target.is_file():
            yield from self._parse_conversations_file(target)
            return

        # Directory: look for each known export file
        conversations_file = target / "conversations.json"
        if conversations_file.exists():
            yield from self._parse_conversations_file(conversations_file)

        projects_file = target / "projects.json"
        if projects_file.exists():
            yield from self._parse_projects_file(projects_file)

        memories_file = target / "memories.json"
        if memories_file.exists():
            yield from self._parse_memories_file(memories_file)

        # Fallback: scan for any JSON files if none of the known files exist
        if not any(
            (target / f).exists()
            for f in ("conversations.json", "projects.json", "memories.json")
        ):
            for f in sorted(target.rglob("*.json")):
                yield from self._parse_conversations_file(f)

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------

    def _parse_conversations_file(self, path: Path) -> Iterator[ChatMessage]:
        data = _load_json(path)
        if data is None:
            return

        # Handle both bare list and {"conversations": [...]}
        conversations = data if isinstance(data, list) else data.get("conversations", [])

        for conv in conversations:
            if not isinstance(conv, dict):
                continue

            conv_id = str(conv.get("uuid", conv.get("id", "")))
            title = conv.get("name", conv.get("title", ""))
            summary = conv.get("summary", "")

            # Support both formats:
            #   Export format: chat_messages with sender/text
            #   Legacy format: messages with role/content
            messages = conv.get("chat_messages", conv.get("messages", []))

            for msg in messages:
                if not isinstance(msg, dict):
                    continue

                # Normalize role from either format
                sender = msg.get("sender", "")
                role = _SENDER_TO_ROLE.get(sender, msg.get("role", ""))
                if role not in ("user", "assistant", "system"):
                    continue

                # Extract text from either format
                text = msg.get("text", "")
                content_blocks = msg.get("content", "")
                if content_blocks and not text:
                    text = _extract_text_blocks(content_blocks)
                elif content_blocks and isinstance(content_blocks, list):
                    # Export format has both text (raw) and content (blocks)
                    # Prefer the structured blocks to skip thinking
                    extracted = _extract_text_blocks(content_blocks)
                    if extracted:
                        text = extracted

                text = str(text).strip()
                if not text:
                    continue

                timestamp = msg.get("created_at", conv.get("created_at", ""))
                msg_id = ChatMessage.make_id(
                    self.source_name, conv_id, role, text, timestamp
                )
                yield ChatMessage(
                    id=msg_id,
                    source=self.source_name,
                    session_id=conv_id,
                    project="",
                    role=role,
                    content=text,
                    timestamp=timestamp,
                    metadata={
                        "title": title,
                        "summary": summary,
                        "conv_updated_at": conv.get("updated_at", ""),
                        "content_type": "conversation",
                    },
                )

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    def _parse_projects_file(self, path: Path) -> Iterator[ChatMessage]:
        data = _load_json(path)
        if not isinstance(data, list):
            return

        for proj in data:
            if not isinstance(proj, dict):
                continue

            proj_id = str(proj.get("uuid", ""))
            proj_name = proj.get("name", "")
            timestamp = proj.get("created_at", "")

            # Ingest the prompt template as a message
            prompt = (proj.get("prompt_template") or "").strip()
            if prompt:
                msg_id = ChatMessage.make_id(
                    self.source_name, proj_id, "system", prompt, timestamp
                )
                yield ChatMessage(
                    id=msg_id,
                    source=self.source_name,
                    session_id=proj_id,
                    project=proj_name,
                    role="system",
                    content=prompt,
                    timestamp=timestamp,
                    metadata={
                        "content_type": "project_prompt",
                        "project_name": proj_name,
                        "project_updated_at": proj.get("updated_at", ""),
                    },
                )

            # Ingest each attached doc
            for doc in proj.get("docs", []):
                if not isinstance(doc, dict):
                    continue
                doc_content = (doc.get("content") or "").strip()
                if not doc_content:
                    continue

                filename = doc.get("filename", "")
                doc_timestamp = doc.get("created_at", timestamp)
                doc_id = ChatMessage.make_id(
                    self.source_name, proj_id, "system", doc_content, doc_timestamp
                )
                yield ChatMessage(
                    id=doc_id,
                    source=self.source_name,
                    session_id=proj_id,
                    project=proj_name,
                    role="system",
                    content=doc_content,
                    timestamp=doc_timestamp,
                    metadata={
                        "content_type": "project_doc",
                        "project_name": proj_name,
                        "filename": filename,
                    },
                )

    # ------------------------------------------------------------------
    # Memories
    # ------------------------------------------------------------------

    def _parse_memories_file(self, path: Path) -> Iterator[ChatMessage]:
        data = _load_json(path)
        if not isinstance(data, list):
            return

        for entry in data:
            if not isinstance(entry, dict):
                continue

            # Conversations memory — a single text blob
            conv_memory = (entry.get("conversations_memory") or "").strip()
            if conv_memory:
                msg_id = ChatMessage.make_id(
                    self.source_name, "memories", "system",
                    conv_memory, "",
                )
                yield ChatMessage(
                    id=msg_id,
                    source=self.source_name,
                    session_id="memories",
                    project="",
                    role="system",
                    content=conv_memory,
                    timestamp="",
                    metadata={
                        "content_type": "memory",
                        "memory_type": "conversations",
                    },
                )

            # Project-specific memories — keyed by project UUID
            proj_memories = entry.get("project_memories", {})
            if isinstance(proj_memories, dict):
                for proj_uuid, memory_text in proj_memories.items():
                    memory_text = str(memory_text).strip()
                    if not memory_text:
                        continue

                    msg_id = ChatMessage.make_id(
                        self.source_name, "memories", "system",
                        memory_text, proj_uuid,
                    )
                    yield ChatMessage(
                        id=msg_id,
                        source=self.source_name,
                        session_id="memories",
                        project=proj_uuid,
                        role="system",
                        content=memory_text,
                        timestamp="",
                        metadata={
                            "content_type": "memory",
                            "memory_type": "project",
                            "project_uuid": proj_uuid,
                        },
                    )


def _load_json(path: Path) -> list | dict | None:
    """Load a JSON file, returning None on error."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
