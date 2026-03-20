---
name: memory-search
description: Search past Claude chat history using the memory-bank vector DB. Use when the user asks about previous conversations, past solutions, or wants to find something discussed in an earlier session.
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

## Setup check

Before searching, verify the tool is installed:

```bash
memory-bank stats
```

If the command is not found, install it:

```bash
uv pip install -e /home/user/memory-bank
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

Override defaults when needed:

```bash
# More results, lower score bar, longer snippets
memory-bank search "query" --agent --limit 10 --min-score 0.3 --snippet 500

# Scope to a project or role
memory-bank search "query" --agent --project my-app --role assistant

# Filter by source
memory-bank search "query" --agent --source claude-code
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
4. If results are empty or all low-score, retry with a rephrased query or drop `--min-score`

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
memory-bank ui           # web UI at http://localhost:6333
memory-bank hooks install    # auto-ingest after each session
memory-bank hooks status
```
