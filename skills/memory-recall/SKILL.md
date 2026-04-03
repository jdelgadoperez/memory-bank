---
name: memory-recall
description: Recall full context from a past Claude session. Use when the user needs detailed context from previous work — architecture decisions, implementation approaches, debugging sessions, or conversation threads.
allowed-tools: Bash, Read
---

# Memory Bank Recall

Retrieve full conversation context from past Claude sessions. Goes beyond search snippets to pull complete session threads and synthesize relevant context.

## When to use

Activate when the user asks:
- "What was our approach to X?"
- "Bring in context from when we worked on Y"
- "What did we decide about Z?"
- "Remind me what we did for that auth refactor"
- "Pull up that debugging session where we fixed..."
- "What was the plan for X?"
- Continuing work from a previous session
- Referencing decisions or patterns from past work

## Prerequisites

```bash
memory-bank stats
```

If the command is not found, the user needs to install memory-bank:

```bash
uv pip install -e /path/to/memory-bank
memory-bank setup install
```

If the DB is empty (0 messages), ingest first:

```bash
memory-bank ingest claude-code
```

## Recall workflow

### Step 1: Find the relevant session

Use search with `--agent` mode to find matching sessions:

```bash
memory-bank search "topic keywords" --agent --limit 10
```

Look at the `sid` (session ID) field in results to identify which session(s) are relevant.

Narrow by project if needed:

```bash
memory-bank search "topic" --agent --project project-name
```

### Step 2: Browse sessions (alternative)

List recent sessions for a project:

```bash
memory-bank sessions --project project-name --limit 10
```

Or list all recent sessions:

```bash
memory-bank sessions --limit 20
```

### Step 3: Retrieve full session context

Once you have the session ID, pull messages from that session:

```bash
memory-bank session <session-uuid>
```

Or search within a specific session for targeted results:

```bash
memory-bank search "topic" --session <session-uuid> --agent --limit 50
```

### Step 4: Synthesize and present

- Extract the key decisions, approaches, and outcomes from the session
- Present a concise summary focused on what's relevant to the current task
- Quote specific messages when precision matters (e.g., exact commands, config values)
- Note the date and project for temporal context

## Tips

- Start broad ("auth refactor") and narrow to specific sessions
- Use `--project` filter when the user mentions a specific project
- Use `--role assistant` to focus on what Claude recommended
- Use `--role user` to focus on what the user described/requested
- Multiple search queries may be needed to find the right session
- If a session is very long, use targeted searches within it rather than pulling everything
- Use `--current-project` to automatically scope to the current git project
