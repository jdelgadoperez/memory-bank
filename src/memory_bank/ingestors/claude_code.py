"""Ingestor for Claude Code chat history (JSONL files under ~/.claude/projects/)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterator

from ..schema import ChatMessage
from .base import BaseIngestor

DEFAULT_CLAUDE_DIR = Path.home() / ".claude" / "projects"


def _extract_text(content: str | list | None) -> str:
    """Flatten Claude's content field to plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    # Array of content blocks
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type", "")
        if btype == "text":
            parts.append(block.get("text", ""))
        elif btype == "thinking":
            # Skip internal thinking blocks
            pass
        elif btype == "tool_use":
            name = block.get("name", "tool")
            inp = block.get("input", {})
            parts.append(f"[tool:{name} {json.dumps(inp)[:200]}]")
        elif btype == "tool_result":
            inner = block.get("content", "")
            parts.append(f"[tool_result: {_extract_text(inner)[:200]}]")
    return "\n".join(p for p in parts if p).strip()


class ClaudeCodeIngestor(BaseIngestor):
    """
    Reads all *.jsonl session files from ~/.claude/projects/ (or a custom path).

    Each session file is a newline-delimited JSON file where lines have
    type "user" or "assistant" (others are skipped).
    """

    source_name = "claude-code"

    def __init__(self, claude_dir: Path | None = None):
        env = os.environ.get("CLAUDE_PROJECTS_DIR")
        self.claude_dir = Path(env) if env else (claude_dir or DEFAULT_CLAUDE_DIR)

    def validate(self) -> list[str]:
        if not self.claude_dir.exists():
            return [f"Claude projects directory not found: {self.claude_dir}"]
        return []

    def iter_messages(self) -> Iterator[ChatMessage]:
        for jsonl_path in sorted(self.claude_dir.rglob("*.jsonl")):
            # Skip subagent files — they duplicate content already in the main session
            if "subagents" in jsonl_path.parts:
                continue
            yield from self._parse_file(jsonl_path)

    def _parse_file(self, path: Path) -> Iterator[ChatMessage]:
        # Derive project name from the directory name (encoded as -home-user-myproject)
        project = _decode_project_path(path.parts[-2]) if len(path.parts) >= 2 else ""
        session_id = path.stem  # filename without .jsonl

        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    msg_type = obj.get("type")
                    if msg_type not in ("user", "assistant"):
                        continue

                    message = obj.get("message", {})
                    role = message.get("role", msg_type)
                    raw_content = message.get("content", "")
                    text = _extract_text(raw_content)
                    if not text:
                        continue

                    timestamp = obj.get("timestamp", "")
                    meta: dict = {
                        "git_branch": obj.get("gitBranch", ""),
                        "cwd": obj.get("cwd", ""),
                        "version": obj.get("version", ""),
                        "is_sidechain": obj.get("isSidechain", False),
                        "user_type": obj.get("userType", ""),
                        "slug": obj.get("slug", ""),
                    }
                    if msg_type == "assistant":
                        msg_obj = obj.get("message", {})
                        meta["model"] = msg_obj.get("model", "")

                    msg_id = ChatMessage.make_id(
                        self.source_name, session_id, role, text, timestamp
                    )
                    yield ChatMessage(
                        id=msg_id,
                        source=self.source_name,
                        session_id=session_id,
                        project=project,
                        role=role,
                        content=text,
                        timestamp=timestamp,
                        metadata=meta,
                    )
        except OSError:
            return


def _decode_project_path(encoded: str) -> str:
    """
    Claude Code encodes project paths by replacing / with -.
    e.g. '-home-user-my-project' -> '/home/user/my-project'
    We return just the last component as the project name.
    """
    decoded = encoded.replace("-", "/").lstrip("/")
    return decoded.split("/")[-1] if decoded else encoded
