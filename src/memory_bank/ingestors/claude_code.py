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
            is_subagent = "subagents" in jsonl_path.parts
            agent_type = ""
            parent_session_id = ""

            if is_subagent:
                # Load agent type from companion .meta.json
                meta_path = jsonl_path.with_suffix(".meta.json")
                if meta_path.exists():
                    try:
                        agent_meta = json.loads(meta_path.read_text())
                        agent_type = agent_meta.get("agentType", "")
                    except (json.JSONDecodeError, OSError):
                        pass
                # Parent session is the directory name containing subagents/
                parent_session_id = jsonl_path.parts[-3] if len(jsonl_path.parts) >= 3 else ""

            yield from self._parse_file(
                jsonl_path,
                is_subagent=is_subagent,
                agent_type=agent_type,
                parent_session_id=parent_session_id,
            )

    def _parse_file(
        self,
        path: Path,
        is_subagent: bool = False,
        agent_type: str = "",
        parent_session_id: str = "",
    ) -> Iterator[ChatMessage]:
        # Derive project name from the encoded directory path
        if is_subagent:
            # subagents live at <project>/<session>/subagents/<agent>.jsonl
            project = _decode_project_path(path.parts[-4]) if len(path.parts) >= 4 else ""
        else:
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
                        "is_subagent": is_subagent,
                    }
                    if is_subagent:
                        meta["agent_type"] = agent_type
                        meta["parent_session_id"] = parent_session_id
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

    Uses a greedy filesystem walk to correctly handle project names that
    contain dashes (e.g. 'memory-bank'), which would otherwise be split
    into path segments.
    """
    parts = encoded.lstrip("-").split("-")  # leading dash encodes root /; rest are path components
    current = Path("/")
    i = 0
    while i < len(parts):
        # Try longest match first so dashes in directory names are preserved
        for j in range(len(parts), i, -1):
            candidate = current / "-".join(parts[i:j])
            if candidate.exists():
                current = candidate
                i = j
                break
        else:
            # No filesystem match — return remaining parts joined with dashes
            return "-".join(parts[i:])
    return current.name or encoded
