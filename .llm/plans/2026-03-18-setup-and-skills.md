# Setup Command & Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `memory-bank setup` command that installs skills and hooks with correct paths, update the `memory-search` skill with session-level features, and create a new `memory-recall` skill for full context retrieval.

**Architecture:** A `setup` CLI command resolves the memory-bank install path at runtime (`Path(__file__).resolve()`) and uses it to symlink skills into `~/.claude/skills/` and install hooks. Skills use `MEMORY_BANK_PATH` placeholder in source, which gets replaced during symlink (skills are plain markdown read by Claude — symlinks point to the repo, so no rewriting needed). The session-start hook template gets path substitution on install.

**Tech Stack:** Python (Click CLI), Markdown (SKILL.md files), Bash (hook scripts)

---

## File Structure

```
src/memory_bank/
├── cli.py              — Modify: add `setup` command group (install, uninstall, status)
skills/
├── memory-search/
│   └── SKILL.md        — Rewrite: add session commands, date filters, fix paths
├── memory-recall/
│   └── SKILL.md        — Create: full context recall skill
```

## Key Design Decisions

1. **Skills stay in the repo as source of truth.** `setup` symlinks them into `~/.claude/skills/`. No file copying or path rewriting needed — Claude reads the SKILL.md at the symlink target, and the skill content uses `memory-bank` CLI commands (which are on PATH after install).

2. **`setup` replaces `hooks install` for onboarding.** `setup` does everything: symlink skills + install hooks + verify `memory-bank` is on PATH. The existing `hooks` subcommand stays for granular hook management.

3. **The session-start.sh hook is project-local** (`.claude/hooks/`). It's only for the memory-bank repo itself during development. The global setup uses `~/.claude/settings.json` hooks (already implemented). The project-local hook gets its paths fixed and loops over all skills dynamically.

4. **`memory-recall` vs `memory-search`:** Search returns ranked snippets. Recall drills into a full session and synthesizes context. They're separate skills because they serve different workflows and trigger on different user intents.

5. **No `--date-from`/`--date-to` in skills.** The `search` CLI command does not currently expose date filter flags (only `db.py` supports them internally). Skills must only reference flags that exist. Date filters can be added as a separate task later.

6. **`_repo_root()` validates `skills/` exists.** Prevents silent misbehavior if package is installed non-editable.

7. **Shared hook removal logic.** Extract `_remove_hooks()` helper used by both `hooks uninstall` and `setup uninstall` to avoid duplication.

---

### Task 1: Update `memory-search` skill

**Files:**
- Modify: `skills/memory-search/SKILL.md`

- [ ] **Step 1: Rewrite the skill with session-level commands**

