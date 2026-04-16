---
name: memory-search
description: Search past Claude chat history using the memory-bank vector DB. Use when the user asks about previous conversations, past solutions, or wants to find something discussed in an earlier session.
allowed-tools: Bash, Read
---

# Memory Bank Search Skill

Search semantically over ingested Claude Code and Claude Desktop chat histories stored in a local Qdrant vector DB.

## When to use

Trigger this skill when the user asks things like:
- "Did we talk about X before?"
- "What was that solution we used for Y?"
- "Find past conversations about Z"
- "What have I worked on related to X?"
- "Search my chat history for..."

## Prerequisites

Before searching, verify the tool is installed:

```bash
memory-bank stats
```

If the command is not found, the user needs to install memory-bank:

```bash
uv tool install memory-bank
memory-bank setup install
```

If the DB is empty (0 messages), ingest first:

```bash
memory-bank ingest claude-code
```

## Search — use `--agent` mode

Always use `--agent` when calling from Claude Code. It returns compact JSON (no id field,
date-only timestamps, 300-char content snippets, score ≥ 0.5 filter) that costs ~60% fewer
tokens than `--json` while preserving all signal needed to answer the user.

```bash
memory-bank search "your query" --agent
```

In `--agent` mode, `min-score` defaults to `0.5` and `limit` defaults to `5`. Override when needed:

```bash
# More results, lower score bar, longer snippets
memory-bank search "query" --agent --limit 10 --min-score 0.3 --snippet 500

# Scope to a project or role
memory-bank search "query" --agent --project my-app --role assistant

# Filter by source
memory-bank search "query" --agent --source claude-code

# Filter by message category (bugfix, feature, refactor, decision, research)
memory-bank search "authentication" --agent --category bugfix

# Include surrounding context to understand whether a result was a solution or dead-end
memory-bank search "docker fix" --agent --context 2

# Remove duplicate results across sessions (keeps highest-scoring copy)
memory-bank search "docker fix" --agent --dedupe

# Scope to the current working directory's project
memory-bank search "refactor" --agent --current-project --dedupe
```

### Human-readable table (for showing results to the user)
```bash
memory-bank search "query"
```

### Full JSON (for scripting / jq pipelines)
```bash
memory-bank search "query" --json --snippet 400
```

### Environment variable for custom DB path
```bash
MEMORY_BANK_DB=/custom/path memory-bank search "query" --agent
```

## Workflow

1. Run `memory-bank search "..." --agent`
2. Parse the compact JSON array: each object has `score`, `role`, `src`, `date`, `text`, and optionally `proj` / `sid`
3. Summarize the most relevant findings to the user, quoting briefly
4. If results are empty or low quality:
   - Rephrase the query more semantically (e.g. "container networking" instead of "docker errors")
   - Lower `--min-score` to `0.3`
   - Remove or broaden `--since` / `--before` filters
   - Increase `--limit` to `20`

## Ingest commands reference

```bash
memory-bank ingest claude-code                         # auto-detects ~/.claude/projects/
memory-bank ingest claude-code --path /custom/path
memory-bank ingest claude-desktop --path ~/Downloads/conversations.json
memory-bank ingest all
```

## Other commands

```bash
memory-bank stats
memory-bank ui           # web UI at http://localhost:8765
memory-bank hooks install    # auto-ingest after each session
memory-bank hooks status
```

## Web UI

```bash
memory-bank ui           # opens http://localhost:8765
memory-bank ui --port 8765
```

## Auto-ingest hooks

```bash
memory-bank hooks install    # run ingest automatically after each session
memory-bank hooks status
```
