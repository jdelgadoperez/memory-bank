![memory-bank](./docs/images/memory-bank.png)

# memory-bank

Local vector DB for ingesting and searching Claude chat histories. Ask "what did I work on last week?" and get real answers from your past sessions — no cloud, no server, everything runs on your machine.

## Getting started

**Prerequisites:** Python 3.11+ and [`uv`](https://docs.astral.sh/uv/)

**Option 1 — one-step installer (recommended)**

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/jdelgadoperez/memory-bank/main/install.sh)
```

Or clone first and run locally:

```bash
git clone https://github.com/jdelgadoperez/memory-bank
bash memory-bank/install.sh
```

The installer clones the repo, runs `uv sync`, symlinks `memory-bank` to `~/.local/bin/`, wires Claude Code hooks and MCP, and runs an initial ingest. When it finishes, `memory-bank` is available as a shell command.

> **PATH note:** If you see `zsh: command not found: memory-bank` after install, `~/.local/bin` is not in your PATH. Add this to your `~/.zshrc` or `~/.bashrc` and open a new terminal:
> ```bash
> export PATH="$HOME/.local/bin:$PATH"
> ```

**Option 2 — manual setup**

```bash
# 1. Clone and install
git clone <repo-url>
cd memory-bank
uv sync --extra mcp

# 2. Symlink the CLI so it's available globally
mkdir -p ~/.local/bin
ln -sf "$PWD/.venv/bin/memory-bank" ~/.local/bin/memory-bank

# 3. Wire up Claude Code hooks, skills, and MCP
memory-bank setup install --on recommended

# 4. Ingest your Claude Code history
memory-bank ingest claude-code

# 5. Search
memory-bank search "authentication bug fix"
memory-bank stats
```

**Note:** On first ingest, `BAAI/bge-small-en-v1.5` embedding model (~25 MB) downloads once from HuggingFace and runs fully offline after.

---

## Configuration

All settings are controlled via environment variables. You can set them in your shell profile (`~/.zshrc`, `~/.bashrc`) or prefix individual commands.

| Variable              | Default                                | Description                                    |
| --------------------- | -------------------------------------- | ---------------------------------------------- |
| `MEMORY_BANK_DB`      | `~/.memory-bank/qdrant`                | Where the vector DB is stored on disk          |
| `CLAUDE_PROJECTS_DIR` | `~/.claude/projects`                   | Path to Claude Code session logs               |
| `CLAUDE_DESKTOP_PATH` | `~/Library/Application Support/Claude` | Path to Claude Desktop app data                |
| `ANTHROPIC_API_KEY`   | —                                      | Required only for the interactive search agent |
| `MEMORY_BANK_RECALL`  | —                                      | Set to `0` to temporarily disable the recall (UserPromptSubmit) hook |

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
memory-bank ingest custom                         # prints Python API usage
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

| Option                   | Description                                                                                                                                                  |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `--limit N` / `-n N`     | Number of results (default: 10)                                                                                                                              |
| `--source SOURCE`        | Filter by source: `claude-code`, `claude-desktop`, or a custom name                                                                                          |
| `--project PROJECT`      | Filter by project name (matches the folder name under `~/.claude/projects/`)                                                                                 |
| `--current-project`      | Auto-set `--project` to the current working directory name                                                                                                   |
| `--role user\|assistant` | Only return messages from one side of the conversation                                                                                                       |
| `--session SESSION_ID`   | Filter to a specific session                                                                                                                                 |
| `--since EXPR`           | Only return messages newer than this time (e.g. `7d`, `2w`, `2025-01-01`)                                                                                   |
| `--before EXPR`          | Only return messages older than this time                                                                                                                    |
| `--context N`            | Include N surrounding messages before/after each result (from the same session)                                                                              |
| `--category CAT`         | Filter by message category: `bugfix`, `feature`, `refactor`, `decision`, `research`                                                                          |
| `--dedupe`               | Remove duplicate results, keeping the highest-scoring copy when the same content appears across multiple sessions                                             |
| `--min-score FLOAT`      | Discard results below this similarity score (0–1). Recommended: `0.5` in agent contexts                                                                      |
| `--json`                 | Output raw JSON (full fidelity, good for `jq` pipelines)                                                                                                     |
| `--agent`                | Compact JSON for LLM consumption — drops `id`, date-only timestamps, 300-char snippets, defaults to limit=5 / min-score=0.5. ~60% fewer tokens than `--json` |
| `--snippet N`            | Truncate content to N characters in JSON/agent output                                                                                                        |
| `--db PATH`              | Use an alternate DB path                                                                                                                                     |

#### Examples

```bash
# Human-readable table
memory-bank search "docker networking" --role assistant

