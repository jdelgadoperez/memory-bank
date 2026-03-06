# memory-bank

Local vector DB for ingesting and searching Claude chat histories. Ask Claude "what did I work on last week?" and get real answers from your past sessions.

## Install

```bash
uv pip install -e .
```

## Quick start

```bash
# Ingest Claude Code sessions (~/.claude/projects/)
memory-bank ingest claude-code

# Search
memory-bank search "authentication bug fix"

# Stats
memory-bank stats
```

## Commands

```
memory-bank ingest claude-code [--path PATH]
memory-bank ingest claude-desktop --path PATH
memory-bank ingest all
memory-bank search QUERY [--limit N] [--source SOURCE] [--project PROJECT] [--role user|assistant] [--json]
memory-bank stats
memory-bank delete SOURCE
```

### Search filters

```bash
memory-bank search "docker networking" --source claude-code
memory-bank search "auth bug" --project my-app --role assistant
memory-bank search "..." --limit 20 --json
```

## Claude Desktop

Export conversations from Claude Desktop (Settings → Data & Privacy → Export Conversations), then:

```bash
memory-bank ingest claude-desktop --path ~/Downloads/conversations.json
```

## Custom data source

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

ingestor = CustomIngestor(source_name="slack", file_path="export.json", mapper=my_mapper)
```

## Search agent

Interactive agent that answers questions about your chat history using the Anthropic API:

```bash
# Interactive
ANTHROPIC_API_KEY=sk-... python scripts/search_agent.py

# Single query
ANTHROPIC_API_KEY=sk-... python scripts/search_agent.py "What was that Docker fix?"
```

## Claude Code skill

Install the `memory-search` skill so Claude can search your history mid-session:

```bash
ln -s /home/user/memory-bank/skills/memory-search ~/.claude/skills/memory-search
```

Then ask Claude: *"Search my chat history for X"* and it will run `memory-bank search` automatically.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `MEMORY_BANK_DB` | `~/.memory-bank/qdrant` | DB storage path |
| `CLAUDE_PROJECTS_DIR` | `~/.claude/projects` | Claude Code sessions path |
| `CLAUDE_DESKTOP_PATH` | `~/Library/Application Support/Claude` | Claude Desktop path |
| `ANTHROPIC_API_KEY` | — | Required for the search agent |

## How it works

- **Storage**: [Qdrant](https://qdrant.tech/) embedded — no server, data lives in `~/.memory-bank/qdrant/`
- **Embeddings**: [fastembed](https://github.com/qdrant/fastembed) with `BAAI/bge-small-en-v1.5` (~25 MB, downloaded once, runs fully locally)
- **Ingest is idempotent**: re-running skips already-indexed messages

## Project layout

```
src/memory_bank/
├── schema.py              ChatMessage dataclass + IngestResult
├── db.py                  Qdrant wrapper (upsert, search, stats, delete)
├── cli.py                 CLI entry point
└── ingestors/
    ├── base.py            BaseIngestor ABC
    ├── claude_code.py     ~/.claude/projects/**/*.jsonl
    ├── claude_desktop.py  Claude Desktop JSON export
    └── custom.py          Generic mapper-based ingestor
scripts/
└── search_agent.py        Agentic search via Anthropic API
skills/
└── memory-search/SKILL.md Claude Code skill
```