Replace the current SKILL.md with updated content covering:
- Message-level search (existing): `memory-bank search "query" [filters]`
- Session-level search (new): `memory-bank search "query" --json` to find sessions
- Session listing: `memory-bank search` with `--project` and `--source` filters
- JSON output for programmatic parsing
- Remove all hardcoded `/home/user/memory-bank` paths — use `memory-bank` CLI directly (assumes it's on PATH after `uv pip install -e .`)
- Setup check: just `memory-bank stats` (if not found, tell user to run `memory-bank setup` or `uv pip install -e /path/to/memory-bank`)
- NOTE: Do NOT include `--date-from`/`--date-to` — these flags don't exist in the CLI yet

```markdown
---
name: memory-search
description: Search past Claude chat history using the memory-bank vector DB. Use when the user asks about previous conversations, past solutions, or wants to find something discussed in an earlier session.
allowed-tools: Bash, Read
---

# Memory Bank Search

Search semantically over ingested Claude Code and Claude Desktop chat histories stored in a local Qdrant vector DB.

## When to use

Activate when the user asks:
- "Did we talk about X before?"
- "What was that solution for Y?"
- "Find past conversations about Z"
- "What have I worked on related to X?"
- "Search my chat history for..."
- "Have I seen this error before?"

## Prerequisites

Verify the CLI is available and has data:

\`\`\`bash
memory-bank stats
\`\`\`

If the command is not found, the user needs to install memory-bank and run setup.
If the DB is empty (0 messages), ingest first:

\`\`\`bash
memory-bank ingest claude-code
\`\`\`

## Search commands

### Basic semantic search
\`\`\`bash
memory-bank search "your query here"
\`\`\`

### With filters
\`\`\`bash
# Filter by source
memory-bank search "query" --source claude-code

# Filter by project
memory-bank search "query" --project my-project

# Only user messages or only assistant responses
memory-bank search "query" --role user
memory-bank search "query" --role assistant

# Within a specific session
memory-bank search "query" --session <session-uuid>

# More results
memory-bank search "query" --limit 20

# JSON output for programmatic use
memory-bank search "query" --json
\`\`\`

## Workflow

1. Run the search command with the user's query
2. Read the results (score, role, source/project, timestamp, content preview)
3. Summarize the most relevant findings to the user
4. If the user wants more detail from a specific result, use the memory-recall skill to pull the full session context
5. If results are empty, suggest refining the query or running `memory-bank ingest claude-code`
```

- [ ] **Step 2: Verify the skill markdown is valid**

```bash
head -5 skills/memory-search/SKILL.md
```

Expected: frontmatter with `---` delimiters and `name: memory-search`

- [ ] **Step 3: Commit**

```bash
git -C /Users/jessdelgadoperez/projects/memory-bank add skills/memory-search/SKILL.md
git -C /Users/jessdelgadoperez/projects/memory-bank commit -m "feat: update memory-search skill with session-level commands and setup instructions"
```

---

### Task 2: Create `memory-recall` skill

**Files:**
- Create: `skills/memory-recall/SKILL.md`

- [ ] **Step 1: Create the skill directory and SKILL.md**

```markdown
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

\`\`\`bash
memory-bank stats
\`\`\`

If 0 sessions, run: `memory-bank ingest claude-code`

## Recall workflow

### Step 1: Find the relevant session

Use search with JSON output to find matching sessions:

\`\`\`bash
memory-bank search "topic keywords" --json --limit 5
\`\`\`

Look at the `session_id` field in results to identify which session(s) are relevant.

If you need to narrow by project:

\`\`\`bash
memory-bank search "topic" --project project-name --json
\`\`\`

### Step 2: Retrieve full session context

Once you have the session_id, search within that session to get the relevant messages:

\`\`\`bash
memory-bank search "topic" --session <session-uuid> --json --limit 50
\`\`\`

### Step 3: Synthesize and present

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
```

- [ ] **Step 2: Verify the skill exists and is valid**

```bash
head -5 skills/memory-recall/SKILL.md
```

Expected: frontmatter with `name: memory-recall`

- [ ] **Step 3: Commit**

```bash
git -C /Users/jessdelgadoperez/projects/memory-bank add skills/memory-recall/SKILL.md
git -C /Users/jessdelgadoperez/projects/memory-bank commit -m "feat: add memory-recall skill for full session context retrieval"
```

---

### Task 3: Add `memory-bank setup` CLI command

**Files:**
- Modify: `src/memory_bank/cli.py`

This task adds a `setup` command group with `install`, `uninstall`, and `status` subcommands.

- [ ] **Step 1: Define the setup helper functions**

Add above the existing `hooks` section in `cli.py`. The helpers resolve the repo root from `__file__`, find skills in `skills/*/SKILL.md`, and manage symlinks.

```python
# ---------------------------------------------------------------------------
# setup command group
# ---------------------------------------------------------------------------

_SKILLS_TARGET = Path("~/.claude/skills").expanduser()


def _repo_root() -> Path:
    """Resolve the memory-bank repo root from this file's location."""
    root = Path(__file__).resolve().parent.parent.parent
    if not (root / "skills").is_dir():
        raise click.ClickException(
            f"Cannot find skills/ directory at {root}. "
            "memory-bank must be installed in editable mode (uv pip install -e .)."
        )
    return root


def _available_skills() -> list[tuple[str, Path]]:
    """Return (name, path) pairs for all skills in the repo."""
    skills_dir = _repo_root() / "skills"
    if not skills_dir.is_dir():
        return []
    return [
        (d.name, d)
        for d in sorted(skills_dir.iterdir())
        if d.is_dir() and (d / "SKILL.md").exists()
    ]
```

- [ ] **Step 2: Add the `setup` command group and `install` subcommand**

```python
@cli.group(context_settings=CONTEXT_SETTINGS)
def setup():
    """Set up memory-bank integration with Claude Code.

    Installs skills into ~/.claude/skills/ and hooks into
    ~/.claude/settings.json so memory-bank is available in
    every Claude Code session.

    \b
    Quick start:
      memory-bank setup install
      memory-bank setup status
      memory-bank setup uninstall
    """


@setup.command(context_settings=CONTEXT_SETTINGS)
@click.option(
    "--skip-hooks", is_flag=True, default=False,
    help="Only install skills, skip hook installation.",
)
@click.option(
    "--on",
    "trigger",
    type=click.Choice(["stop", "start", "both"]),
    default="stop",
    show_default=True,
    help="Which hook event to use (ignored with --skip-hooks).",
)
def install(skip_hooks, trigger):
    """Install skills and hooks for Claude Code integration.

    Symlinks memory-bank skills into ~/.claude/skills/ and
    installs auto-ingest hooks into ~/.claude/settings.json.

    \b
    Examples:
      memory-bank setup install
      memory-bank setup install --skip-hooks
      memory-bank setup install --on both
    """
    repo = _repo_root()
    skills = _available_skills()

    # Install skills
    _SKILLS_TARGET.mkdir(parents=True, exist_ok=True)
    for name, skill_path in skills:
        target = _SKILLS_TARGET / name
        if target.is_symlink():
            existing = target.resolve()
            if existing == skill_path.resolve():
                console.print(f"  [dim]✓ {name} — already linked[/dim]")
                continue
            else:
                target.unlink()
        elif target.exists():
            console.print(
                f"  [yellow]⚠ {name} — exists but is not a symlink, skipping[/yellow]"
            )
            continue
        target.symlink_to(skill_path)
        console.print(f"  [bold green]✓[/bold green] {name} → [dim]{skill_path}[/dim]")

    # Install hooks (reuse existing logic)
    if not skip_hooks:
        console.print()
        event_map = {
            "stop": ["Stop"],
            "start": ["SessionStart"],
            "both": ["Stop", "SessionStart"],
        }
        settings = _load_settings()
        hooks_cfg = settings.setdefault("hooks", {})
        installed_any = False

        for event in event_map[trigger]:
            if _is_installed(settings, event):
                console.print(f"  [dim]✓ {event} hook — already installed[/dim]")
                continue
            hooks_cfg.setdefault(event, []).append(_hook_entry(event))
            console.print(
                f"  [bold green]✓[/bold green] {event} hook → [dim]{_HOOK_COMMAND}[/dim]"
            )
            installed_any = True

        if installed_any:
            _save_settings(settings)

    console.print(
        "\n[bold green]Setup complete.[/bold green] "
        "Skills and hooks are ready for your next Claude Code session."
    )
```

- [ ] **Step 3: Extract shared `_remove_hooks()` helper and add `uninstall` subcommand**

First, extract the hook removal logic into a shared helper (used by both `hooks uninstall` and `setup uninstall`). Add this near the other hook helpers:

```python
def _remove_hooks(settings_path: Path | None = None) -> bool:
    """Remove all memory-bank hooks from settings. Returns True if any were removed."""
    import json

    path = settings_path or _SETTINGS_PATH
    if not path.exists():
        return False

    settings = json.loads(path.read_text())
    removed = False

    for event in list(settings.get("hooks", {}).keys()):
        before = settings["hooks"][event]
        after = [
            entry for entry in before
            if not any(
                _HOOK_MARKER in h.get("command", "")
                for h in entry.get("hooks", [])
            )
        ]
        if len(after) < len(before):
            if after:
                settings["hooks"][event] = after
            else:
                del settings["hooks"][event]
            console.print(f"  [bold green]✓[/bold green] Removed {event} hook")
            removed = True

    if removed:
        path.write_text(json.dumps(settings, indent=2) + "\n")
    return removed
```

Then update the existing `hooks uninstall` command to call `_remove_hooks()` instead of duplicating the logic. Then add the `setup uninstall` subcommand:

```python
@setup.command(context_settings=CONTEXT_SETTINGS)
def uninstall():
    """Remove memory-bank skills and hooks from Claude Code.

    Removes skill symlinks from ~/.claude/skills/ and
    auto-ingest hooks from ~/.claude/settings.json.
    """
    skills = _available_skills()
    removed_skills = False

    for name, skill_path in skills:
        target = _SKILLS_TARGET / name
        if target.is_symlink() and target.resolve() == skill_path.resolve():
            target.unlink()
            console.print(f"  [bold green]✓[/bold green] Removed skill: {name}")
            removed_skills = True

    if not removed_skills:
        console.print("  [dim]No memory-bank skills found.[/dim]")

    removed_hooks = _remove_hooks()
    if not removed_hooks and not removed_skills:
        console.print("  [dim]Nothing to remove.[/dim]")
```

- [ ] **Step 4: Add the `status` subcommand**

```python
@setup.command(context_settings=CONTEXT_SETTINGS)
def status():
    """Show what's currently installed.

    Checks skill symlinks and hook registrations.
    """
    import json

    skills = _available_skills()
    console.print("[bold]Skills[/bold]")
    for name, skill_path in skills:
        target = _SKILLS_TARGET / name
        if target.is_symlink() and target.resolve() == skill_path.resolve():
            console.print(f"  [bold green]✓[/bold green] {name}")
        elif target.exists():
            console.print(f"  [yellow]⚠[/yellow] {name} — exists but not linked to repo")
        else:
            console.print(f"  [dim]✗ {name} — not installed[/dim]")

    console.print("\n[bold]Hooks[/bold]")
    if _SETTINGS_PATH.exists():
        settings = json.loads(_SETTINGS_PATH.read_text())
        for event in ("Stop", "SessionStart"):
            if _is_installed(settings, event):
                console.print(f"  [bold green]✓[/bold green] {event}")
            else:
                console.print(f"  [dim]✗ {event} — not installed[/dim]")
    else:
        console.print("  [dim]No settings.json found[/dim]")

    # Check if memory-bank is on PATH
    import shutil
    console.print("\n[bold]CLI[/bold]")
    if shutil.which("memory-bank"):
        console.print("  [bold green]✓[/bold green] memory-bank on PATH")
    else:
        console.print(
            "  [yellow]⚠[/yellow] memory-bank not on PATH — "
            "run: uv pip install -e /path/to/memory-bank"
        )
```

- [ ] **Step 5: Register `setup` in rich-click command groups**

Update the `COMMAND_GROUPS` dict at the top of `cli.py`:

```python
click.rich_click.COMMAND_GROUPS = {
    "memory-bank": [
        {
            "name": "Ingestion",
            "commands": ["ingest"],
        },
        {
            "name": "Query & Manage",
            "commands": ["search", "stats", "delete", "ui"],
        },
        {
            "name": "Integration",
            "commands": ["setup", "hooks"],
        },
    ],
    # ... rest unchanged
}
```

- [ ] **Step 6: Verify CLI loads and `setup` group appears**

```bash
cd /Users/jessdelgadoperez/projects/memory-bank && .venv/bin/memory-bank setup --help
```

Expected: shows `install`, `uninstall`, `status` subcommands.

- [ ] **Step 7: Test `setup install` and `setup status`**

```bash
cd /Users/jessdelgadoperez/projects/memory-bank && .venv/bin/memory-bank setup status
```

Expected: shows skills not installed, shows hook status.

```bash
cd /Users/jessdelgadoperez/projects/memory-bank && .venv/bin/memory-bank setup install --skip-hooks
```

Expected: symlinks `memory-search` and `memory-recall` into `~/.claude/skills/`.

```bash
ls -la ~/.claude/skills/memory-search ~/.claude/skills/memory-recall
```

Expected: symlinks pointing to the repo's `skills/` directory.

- [ ] **Step 8: Commit**

```bash
git -C /Users/jessdelgadoperez/projects/memory-bank add src/memory_bank/cli.py
git -C /Users/jessdelgadoperez/projects/memory-bank commit -m "feat: add setup command for skills and hooks installation"
```

---

### Task 4: Fix project-local session-start hook paths

**Files:**
- Modify: `.claude/hooks/session-start.sh`

- [ ] **Step 1: Update the hardcoded paths**

Replace `/home/user/memory-bank` with the actual path or a dynamic resolution.

```bash
#!/bin/bash
set -euo pipefail

echo '{"async": true, "asyncTimeout": 300000}'

MEMORY_BANK_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

# Install memory-bank and dependencies in editable mode
uv pip install -e "${MEMORY_BANK_DIR}" --quiet

# Symlink all skills into ~/.claude/skills/
mkdir -p "${HOME}/.claude/skills"
for skill_dir in "${MEMORY_BANK_DIR}"/skills/*/; do
    skill_name="$(basename "${skill_dir}")"
    target="${HOME}/.claude/skills/${skill_name}"
    if [ ! -e "${target}" ]; then
        ln -s "${skill_dir}" "${target}"
        echo "Installed ${skill_name} skill -> ${target}"
    fi
done
```

- [ ] **Step 2: Verify the hook resolves correctly**

```bash
bash -c 'MEMORY_BANK_DIR="$(cd "/Users/jessdelgadoperez/projects/memory-bank/.claude/hooks/../.." && pwd)" && echo $MEMORY_BANK_DIR'
```

Expected: `/Users/jessdelgadoperez/projects/memory-bank`

- [ ] **Step 3: Commit**

```bash
git -C /Users/jessdelgadoperez/projects/memory-bank add .claude/hooks/session-start.sh
git -C /Users/jessdelgadoperez/projects/memory-bank commit -m "fix: resolve hook paths dynamically instead of hardcoding"
```

---

### Task 5: Update CLAUDE.md and README with setup instructions

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`

- [ ] **Step 1: Update CLAUDE.md project structure and CLI reference**

Add `setup` to the CLI reference section and update project structure to include `memory-recall` skill.

- [ ] **Step 2: Update README.md**

Replace the manual symlink instructions in the "Claude Code skill" section with:

```markdown
## Setup (Claude Code integration)

\`\`\`bash
# Install skills and auto-ingest hooks in one step
memory-bank setup install

# Check what's installed
memory-bank setup status

# Remove everything
memory-bank setup uninstall
\`\`\`

This symlinks the `memory-search` and `memory-recall` skills into
`~/.claude/skills/` and adds a Stop hook to `~/.claude/settings.json`
for automatic ingestion after each session.
```

- [ ] **Step 3: Commit**

```bash
git -C /Users/jessdelgadoperez/projects/memory-bank add CLAUDE.md README.md
git -C /Users/jessdelgadoperez/projects/memory-bank commit -m "docs: update setup instructions for new setup command"
```
