![memory-bank](./docs/images/memory-bank.png)

# memory-bank

Local vector DB for ingesting and searching Claude chat histories. Ask "what did I work on last week?" and get real answers from your past sessions — no cloud, no server, everything runs on your machine.

## Contents

- [Getting started](#getting-started)
- [Configuration](#configuration)
- [Storage modes](#storage-modes)
- [Commands](#commands)
  - [Ingest](#ingest)
  - [Search](#search)
  - [Stats](#stats)
  - [Delete](#delete)
  - [UI](#ui)
  - [Hooks](#hooks)
  - [Update](#update)
- [Data sources](#data-sources)
- [Custom data source (Python API)](#custom-data-source-python-api)
- [Interactive search agent](#interactive-search-agent)
- [Claude Code integration](#claude-code-integration)
- [How it works](#how-it-works)
- [Project layout](#project-layout)

## Getting started

**Option 1 — one-step installer (recommended)**

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/jdelgadoperez/memory-bank/main/install.sh)
```

Installs `uv` if needed, runs `uv tool install memory-bank`, wires Claude Code hooks and MCP, and runs an initial ingest. No repo clone required. When it finishes, `memory-bank` is available as a shell command.

> **PATH note:** If you see `zsh: command not found: memory-bank` after install, `~/.local/bin` is not in your PATH. Add this to your `~/.zshrc` or `~/.bashrc` and open a new terminal:
> ```bash
> export PATH="$HOME/.local/bin:$PATH"
> ```

**Option 2 — manual (uv tool)**

```bash
uv tool install memory-bank
memory-bank setup install
memory-bank ingest claude-code
```

To update: `memory-bank update`

**Option 3 — clone (contributors / local dev)**

```bash
git clone https://github.com/jdelgadoperez/memory-bank
cd memory-bank
uv sync
mkdir -p ~/.local/bin
ln -sf "$PWD/.venv/bin/memory-bank" ~/.local/bin/memory-bank
memory-bank setup install
memory-bank ingest claude-code
```

Skills are symlinked from the source tree in this mode — edits take effect immediately without reinstalling.

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
| `MEMORY_BANK_RECALL`  | —                                      | Set to `0` to disable the recall (UserPromptSubmit) hook |
| `QDRANT_URL`          | —                                      | Override the Qdrant server URL (e.g. `http://localhost:6333`). Skips Docker auto-start. |

### Slow commands / commands hanging

If memory-bank commands hang or feel slow, it is usually because the Qdrant health check
and Docker daemon probe run on startup. Each has a short timeout, but on some machines
(e.g. Apple Silicon with Docker not running) the probes still add a few seconds of latency.

**Option 1 — disable the recall hook** (fastest, no DB access on every prompt):
```bash
export MEMORY_BANK_RECALL=0
```

**Option 2 — point directly at a running Qdrant server** (skips Docker probing):
```bash
export QDRANT_URL=http://localhost:6333
```

**Option 3 — run `memory-bank update` when commands are hanging** (e.g. after a fresh install before Qdrant has started):
```bash
MEMORY_BANK_RECALL=0 memory-bank update
```

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

## Storage modes

memory-bank stores its data in Qdrant, which runs in one of two modes:

| Mode | What it is | When it's used |
| --- | --- | --- |
| **Server** | A Qdrant server, usually the `memory-bank-qdrant` Docker container on `localhost:6333` | Whenever one is reachable |
| **Embedded** | Qdrant runs inside the memory-bank process and reads files directly. No server needed. | Fallback when no server is reachable |

There's no setting that picks the mode. Each time a memory-bank process starts, it uses the first of these that works:

1. `QDRANT_URL` is set → use that server. Docker auto-start is skipped.
2. Something already answers on `localhost:6333` → use it.
3. Docker is running → start (or create) the `memory-bank-qdrant` container and use it.
4. Otherwise → embedded mode.

`memory-bank stats` shows the current mode on its **Qdrant mode** row.

Embedded mode is fine for small collections. It slows down past about 20k points (you'll see a warning), and only one process can have the files open at a time. So the UI server, MCP server and CLI commands can block each other with `Database is locked`. Server mode doesn't have either limit.

### Switching from embedded to server

1. Stop anything that has the embedded files open: `memory-bank ui stop`, and quit Claude Code / Claude Desktop so the hooks and MCP server release them.
2. Start Docker.
3. Copy your data into the server. It starts out **empty**:
   ```bash
   memory-bank migrate --to server
   ```
   This creates the container if needed. Run `memory-bank stats` afterwards: the **Qdrant mode** row should say `server` and the count should match.
4. Restart the long-running processes, which pick their mode once at startup: `memory-bank ui start`, and reopen Claude Code / Claude Desktop.

You don't need `QDRANT_URL` for this. The container on `localhost:6333` is found automatically. Set it only if Qdrant runs somewhere else (another host or port, or Qdrant Cloud), and make sure that server is already up, because setting `QDRANT_URL` skips the Docker auto-start.

### Switching from server to embedded

Copy first, while the server is still running. Stopping the container alone isn't enough to switch: if Docker is running, memory-bank starts it again, and the container is set to restart on its own.

1. Stop the UI server and quit Claude Code / Claude Desktop.
2. Copy your data into the embedded store:
   ```bash
   memory-bank migrate --to embedded
   ```
3. Unset `QDRANT_URL`, stop the container (`docker stop memory-bank-qdrant`), and quit Docker.
4. Restart the UI server and Claude Code / Claude Desktop.

### Where `QDRANT_URL` needs to be set

`QDRANT_URL` is a plain environment variable that each process reads at startup. memory-bank doesn't save it anywhere. Set it wherever the process runs:

- **CLI**: `~/.zshrc` / `~/.bashrc`.
- **Hooks**: these run inside Claude Code, so they see your shell environment if you started Claude Code from a terminal. To be sure, also add it to the `env` block in `~/.claude/settings.json`.
- **MCP server in Claude Desktop**: apps opened from the Dock don't read your shell profile. Add `"env": {"QDRANT_URL": "..."}` to the `memory-bank` entry in `claude_desktop_config.json`.

### Upgrading the Qdrant server

New containers are created from a pinned image (`QDRANT_IMAGE` in `src/memory_bank/db.py`), matched to the `qdrant-client` version in `pyproject.toml`. **An existing container keeps the image it was created with.** Containers created before this pin used the untagged `qdrant/qdrant` image, so they're stuck on whatever version was current at the time. Once the client moves on, every command prints:

```
UserWarning: Qdrant client version 1.20.0 is incompatible with server version 1.17.1.
Major versions should match and minor version difference must not exceed 1.
```

To fix it, upgrade the container. Qdrant only guarantees storage compatibility between consecutive minor versions, so step through each one rather than jumping straight to the latest. Your data lives in the mounted folder, so it carries over from one container to the next.

1. Stop the UI server (`memory-bank ui stop`) and quit Claude Code / Claude Desktop, so no hook or MCP server recreates the container mid-upgrade.

2. Check your current server version:

   ```bash
   curl -s localhost:6333 | grep -o '"version":"[^"]*"'
   ```

3. Back up the storage folder (with the container stopped):

   ```bash
   docker stop memory-bank-qdrant
   cp -a ~/.memory-bank/qdrant ~/.memory-bank/qdrant.bak
   ```

4. Step through each minor version, starting from the one after yours. This example goes from 1.17 to 1.20:

   ```bash
   for v in v1.18.3 v1.19.2 v1.20.2; do
     docker rm -f memory-bank-qdrant
     docker run -d --name memory-bank-qdrant -p 6333:6333 --restart unless-stopped \
       -v ~/.memory-bank/qdrant:/qdrant/storage:z qdrant/qdrant:$v
     until curl -sf localhost:6333/readyz >/dev/null; do sleep 1; done
     echo "$v: $(curl -s localhost:6333/collections/chat_history | grep -o '"points_count":[0-9]*')"
   done
   ```

   The points count should stay the same at every step.

5. Run `memory-bank stats`. The warning should be gone. Once you're happy, delete `~/.memory-bank/qdrant.bak`.

If a step fails, stop the container, restore the backup with `rm -rf ~/.memory-bank/qdrant && mv ~/.memory-bank/qdrant.bak ~/.memory-bank/qdrant`, and start the old container again.

### Moving data between modes

The two modes **don't share a storage format**. Even though the container mounts the same `~/.memory-bank/qdrant` folder, they keep data in separate places inside it:

```
~/.memory-bank/qdrant/
├── collection/    ← embedded mode (SQLite)
├── meta.json      ← embedded mode
└── collections/   ← server mode (Qdrant's own segment format)
```

Switching modes therefore doesn't bring your history along. Neither side is deleted, though. The other mode's data is still on disk and can be copied across.

Use `memory-bank migrate` to copy it. It copies every point with its stored vector and payload, so nothing is re-embedded and soft-deleted points stay soft-deleted. Points are keyed by message ID, so it **merges** into whatever the destination already has. A message already there is overwritten with the source copy, and re-running is safe. Nothing is deleted from the source.

```bash
memory-bank migrate --to server --dry-run   # show counts on both sides, write nothing
memory-bank migrate --to server             # embedded → server
memory-bank migrate --to embedded           # server → embedded
```

| Option | Description |
| --- | --- |
| `--to server\|embedded` | Mode to copy **into**. The other one is the source. |
| `--db DIR` | Embedded store path (default `MEMORY_BANK_DB` or `~/.memory-bank/qdrant`) |
| `--url URL` | Server URL (default `QDRANT_URL` or `http://localhost:6333`) |
| `--batch-size N` | Points per request (default 256) |
| `--pause SECONDS` | Sleep between batches to throttle the copy, e.g. `0.1` |
| `--dry-run` | Show what would be copied without writing |

Notes:

- **Nothing else may have the embedded files open.** If the UI server, a hook or the MCP server holds them, `migrate` stops with a message saying which to close.
- **With `--to server`**, if nothing answers on `localhost:6333` and Docker is running, the container is started for you. A custom `--url` must already be up.
- **With `--to embedded`**, the server must already be running. Docker is never started.
- It finishes by printing both counts, and exits with an error if the destination ends up with fewer points than were copied.

**Resource use.** With `--to server`, the embedded store is read straight from its SQLite file one batch at a time, so memory stays flat however big the store is. Opening it the usual way loads every message and vector into RAM, which runs to many GB for a large collection. The server's search indexing is paused during the upload and turned back on at the end, even if you Ctrl+C. Qdrant then builds the index once in the background, so the container's CPU can stay busy for a while afterwards; search keeps working meanwhile. To slow things down further, add `--pause 0.1` or cap the container in Docker Desktop (*Settings → Resources*).

With `--to embedded`, the destination is held in memory the whole time, as embedded mode always is. It's meant for collections small enough to run embedded in the first place.

**Alternative: re-ingest.** Running `memory-bank ingest all` in the new mode rebuilds whatever is still in your source files. Anything that isn't comes back only through `migrate`: Claude Code transcripts that have since been cleaned up, one-off ChatGPT/Desktop imports, and `distill` summaries (especially with `--replace-raw`).

---

## Commands

### Ingest

```bash
memory-bank ingest claude-code [--path PATH] [--db PATH]
memory-bank ingest claude-desktop --path PATH [--db PATH]
memory-bank ingest chatgpt --path PATH [--db PATH]
memory-bank ingest all [--db PATH]
memory-bank ingest custom                         # prints Python API usage
```

Ingest is **idempotent** — re-running skips messages already in the DB.

#### Claude Desktop

Export your conversations from Claude Desktop (Settings → Data & Privacy → Export Conversations), then point at the file:

```bash
memory-bank ingest claude-desktop --path ~/Downloads/conversations.json
```

#### ChatGPT

Export your ChatGPT history from [chat.openai.com](https://chat.openai.com) → Settings → Data controls → Export data. You'll receive a zip containing `conversations.json`.

```bash
memory-bank ingest chatgpt --path ~/Downloads/conversations.json
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
| `-p PORT` / `--port PORT` | Port to listen on (default: 8765)              |
| `-B` / `--no-browser`     | Start the server without opening a browser tab |
| `--db PATH`               | Use an alternate DB path                       |

```bash
memory-bank ui                   # foreground server, opens browser
memory-bank ui -B                # foreground, no browser
memory-bank ui -p 8765           # custom port
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

Requires the dev extras: `uv sync --extra dev` (installs `watchfiles`). Press Ctrl+C to stop.

### Hooks

Hooks are installed automatically by `memory-bank setup install` (default: `stop` hook). To manage them separately or install additional hooks:

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
| `recommended` | Stop + UserPromptSubmit |
| `all` | Stop + SessionStart + PreCompact + UserPromptSubmit |

### Update

```bash
memory-bank update [--dir DIR]
```

Pulls the latest changes and refreshes skills. For `uv tool install` installs, runs `uv tool upgrade memory-bank`. For clone-based installs, runs `git pull` + `uv sync`. Pass `--dir` to specify a custom clone path.

---

## Data sources

| Source           | What's ingested                       | Default path          |
| ---------------- | ------------------------------------- | --------------------- |
| `claude-code`    | All Claude Code sessions (`*.jsonl`)  | `~/.claude/projects/` |
| `claude-desktop` | Exported Claude Desktop conversations | _(requires `--path`)_ |
| `chatgpt`        | ChatGPT data export (`conversations.json` or directory) | _(requires `--path`)_ |
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

- **Storage**: [Qdrant](https://qdrant.tech/), as a Docker-managed server when available, otherwise embedded with no server process. Data lives in `~/.memory-bank/qdrant/`. See [Storage modes](#storage-modes).
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
│   ├── update.py          update command (uv tool upgrade or git pull)
│   ├── _recall_guard.py   recall hook logic and skip patterns
│   └── mcp.py             mcp command
├── ui/
│   ├── server.py          HTML template + HTTP server + ui group command
│   └── daemon.py          background daemon (start/stop/restart/status/dev)
├── skills/
│   ├── memory-search/SKILL.md  Semantic search skill
│   └── memory-recall/SKILL.md  Full session context retrieval skill
└── ingestors/
    ├── base.py            BaseIngestor ABC
    ├── claude_code.py     ~/.claude/projects/**/*.jsonl
    ├── claude_desktop.py  Claude Desktop JSON export
    ├── chatgpt.py         ChatGPT data export (conversations.json)
    └── custom.py          Generic mapper-based ingestor
scripts/
└── search_agent.py        Agentic search via Anthropic API
.claude-plugin/
└── plugin.json            Claude Code plugin manifest (auto-discovery)
hooks/
└── hooks.json             Hook definitions used by the plugin manifest
.github/
└── FUNDING.yml            GitHub metadata (funding link, shown as the Sponsor button)
.mcp.json                  Project-level MCP server config (Claude Code / Claude Desktop)
install.sh                 One-step installer script
```

## Found this useful?

If you'd like to buy me a coffee or send a tip, it's much appreciated.

[![Say thanks on Ko-fi](https://img.shields.io/badge/Ko--fi-Say%20thanks-FF5E5B?logo=kofi&logoColor=white)](https://ko-fi.com/jessdp)

A star works just as well.
