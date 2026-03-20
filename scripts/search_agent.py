#!/usr/bin/env python3
"""
Memory Bank Search Agent

An interactive agent that answers questions about your past Claude conversations
using the Anthropic API + memory-bank vector DB search.

Usage:
    python scripts/search_agent.py
    python scripts/search_agent.py "What did I work on last week?"
    ANTHROPIC_API_KEY=sk-... python scripts/search_agent.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Allow running from repo root without installing
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import anthropic
from memory_bank.db import MemoryDB

SYSTEM_PROMPT = """\
You are a personal memory assistant with access to the user's past Claude chat history.
When asked about past conversations: call search_memory, synthesize an answer, quote briefly where useful.
If results are sparse, retry with a rephrased query. Be concise. Cite src, proj, date.
"""

# Compact tool schema — descriptions kept short to minimise prompt tokens.
TOOLS = [
    {
        "name": "search_memory",
        "description": "Semantic search over ingested Claude chat history. Returns ranked results.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Max results (default 5)"},
                "min_score": {
                    "type": "number",
                    "description": "Minimum similarity score 0–1 (default 0.5)",
                },
                "source": {
                    "type": "string",
                    "description": "Filter by source: claude-code | claude-desktop",
                },
                "project": {"type": "string", "description": "Filter by project name"},
                "role": {
                    "type": "string",
                    "enum": ["user", "assistant"],
                    "description": "Filter by role",
                },
                "session_id": {"type": "string", "description": "Filter to a specific session"},
                "snippet": {
                    "type": "integer",
                    "description": "Truncate each result's text to N chars (default 300)",
                },
            },
            "required": ["query"],
        },
    }
]

_DEFAULT_SNIPPET = 300
_DEFAULT_LIMIT = 5
_DEFAULT_MIN_SCORE = 0.5


def run_search_tool(db: MemoryDB, tool_input: dict) -> str:
    results = db.search(
        query=tool_input["query"],
        limit=tool_input.get("limit", _DEFAULT_LIMIT),
        source=tool_input.get("source"),
        project=tool_input.get("project"),
        role=tool_input.get("role"),
        session_id=tool_input.get("session_id"),
    )
    if not results:
        return "[]"

    min_score = tool_input.get("min_score", _DEFAULT_MIN_SCORE)
    snippet = tool_input.get("snippet", _DEFAULT_SNIPPET)
    results = [r for r in results if r.get("score", 0) >= min_score]

    def _compact(r: dict) -> dict:
        text = r.get("content", "")
        if snippet and len(text) > snippet:
            text = text[:snippet] + "…"
        out: dict = {
            "score": round(r["score"], 2),
            "role": r.get("role", ""),
            "src": r.get("source", ""),
            "date": (r.get("timestamp") or "")[:10],
            "text": text,
        }
        if r.get("project"):
            out["proj"] = r["project"]
        if r.get("session_id"):
            out["sid"] = r["session_id"]
        return out

    return json.dumps([_compact(r) for r in results])


def agent_loop(client: anthropic.Anthropic, db: MemoryDB, user_message: str) -> str:
    messages = [{"role": "user", "content": user_message}]

    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        # Collect text output and tool calls
        tool_uses = []
        text_parts = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_uses.append(block)

        if response.stop_reason == "end_turn" or not tool_uses:
            return "\n".join(text_parts)

        # Execute tool calls
        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for tool_use in tool_uses:
            result = run_search_tool(db, tool_use.input)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": result,
            })
        messages.append({"role": "user", "content": tool_results})


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set.", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    db = MemoryDB()

    s = db.stats()
    if s["total_messages"] == 0:
        print("Warning: No messages in DB. Run 'memory-bank ingest claude-code' first.")

    # Single query mode
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        answer = agent_loop(client, db, query)
        print(answer)
        return

    # Interactive mode
    print("Memory Bank Search Agent (type 'quit' to exit)")
    print(f"DB: {s['db_path']} | {s['total_messages']} messages indexed")
    print("-" * 60)
    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break
        if not user_input or user_input.lower() in ("quit", "exit", "q"):
            break
        answer = agent_loop(client, db, user_input)
        print(f"\nAssistant: {answer}")


if __name__ == "__main__":
    main()