# Compact JSON for LLM/agent use (~60% fewer tokens)
memory-bank search "auth bug" --agent --project my-app

# Full JSON for jq pipelines
memory-bank search "deployment pipeline" --limit 5 --json --snippet 400

# Filter out low-quality hits
memory-bank search "kubernetes config" --source claude-code --min-score 0.5

# Filter by category
memory-bank search "authentication" --agent --category bugfix

# Include surrounding context to understand if a result was the solution or a dead-end
memory-bank search "docker fix" --agent --context 2

# Search current project, dedup repeated conversations
memory-bank search "refactor" --current-project --dedupe --agent
```

### Stats

```bash
memory-bank stats [--db PATH]
```

Shows total message count broken down by source, the DB path, and which embedding model is active.

### Delete

```bash
memory-bank delete [SOURCE] [--since EXPR] [--yes]
```

Deletes ingested messages by source, age, or both. Either `SOURCE` or `--since` (or both) must be provided. Cannot be undone.

| Option          | Description                                                              |
| --------------- | ------------------------------------------------------------------------ |
| `SOURCE`        | Delete all messages from this source (e.g. `claude-code`). Run `memory-bank stats` to see available source names. |
| `--since EXPR`  | Delete messages **older than** this time (e.g. `90d`, `2025-01-01`). Use this to prune old data without wiping a whole source. |
| `--yes` / `-y`  | Skip the confirmation prompt — useful for scripting.                     |
| `--db PATH`     | Use an alternate DB path.                                                |

```bash
# Delete all messages from claude-desktop
memory-bank delete claude-desktop

# Prune messages older than 90 days (across all sources)
memory-bank delete --since 90d

