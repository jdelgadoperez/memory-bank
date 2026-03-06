# memory-bank

Local vector DB for ingesting and searching Claude chat histories. Ask "what did I work on last week?" and get real answers from your past sessions — no cloud, no server, everything runs on your machine.

---

## Getting started

### Prerequisites

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) (recommended) or pip

### 1. Install

Clone the repo, then install in editable mode:

```bash
git clone <repo-url>
cd memory-bank
uv sync          # or: uv pip install -e .
```

> **macOS note:** If `uv sync` fails with an `onnxruntime` platform error, the pinned version
> in `pyproject.toml` (`onnxruntime<1.24`) should resolve this automatically. If you still hit
> issues, try `pip install onnxruntime` separately to let pip pick a compatible wheel.

The `memory-bank` command is now on your PATH inside the virtualenv. Activate it or prefix commands with `uv run`:

```bash
# Option A: activate venv
source .venv/bin/activate

# Option B: prefix every command
uv run memory-bank stats
```

**Tip — add a shell alias** so `memory-bank` works from any directory without activating the venv. Add this to your `~/.zshrc` or `~/.bashrc`:

```bash
alias memory-bank="uv run --project /path/to/memory-bank memory-bank"
```

Replace `/path/to/memory-bank` with the actual clone location (e.g. `~/code/memory-bank`). Then reload your shell:

```bash
source ~/.zshrc   # or ~/.bashrc
```

### 2. Ingest your Claude Code history

Claude Code stores session logs in `~/.claude/projects/`. Ingest them all with:

```bash
memory-bank ingest claude-code
```

On first run this downloads the `BAAI/bge-small-en-v1.5` embedding model (~25 MB from HuggingFace). Subsequent runs are instant and skip already-indexed messages.

### 3. Search

```bash
memory-bank search "authentication bug fix"
memory-bank search "docker networking issue" --role assistant --limit 20
```

Results are shown in a formatted table with relevance scores. Run with `--json` to get raw output for scripting.

### 4. Check what's indexed

```bash
memory-bank stats
```

---

## Configuration

All settings are controlled via environment variables. You can set them in your shell profile (`~/.zshrc`, `~/.bashrc`) or prefix individual commands.

| Variable | Default | Description |
|---|---|---|
| `MEMORY_BANK_DB` | `~/.memory-bank/qdrant` | Where the vector DB is stored on disk |
| `CLAUDE_PROJECTS_DIR` | `~/.claude/projects` | Path to Claude Code session logs |
| `CLAUDE_DESKTOP_PATH` | `~/Library/Application Support/Claude` | Path to Claude Desktop app data |
| `ANTHROPIC_API_KEY` | — | Required only for the interactive search agent |

### Example: custom DB location

```bash
export MEMORY_BANK_DB=/data/my-memory-bank
memory-bank ingest claude-code
memory-bank search "my query"
```

Or inline per-command with `--db`:

```bash
memory-bank ingest claude-code --db /data/my-memory-bank
memory-bank search "my query" --db /data/my-memory-bank
```

### Example: custom Claude Code path

```bash
# If your Claude projects live somewhere non-standard
memory-bank ingest claude-code --path /Volumes/external/claude-projects
# or permanently:
export CLAUDE_PROJECTS_DIR=/Volumes/external/claude-projects
```

---

## Commands

### Ingest

```bash
memory-bank ingest claude-code [--path PATH] [--db PATH]
memory-bank ingest claude-desktop --path PATH [--db PATH]
memory-bank ingest all [--db PATH]
memory-bank ingest custom          # prints Python API usage
```

Ingest is **idempotent** — re-running skips messages already in the DB.

#### Claude Desktop

Export your conversations from Claude Desktop (Settings → Data & Privacy → Export Conversations), then point at the file:

```bash
memory-bank ingest claude-desktop --path ~/Downloads/conversations.json
```

#### Ingest all sources at once

```bash
memory-bank ingest all
```

Runs `claude-code` automatically and `claude-desktop` if the default path is found. If Claude Desktop isn't auto-detected, ingest it manually with `--path`.

### Search

```bash
memory-bank search QUERY [options]
```

| Option | Description |
|---|---|
| `--limit N` / `-n N` | Number of results (default: 10) |
| `--source SOURCE` | Filter by source: `claude-code`, `claude-desktop`, or a custom name |
| `--project PROJECT` | Filter by project name (matches the folder name under `~/.claude/projects/`) |
| `--role user\|assistant` | Only return messages from one side of the conversation |
| `--session SESSION_ID` | Filter to a specific session |
| `--json` | Output raw JSON instead of a table |
| `--db PATH` | Use an alternate DB path |

#### Examples

```bash
# Find assistant responses about Docker
memory-bank search "docker networking" --role assistant

# Search only within a specific project
memory-bank search "auth bug" --project my-app

# Get JSON output for scripting
memory-bank search "deployment pipeline" --limit 5 --json

# Search a specific source
memory-bank search "kubernetes config" --source claude-code
```

### Stats

```bash
memory-bank stats [--db PATH]
```

Shows total message count broken down by source, the DB path, and which embedding model is active.

### Delete

```bash
memory-bank delete SOURCE
```

Deletes all messages from the named source after a confirmation prompt. Cannot be undone.

---

## Data sources

| Source | What's ingested | Default path |
|---|---|---|
| `claude-code` | All Claude Code sessions (`*.jsonl`) | `~/.claude/projects/` |
| `claude-desktop` | Exported Claude Desktop conversations | _(requires `--path`)_ |
| Custom | Any JSON/JSONL via a mapper function | _(Python API only)_ |

---

## Custom data source (Python API)

There is no CLI command for custom sources — use the Python API directly:

```python
from memory_bank.ingestors.custom import CustomIngestor, SourceRecord
from memory_bank.db import MemoryDB

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

db = MemoryDB()
for msg in ingestor.iter_messages():
    db.upsert([msg])
```

Then search as usual:

```bash
memory-bank search "standup notes" --source slack
```

Return `None` from the mapper to skip a record.

---

## Interactive search agent

An agentic wrapper that answers natural-language questions about your history using the Anthropic API:

```bash
# Requires ANTHROPIC_API_KEY
export ANTHROPIC_API_KEY=sk-ant-...

# Interactive chat mode
python scripts/search_agent.py

# Single question
python scripts/search_agent.py "What was that Docker fix I did last month?"
```

---

## Claude Code skill

Install the `memory-search` skill so Claude can search your history automatically during any session:

```bash
ln -s /home/user/memory-bank/skills/memory-search ~/.claude/skills/memory-search
```

Once installed, ask Claude mid-session: *"Search my chat history for X"* and it will call `memory-bank search` for you.

---

## How it works

- **Storage**: [Qdrant](https://qdrant.tech/) runs embedded — no server process, data lives in `~/.memory-bank/qdrant/`
- **Embeddings**: [fastembed](https://github.com/qdrant/fastembed) with `BAAI/bge-small-en-v1.5` (384-dim, ~25 MB, downloaded once, runs fully offline after that)
- **Offline fallback**: if the model can't be loaded, a hash-based fallback embedding is used so ingest still works, with reduced search quality
- **Deduplication**: each message gets a SHA-256 ID; re-ingesting the same source never creates duplicates

---

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
