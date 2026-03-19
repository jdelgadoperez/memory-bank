# Memory Bank

Local vector DB for ingesting and searching Claude chat histories.

## Setup

```bash
uv pip install -e .
```

The `memory-bank` CLI is now available. The Qdrant DB is stored at `~/.memory-bank/qdrant/` by default.

## Quick start

```bash
# 1. Ingest Claude Code history
memory-bank ingest claude-code

# 2. Search
memory-bank search "authentication bug fix"

# 3. Stats
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
# Install a Stop hook (runs after each session — recommended)
memory-bank hooks install

# Or hook into SessionStart instead, or both
memory-bank hooks install --on start
memory-bank hooks install --on both

# Check what's installed
memory-bank hooks status

# Remove all memory-bank hooks
memory-bank hooks uninstall
```

The hook runs `memory-bank ingest claude-code` in the background and appends
output to `~/.memory-bank/ingest.log`.  Your existing hooks in
`~/.claude/settings.json` are preserved.

## CLI reference

```
memory-bank ingest claude-code [--path PATH]
memory-bank ingest claude-desktop --path PATH
memory-bank ingest all
memory-bank ingest custom          # show Python API usage for custom sources
memory-bank search QUERY [--limit N] [--source SOURCE] [--project PROJECT] [--role user|assistant] [--session ID] [--json]
memory-bank stats
memory-bank delete SOURCE
memory-bank ui [--port PORT] [--no-browser]
memory-bank hooks install [--on stop|start|both]
memory-bank hooks uninstall
memory-bank hooks status
```

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

## Claude Code skill

The `memory-search` skill in `skills/memory-search/SKILL.md` teaches Claude to use
`memory-bank search` during sessions. Install it by symlinking:

```bash
ln -s /home/user/memory-bank/skills/memory-search ~/.claude/skills/memory-search
```

## Project structure

```
src/memory_bank/
├── schema.py           — ChatMessage dataclass + IngestResult
├── db.py               — Qdrant wrapper (upsert, search, stats, delete)
├── cli.py              — Click CLI (memory-bank command)
└── ingestors/
    ├── base.py         — BaseIngestor ABC
    ├── claude_code.py  — ~/.claude/projects/**/*.jsonl
    ├── claude_desktop.py — Claude Desktop JSON export
    └── custom.py       — Generic mapper-based ingestor

scripts/
└── search_agent.py     — Agentic search via Anthropic API

skills/
└── memory-search/SKILL.md  — Claude Code skill
```