# Prune old messages from a specific source, no confirmation
memory-bank delete claude-code --since 90d --yes
```

### UI

```bash
memory-bank ui [-p PORT] [-B|--no-browser] [--db PATH]
```

Launches a local web UI to browse and search your memory bank. When run without a subcommand it starts a foreground HTTP server and opens your browser.

| Option                    | Description                                    |
| ------------------------- | ---------------------------------------------- |
| `-p PORT` / `--port PORT` | Port to listen on (default: 6333)              |
| `-B` / `--no-browser`     | Start the server without opening a browser tab |
| `--db PATH`               | Use an alternate DB path                       |

```bash
memory-bank ui                   # foreground server, opens browser
memory-bank ui -B                # foreground, no browser
memory-bank ui -p 8080           # custom port
```

#### Background daemon

Manage the UI as a background process:

```bash
memory-bank ui start             # start in background, open browser
memory-bank ui -B start          # start in background, no browser
memory-bank ui stop              # stop the background server
memory-bank ui restart           # stop + start
memory-bank ui status            # check if running
```

PID is written to `~/.memory-bank/ui.pid`, logs to `~/.memory-bank/ui.log`.

#### Dev mode (auto-reload)

```bash
memory-bank ui dev               # watches src/ and restarts on .py changes
```

Requires the dev extras: `uv pip install -e '.[dev]'` (installs `watchfiles`). Press Ctrl+C to stop.

### Hooks

Hooks are installed automatically by `memory-bank setup install` (recommended: `stop` + `recall`). To manage them separately:

```bash
memory-bank hooks status               # check what's installed
memory-bank hooks install --on stop    # auto-ingest after each session
memory-bank hooks install --on recall  # inject context into every prompt
memory-bank hooks uninstall            # remove all memory-bank hooks
```

Hooks run in the background and log to `~/.memory-bank/ingest.log`. Re-running `install` is safe — already-installed hooks are skipped.

| `--on` value    | What it does |
|---|---|
| `stop` | Auto-ingest after each session ends |
| `start` | At session start, search DB for relevant past work and inject into project's `CLAUDE.md` |
| `precompact` | Ensure full transcript is captured before Claude Code prunes context |
| `recall` | Before each prompt, search history and inject relevant context. Disable with `MEMORY_BANK_RECALL=0` |
| `both` | Stop + SessionStart |
| `recommended` | Stop + UserPromptSubmit (default from `setup install`) |
| `all` | Stop + SessionStart + PreCompact + UserPromptSubmit |

---

## Data sources

| Source           | What's ingested                       | Default path          |
| ---------------- | ------------------------------------- | --------------------- |
| `claude-code`    | All Claude Code sessions (`*.jsonl`)  | `~/.claude/projects/` |
| `claude-desktop` | Exported Claude Desktop conversations | _(requires `--path`)_ |
| Custom           | Any JSON/JSONL via a mapper function  | _(Python API only)_   |

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

## Claude Code integration

### Claude Code plugin (zero-config)

The repo ships a `.claude-plugin/plugin.json` manifest. When the repo is open in Claude Code the plugin is auto-discovered — MCP tools, skills, and hooks are all registered without running `setup install`.

### Skills

Installed automatically by `memory-bank setup install` (or via the plugin). Use these slash commands in Claude Code:

- **/memory-search** — Find relevant past conversations. Try: _"Search my history for Docker networking"_
- **/memory-recall** — Pull full session context. Try: _"What was our approach to that auth bug?"_

### MCP server

The repo includes `.mcp.json` for project-level auto-discovery. To register globally, `setup install` adds the server to `~/.claude/settings.json`. MCP tools available in every session: `search_memory`, `list_sessions`, `get_session`.

To manage setup:

```bash
memory-bank setup status           # check what's installed
memory-bank setup uninstall        # remove skills and hooks
memory-bank setup install          # re-install from scratch
```

After running `setup install`, the CLI prints next steps: ingest your history, open the UI, and start using MCP tools in your next session.

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
├── db.py                  Qdrant wrapper (upsert, search, stats, delete, sessions)
├── cli.py                 CLI entry point + shared config
├── categorizer.py         Keyword-based message categorization
├── router.py              Ingest routing (direct DB or HTTP via UI server)
├── mcp_server.py          FastMCP server (search_memory, get_session, list_sessions)
├── commands/
│   ├── ingest.py          ingest subcommands (claude-code, claude-desktop, all, custom)
│   ├── search.py          search + sessions + session commands
│   ├── manage.py          stats + delete commands
│   ├── hooks.py           hooks install/uninstall/status
│   ├── setup.py           setup install/uninstall/status
│   └── mcp.py             mcp command
├── ui/
│   ├── server.py          HTML template + HTTP server + ui group command
│   └── daemon.py          background daemon (start/stop/restart/status/dev)
└── ingestors/
    ├── base.py            BaseIngestor ABC
    ├── claude_code.py     ~/.claude/projects/**/*.jsonl
    ├── claude_desktop.py  Claude Desktop JSON export
    ├── chatgpt.py         ChatGPT data export (conversations.json)
    └── custom.py          Generic mapper-based ingestor
scripts/
└── search_agent.py        Agentic search via Anthropic API
skills/
├── memory-search/SKILL.md Semantic search skill
└── memory-recall/SKILL.md Full session context retrieval skill
.claude-plugin/
└── plugin.json            Claude Code plugin manifest (auto-discovery)
hooks/
└── hooks.json             Hook definitions used by the plugin manifest
.mcp.json                  Project-level MCP server config (Claude Code / Claude Desktop)
install.sh                 One-step installer script
```
