"""
Memory Bank MCP Server

Exposes search_memory, get_session, and list_sessions as native MCP tools.
Run via: memory-bank mcp
"""
from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .db import MemoryDB, parse_time_expr

_DEFAULT_SNIPPET = 300
_DEFAULT_LIMIT = 5
_DEFAULT_MIN_SCORE = 0.5


def _compact_message(r: dict, snippet: int | None = _DEFAULT_SNIPPET) -> dict:
    """Compact a DB result for LLM consumption."""
    text = r.get("content", "")
    if snippet and len(text) > snippet:
        text = text[:snippet] + "…"
    out: dict[str, Any] = {
        "score": round(r.get("score", 0.0), 2) if "score" in r else None,
        "role": r.get("role", ""),
        "src": r.get("source", ""),
        "date": (r.get("timestamp") or "")[:10],
        "text": text,
    }
    if out["score"] is None:
        del out["score"]
    if r.get("project"):
        out["proj"] = r["project"]
    if r.get("session_id"):
        out["sid"] = r["session_id"]
    return out


def run_mcp_server(db: MemoryDB) -> None:
    """Start the FastMCP server over stdio."""
    mcp = FastMCP(
        name="memory-bank",
        instructions=(
            "Search and replay past Claude chat history stored in the local vector DB. "
            "Use search_memory to find relevant past conversations, "
            "list_sessions to enumerate sessions, "
            "and get_session to replay a full session in order."
        ),
    )

    @mcp.tool()
    def search_memory(
        query: str,
        limit: int = _DEFAULT_LIMIT,
        min_score: float = _DEFAULT_MIN_SCORE,
        source: str | None = None,
        project: str | None = None,
        role: str | None = None,
        session_id: str | None = None,
        since: str | None = None,
        before: str | None = None,
        snippet: int = _DEFAULT_SNIPPET,
    ) -> str:
        """
        Semantic search over ingested Claude chat history.

        Returns ranked results as compact JSON. Each result includes score,
        role, source (src), date, text snippet, and optionally project (proj)
        and session_id (sid).

        Args:
            query: Natural-language search query.
            limit: Maximum number of results (default 5).
            min_score: Minimum similarity score 0–1 (default 0.5).
            source: Filter by source, e.g. "claude-code" or "claude-desktop".
            project: Filter by project name.
            role: Filter by role — "user" or "assistant".
            session_id: Restrict to a specific session.
            since: Only return results after this time. Accepts "7d", "2025-01-01", etc.
            before: Only return results before this time. Same format as since.
            snippet: Truncate each result's text to N chars (default 300).
        """
        import json

        since_iso = parse_time_expr(since) if since else None
        before_iso = parse_time_expr(before) if before else None

        results = db.search(
            query=query,
            limit=limit,
            source=source,
            project=project,
            role=role,
            session_id=session_id,
            since=since_iso,
            before=before_iso,
        )
        results = [r for r in results if r.get("score", 0) >= min_score]
        return json.dumps([_compact_message(r, snippet) for r in results])

    @mcp.tool()
    def list_sessions(
        source: str | None = None,
        project: str | None = None,
        since: str | None = None,
        before: str | None = None,
        limit: int = 20,
    ) -> str:
        """
        List indexed sessions with metadata, newest first.

        Returns JSON array of session objects with fields:
        session_id, source, project, first_ts, last_ts, message_count.

        Args:
            source: Filter by source (e.g. "claude-code").
            project: Filter by project name.
            since: Only show sessions with activity after this time ("7d", "2025-01-01", …).
            before: Only show sessions with activity before this time.
            limit: Maximum number of sessions to return (default 20).
        """
        import json

        since_iso = parse_time_expr(since) if since else None
        before_iso = parse_time_expr(before) if before else None

        result = db.list_sessions(
            source=source,
            project=project,
            since=since_iso,
            before=before_iso,
            limit=limit,
        )
        return json.dumps(result)

    @mcp.tool()
    def get_session(session_id: str, snippet: int = _DEFAULT_SNIPPET) -> str:
        """
        Replay a full session in chronological order.

        Returns JSON array of messages with fields:
        role, timestamp (date), text, source, project.

        Args:
            session_id: The session ID to retrieve (from list_sessions or search results).
            snippet: Truncate each message to N chars (default 300, 0 = no truncation).
        """
        import json

        messages = db.get_session(session_id)
        return json.dumps([_compact_message(r, snippet or None) for r in messages])

    mcp.run(transport="stdio")
