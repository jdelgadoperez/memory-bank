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
uv tool install memory-bank
memory-bank setup install
```

If the DB is empty (0 messages), ingest first:

```bash
memory-bank ingest claude-code
```

## When to search vs. recall

| User asks | Approach |
|---|---|
| "Did we discuss X?" | Search first with `--agent` to find relevant messages |
| "Show me the full conversation about X" | Search to find session ID, then replay full session |
| "What was our solution for X?" | Search with `--role assistant` to focus on solutions |
| "What requirements did we discuss for X?" | Search with `--role user` to focus on requirements |
| "Remind me of that debugging session" | List sessions, then recall full session |

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

For long-running projects with many sessions, add a time range to reduce scope:

```bash
memory-bank search "topic" --agent --project my-app --since 30d
```

**If multiple sessions match with similar scores:** Refine the query with more specific keywords, add `--project` filtering, or inspect candidates with `memory-bank session <uuid>` before committing to one.

**If no sessions match:** Broaden the query (fewer or different keywords), remove `--since` filters, or switch to listing sessions directly with `memory-bank sessions --project <name>`.

### Step 2: Browse sessions (alternative)

List recent sessions for a project:

```bash
memory-bank sessions --project project-name --limit 10
```

Or list all recent sessions:

```bash
memory-bank sessions --limit 20
```

Filter by time range for large projects:

```bash
memory-bank sessions --project my-app --since 1m --before 1w
```

### Step 3: Retrieve full session context

Once you have the session ID, pull messages from that session:

```bash
memory-bank session <session-uuid>
```

Or search within a specific session for targeted results:

```bash
memory-bank search "topic" --session <session-uuid> --agent --limit 10
```

Add `--context` to include surrounding messages — useful to understand if a result was a solution or a dead-end:

```bash
memory-bank search "topic" --session <session-uuid> --agent --context 3
```

Use role filtering to focus the search:

```bash
# Focus on what Claude recommended (solutions, implementation)
memory-bank search "implementation" --session <session-uuid> --role assistant --agent

# Focus on what the user requested (requirements, questions)
memory-bank search "requirements" --session <session-uuid> --role user --agent
```

### Step 4: Synthesize and present

- Extract the key decisions, approaches, and outcomes from the session
- Present a concise summary focused on what's relevant to the current task
- Quote specific messages when precision matters (e.g., exact commands, config values)
- Note the date and project for temporal context
- For large sessions, use `--role` filters to narrow before synthesizing rather than reading everything

## Tips

- Start broad ("auth refactor") and narrow to specific sessions
- Use `--project` filter when the user mentions a specific project
- Use `--role assistant` to focus on what Claude recommended
- Use `--role user` to focus on what the user described/requested
- Multiple search queries may be needed to find the right session
- If a session is very long, use targeted searches within it with `--session <uuid>` + `--role` filter
- Use `--current-project` to automatically scope to the current git project

## Troubleshooting

| Problem | Solution |
|---|---|
| No results found | Rephrase query, lower `--min-score 0.3`, remove `--since` filters, or use `memory-bank sessions` to browse |
| Multiple sessions match | Inspect each with `memory-bank session <uuid>` to compare before choosing |
| "DB locked" error | Another process is ingesting — wait and retry, or check with `memory-bank stats` |
| Session is very large | Use `--session <uuid>` + `--role` filter to focus; add `--context N` for surrounding messages |
| Command not found | Run `uv tool install memory-bank && memory-bank setup install`, or ensure `~/.local/bin` is on your PATH |
