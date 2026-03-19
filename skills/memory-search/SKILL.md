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

## Search commands

### Basic semantic search
```bash
memory-bank search "your query here"
```

### With filters
```bash
# Filter by source
memory-bank search "query" --source claude-code
memory-bank search "query" --source claude-desktop

# Filter by project
memory-bank search "query" --project my-project

# Only user messages or only assistant responses
memory-bank search "query" --role user
memory-bank search "query" --role assistant

# More results
memory-bank search "query" --limit 20

# JSON output for programmatic use
memory-bank search "query" --json
```

### Environment variable for custom DB path
```bash
MEMORY_BANK_DB=/custom/path memory-bank search "query"
```

## Workflow

1. Run the search command with the user's query
2. Read the results table (score, role, source/project, timestamp, content)
3. Summarize the most relevant findings to the user
4. If results are empty, suggest refining the query or re-ingesting

## Ingest commands reference

```bash
# Ingest Claude Code history (auto-detects ~/.claude/projects/)
memory-bank ingest claude-code

# Ingest from a specific path
memory-bank ingest claude-code --path /custom/.claude/projects

# Ingest Claude Desktop export
memory-bank ingest claude-desktop --path ~/Downloads/conversations.json

# Ingest everything auto-detectable
memory-bank ingest all
```

## Stats
```bash
memory-bank stats
```

## Web UI

```bash
memory-bank ui           # opens http://localhost:6333
memory-bank ui --port 8080
```

## Auto-ingest hooks

```bash
memory-bank hooks install    # run ingest automatically after each session
memory-bank hooks status
```
