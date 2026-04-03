# Memory Bank

Local vector DB for ingesting and searching AI chat histories (Claude Code, Claude Desktop, ChatGPT).

## Setup

```bash
uv pip install -e .
# Optional: MCP server support
uv pip install -e ".[mcp]"
```

The `memory-bank` CLI is now available. The Qdrant DB is stored at `~/.memory-bank/qdrant/` by default.

## Quick start

```bash
# 1. Ingest Claude Code history
memory-bank ingest claude-code

# 2. Ingest ChatGPT history
memory-bank ingest chatgpt -p '~/Documents/ChatGPT Export'

# 3. Search
memory-bank search "authentication bug fix"
memory-bank search "docker networking" --since 7d --context 3

# 4. Browse sessions
memory-bank sessions --project my-app
memory-bank session abc123def456

# 5. Stats
memory-bank stats
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `MEMORY_BANK_DB` | `~/.memory-bank/qdrant` | Override DB storage path |
| `CLAUDE_PROJECTS_DIR` | `~/.claude/projects` | Override Claude Code source path |
| `CLAUDE_DESKTOP_PATH` | `~/Library/Application Support/Claude` | Override Claude Desktop source path |
| `ANTHROPIC_API_KEY` | — | Required for the search agent script |

## Auto-ingest via hooks

Keep your DB current automatically by hooking into Claude Code's session lifecycle:

```bash
# Install a Stop hook (runs ingest after each session — recommended)
memory-bank hooks install

# Install a SessionStart hook (writes a context summary at session start)
memory-bank hooks install --on start

# Or both
memory-bank hooks install --on both

# Check what's installed
memory-bank hooks status

# Remove all memory-bank hooks
memory-bank hooks uninstall
```

The Stop hook runs `memory-bank ingest claude-code` in the background and appends
output to `~/.memory-bank/ingest.log`.

The SessionStart hook searches for past work related to the current git project
and writes a brief summary to `~/.memory-bank/context.md`.

## MCP server

Run memory-bank as a native MCP server so Claude can call `search_memory`,
`get_session`, and `list_sessions` as tools without any shell-out or SKILL.md:

```bash
memory-bank mcp
```

Add to `claude_desktop_config.json` (Claude Desktop) or Claude Code `settings.json`:

```json
{
  "mcpServers": {
    "memory-bank": {
      "command": "memory-bank",
      "args": ["mcp"]
    }
  }
}
```

## CLI reference

```
memory-bank ingest claude-code [--path PATH]
memory-bank ingest claude-desktop --path PATH
memory-bank ingest chatgpt --path PATH
memory-bank ingest all
memory-bank ingest custom          # show Python API usage for custom sources

memory-bank search QUERY [--limit N] [--source SOURCE] [--project PROJECT]
                         [--role user|assistant] [--session ID]
                         [--since EXPR] [--before EXPR] [--context N]
                         [--min-score FLOAT] [--current-project] [--dedupe]
                         [--agent] [--snippet N] [--json]

memory-bank sessions [--source SOURCE] [--project PROJECT]
                     [--since EXPR] [--before EXPR] [--limit N] [--json]

memory-bank session SESSION_ID [--json]

memory-bank stats
memory-bank delete [SOURCE] [--since EXPR] [--yes]
memory-bank ui [-p PORT] [-B|--no-browser] [--db PATH]
memory-bank ui start               # background daemon
memory-bank ui stop
memory-bank ui restart
memory-bank ui status
memory-bank ui dev                 # auto-reload on source changes
memory-bank mcp

memory-bank setup install [--skip-hooks] [--on stop|start|both]
memory-bank setup uninstall
memory-bank setup status

memory-bank hooks install [--on stop|start|both]
memory-bank hooks uninstall
memory-bank hooks status
```

### Time expressions (`--since` / `--before`)

Accepted everywhere a time filter is available:

| Expression | Meaning |
|---|---|
| `7d` | 7 days ago |
| `2w` | 2 weeks ago |
| `1m` | 1 month ago (30 days) |
| `2025-01-01` | Absolute date |
| `2025-01-01T12:00:00` | Absolute datetime |

## Adding a custom data source

```python
from memory_bank.ingestors.custom import CustomIngestor, SourceRecord

def my_mapper(record: dict) -> SourceRecord | None:
    return SourceRecord(
        session_id=record["thread_id"],
        role="user" if record["from_me"] else "assistant",
        content=record["text"],
        timestamp=record["date"],
        project=record.get("channel", ""),
        metadata={"platform": "slack"},
    )

ingestor = CustomIngestor(
    source_name="slack",
    file_path="slack_export.json",
    mapper=my_mapper,
)
```

Then wire it into the CLI or call the DB directly:

```python
from memory_bank.db import MemoryDB
db = MemoryDB()
for msg in ingestor.iter_messages():
    db.upsert([msg])
```

## Search agent (interactive)

```bash
# Interactive chat mode
ANTHROPIC_API_KEY=sk-... python scripts/search_agent.py

# Single query
ANTHROPIC_API_KEY=sk-... python scripts/search_agent.py "What was that Docker fix I did?"
```

## Claude Code integration

Install skills and hooks in one step:

```bash
memory-bank setup install          # symlinks skills + installs hooks
memory-bank setup status           # check what's installed
memory-bank setup uninstall        # remove everything
```

Two skills are included:
- **memory-search** — semantic search over past conversations
- **memory-recall** — full session context retrieval and synthesis

## Project structure

```
src/memory_bank/
├── schema.py              — ChatMessage dataclass + IngestResult
├── db.py                  — Qdrant wrapper (upsert, search, stats, delete, sessions)
├── cli.py                 — CLI entry point + shared config
├── categorizer.py         — keyword-based message categorization
├── router.py              — ingest routing (direct DB or HTTP via UI server)
├── mcp_server.py          — FastMCP server (search_memory, get_session, list_sessions)
├── commands/
│   ├── ingest.py          — ingest subcommands (claude-code, claude-desktop, all, custom)
│   ├── search.py          — search + sessions + session commands
│   ├── manage.py          — stats + delete commands
│   ├── hooks.py           — hooks install/uninstall/status
│   ├── setup.py           — setup install/uninstall/status
│   └── mcp.py             — mcp command
├── ui/
│   ├── server.py          — HTML template + HTTP server + ui group command
│   └── daemon.py          — background daemon (start/stop/restart/status/dev)
└── ingestors/
    ├── base.py            — BaseIngestor ABC
    ├── claude_code.py     — ~/.claude/projects/**/*.jsonl
    ├── claude_desktop.py  — Claude Desktop JSON export
    ├── chatgpt.py         — ChatGPT data export (conversations.json)
    └── custom.py          — generic mapper-based ingestor

scripts/
└── search_agent.py        — Agentic search via Anthropic API

skills/
├── memory-search/SKILL.md — semantic search skill
└── memory-recall/SKILL.md — full session context retrieval skill
```
