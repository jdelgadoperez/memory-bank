from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import rich_click as click

from memory_bank.cli import CONTEXT_SETTINGS, cli, console
from memory_bank.db import MemoryDB

# ---------------------------------------------------------------------------
# Shared hook helpers (also used by commands/setup.py)
# ---------------------------------------------------------------------------

SETTINGS_PATH = Path("~/.claude/settings.json").expanduser()

STOP_HOOK_COMMAND = (
    "memory-bank ingest claude-code"
    " >> ~/.memory-bank/ingest.log 2>&1 &"
)

START_CONTEXT_COMMAND = (
    "memory-bank hooks context-summary"
    " >> ~/.memory-bank/ingest.log 2>&1 &"
)

# The command is wrapped in a subshell so the redirect + backgrounding apply
# and the trailing "# precompact" comment stays a genuine shell comment (used
# only as an install/uninstall identity marker). The subshell also keeps this
# command from containing STOP_HOOK_MARKER ("...claude-code >>"), so the Stop
# and PreCompact hooks remain independently installable.
PRECOMPACT_HOOK_COMMAND = (
    "( memory-bank ingest claude-code )"
    " >> ~/.memory-bank/ingest.log 2>&1 &"
    "  # precompact"
)

DISTILL_HOOK_COMMAND = (
    "memory-bank distill --since 3h"
    " >> ~/.memory-bank/ingest.log 2>&1 &"
)

STOP_HOOK_MARKER = "memory-bank ingest claude-code >>"
START_HOOK_MARKER = "memory-bank hooks context-summary"
PRECOMPACT_HOOK_MARKER = "# precompact"
DISTILL_HOOK_MARKER = "memory-bank distill"

from memory_bank.commands._recall_guard import (  # noqa: E402
    RECALL_HOOK_COMMAND,
    RECALL_HOOK_MARKER,
    RECALL_LIMIT,
    RECALL_MIN_SCORE,
    RECALL_SNIPPET_LENGTH,
    SKIP_RECALL_PATTERNS,
    should_skip_recall,
)

__all__ = [
    "RECALL_HOOK_COMMAND",
    "RECALL_HOOK_MARKER",
    "RECALL_MIN_SCORE",
    "RECALL_LIMIT",
    "RECALL_SNIPPET_LENGTH",
    "SKIP_RECALL_PATTERNS",
    "should_skip_recall",
]

MCP_SERVER_NAME = "memory-bank"
MCP_SERVER_CONFIG: dict[str, Any] = {
    "command": "memory-bank",
    "args": ["mcp"],
}


def load_settings(path: Path | None = None) -> dict[str, Any]:
    p = path or SETTINGS_PATH
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError as exc:
            raise click.ClickException(
                f"Could not parse {p}: {exc}\n"
                "Fix the JSON syntax before running this command."
            ) from exc
    return {}


def save_settings(settings: dict[str, Any], path: Path | None = None) -> None:
    p = path or SETTINGS_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(settings, indent=2) + "\n")


def hook_entry(command: str) -> dict[str, Any]:
    return {
        "matcher": "",
        "hooks": [{"type": "command", "command": command}],
    }


def is_installed(settings: dict[str, Any], hook_type: str, marker: str) -> bool:
    return _find_hook_command(settings, hook_type, marker) is not None


def _find_hook_command(
    settings: dict[str, Any], hook_type: str, marker: str
) -> dict[str, Any] | None:
    """Return the inner command dict for an installed hook, or None.

    Matching is by marker substring so an already-installed hook can be both
    detected and upgraded in place when its command string has changed.
    """
    for entry in settings.get("hooks", {}).get(hook_type, []):
        for h in entry.get("hooks", []):
            if marker in h.get("command", ""):
                return h
    return None


def is_mcp_installed(settings: dict[str, Any]) -> bool:
    return MCP_SERVER_NAME in settings.get("mcpServers", {})


def install_mcp(settings: dict[str, Any]) -> bool:
    """Add memory-bank MCP server to settings. Returns True if added."""
    if is_mcp_installed(settings):
        return False
    settings.setdefault("mcpServers", {})[MCP_SERVER_NAME] = MCP_SERVER_CONFIG.copy()
    return True


def remove_mcp(settings: dict[str, Any]) -> bool:
    """Remove memory-bank MCP server from settings. Returns True if removed."""
    servers = settings.get("mcpServers", {})
    if MCP_SERVER_NAME in servers:
        del servers[MCP_SERVER_NAME]
        if not servers:
            del settings["mcpServers"]
        return True
    return False


def remove_hooks(path: Path | None = None) -> list[str]:
    """Remove all memory-bank hooks from settings. Returns list of removed event names."""
    p = path or SETTINGS_PATH
    if not p.exists():
        return []

    settings = load_settings(p)
    removed: list[str] = []

    all_markers = (STOP_HOOK_MARKER, START_HOOK_MARKER, PRECOMPACT_HOOK_MARKER, RECALL_HOOK_MARKER, DISTILL_HOOK_MARKER)
    for event in list(settings.get("hooks", {}).keys()):
        before = settings["hooks"][event]
        after = [
            entry for entry in before
            if not any(
                any(marker in h.get("command", "") for marker in all_markers)
                for h in entry.get("hooks", [])
            )
        ]
        if len(after) < len(before):
            if after:
                settings["hooks"][event] = after
            else:
                del settings["hooks"][event]
            removed.append(event)

    if removed:
        p.write_text(json.dumps(settings, indent=2) + "\n")
    return removed


@cli.group(context_settings=CONTEXT_SETTINGS)
def hooks():
    """Install or remove Claude Code auto-ingest hooks.

    Hooks run memory-bank ingest automatically at the end of every
    Claude Code session so your vector DB stays up to date without
    any manual steps.

    \b
    Quick start:
      memory-bank hooks install           # adds a Stop hook (ingest after session)
      memory-bank hooks install --on start  # adds a SessionStart context-summary hook
      memory-bank hooks install --on both   # both
      memory-bank hooks status
      memory-bank hooks uninstall
    """


@hooks.command(context_settings=CONTEXT_SETTINGS)
@click.option(
    "--on",
    "trigger",
    type=click.Choice(["stop", "start", "precompact", "recall", "distill", "both", "recommended", "all"]),
    default="recommended",
    show_default=True,
    help=(
        "Which Claude Code hook event to attach to.\n\n"
        "stop        = after each session ends — runs ingest\n"
        "start       = when a new session begins — writes a context summary\n"
        "precompact  = before context compaction — captures full transcript\n"
        "recall      = before each prompt — injects relevant past context\n"
        "distill     = after each session ends — generates AI summaries (requires ANTHROPIC_API_KEY)\n"
        "both        = stop + start\n"
        "recommended = stop + recall + distill (default)\n"
        "all         = stop + start + precompact + recall + distill"
    ),
)
@click.option(
    "--settings",
    "settings_path",
    type=click.Path(),
    default=None,
    metavar="FILE",
    help="Override path to settings.json. Defaults to ~/.claude/settings.json.",
)
def install(trigger, settings_path):
    """Add auto-ingest hook(s) to ~/.claude/settings.json.

    [bold]Stop hook[/bold] (default): runs [dim]memory-bank ingest claude-code[/dim]
    in the background after each session ends.

    [bold]SessionStart hook[/bold]: at session start, searches the DB for past work
    related to the current project, writes a brief summary to
    [dim]~/.memory-bank/context.md[/dim], and injects it into the project's
    [dim]CLAUDE.local.md[/dim] (untracked) so Claude Code picks it up automatically.

    Appends entries to settings.json. Existing hooks are preserved.
    Re-running is safe — already-installed hooks are skipped.

    \b
    Examples:
      memory-bank hooks install
      memory-bank hooks install --on both
      memory-bank hooks install --settings /path/to/settings.json
    """
    path = Path(settings_path).expanduser() if settings_path else SETTINGS_PATH
    settings = load_settings(path)
    hooks_cfg = settings.setdefault("hooks", {})

    plan = []
    if trigger in ("stop", "both", "all"):
        plan.append(("Stop", STOP_HOOK_COMMAND, STOP_HOOK_MARKER))
    if trigger in ("start", "both", "all"):
        plan.append(("SessionStart", START_CONTEXT_COMMAND, START_HOOK_MARKER))
    if trigger in ("precompact", "all"):
        plan.append(("PreCompact", PRECOMPACT_HOOK_COMMAND, PRECOMPACT_HOOK_MARKER))
    if trigger in ("recall", "recommended", "all"):
        plan.append(("UserPromptSubmit", RECALL_HOOK_COMMAND, RECALL_HOOK_MARKER))
    if trigger in ("distill", "recommended", "all"):
        plan.append(("Stop", DISTILL_HOOK_COMMAND, DISTILL_HOOK_MARKER))

    if trigger in ("distill", "recommended", "all") and not os.environ.get("ANTHROPIC_API_KEY"):
        console.print(
            "[yellow]Warning:[/yellow] ANTHROPIC_API_KEY is not set. "
            "The distill hook requires it — set the key before the hook fires."
        )

    installed_any = False
    for event, command, marker in plan:
        existing = _find_hook_command(settings, event, marker)
        if existing is not None:
            if existing.get("command") == command:
                console.print(f"[yellow]Already installed:[/yellow] {event} hook — skipping.")
                continue
            # Marker matches but the command string is stale — upgrade in place.
            existing["command"] = command
            console.print(f"[bold green]Updated:[/bold green] {event} hook → [dim]{command}[/dim]")
            installed_any = True
            continue
        hooks_cfg.setdefault(event, []).append(hook_entry(command))
        console.print(f"[bold green]Installed:[/bold green] {event} hook → [dim]{command}[/dim]")
        installed_any = True

    if installed_any:
        save_settings(settings, path)
        console.print(f"[dim]Saved to {path}[/dim]")

        if trigger in ("start", "both"):
            console.print(
                "\n[dim]SessionStart hook writes context to "
                "[bold]~/.memory-bank/context.md[/bold] and injects it into "
                "the project's [bold]CLAUDE.local.md[/bold] (untracked).[/dim]"
            )
    else:
        console.print("[dim]Nothing changed.[/dim]")


def _inject_claude_local(project_root: Path, content: str) -> None:
    """Inject or update the memory-bank section in the project's CLAUDE.local.md.

    CLAUDE.local.md is the conventional untracked sibling to CLAUDE.md that
    Claude Code auto-loads. Writing there keeps per-session context out of
    version control.

    Uses HTML comment markers to fence the memory-bank block so any other
    content the user keeps in CLAUDE.local.md is preserved. Safe to call
    repeatedly — existing block is replaced, new block is appended if not
    present.

    Also strips a legacy memory-bank block from a tracked CLAUDE.md if one
    is present, so the historical injection stops appearing in diffs.
    """
    claude_local = project_root / "CLAUDE.local.md"
    start_marker = "<!-- memory-bank:start -->"
    end_marker = "<!-- memory-bank:end -->"
    block = f"{start_marker}\n{content}\n{end_marker}\n"
    pattern = re.compile(
        r"\n*<!-- memory-bank:start -->.*?<!-- memory-bank:end -->\n?",
        re.DOTALL,
    )

    if claude_local.exists():
        existing = claude_local.read_text()
        if pattern.search(existing):
            new_text = pattern.sub("\n\n" + block, existing)
        else:
            new_text = existing.rstrip("\n") + "\n\n" + block
    else:
        new_text = block

    claude_local.write_text(new_text)

    legacy = project_root / "CLAUDE.md"
    if legacy.exists():
        legacy_text = legacy.read_text()
        if pattern.search(legacy_text):
            legacy.write_text(pattern.sub("", legacy_text).rstrip("\n") + "\n")


@hooks.command("context-summary", context_settings=CONTEXT_SETTINGS, hidden=True)
@click.option(
    "--db",
    type=click.Path(),
    default=None,
    envvar="MEMORY_BANK_DB",
    metavar="DIR",
)
@click.option("--limit", default=5, type=int)
def context_summary(db, limit):
    """
    [Internal] Called by the SessionStart hook.

    Searches for recent work related to the current git project and writes
    a Markdown summary to ~/.memory-bank/context.md.  Also injects the
    summary into the project's CLAUDE.md (fenced with HTML comment markers)
    so Claude Code picks it up automatically.
    """
    db_obj = MemoryDB(Path(db) if db else None)

    # Detect current project from git
    project = None
    project_root = None
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        project_root = Path(r.stdout.strip())
        project = project_root.name
    except Exception:
        pass

    query = f"recent work {project}" if project else "recent work"
    results = db_obj.search(
        query=query,
        limit=limit,
        project=project,
        since=None,
        before=None,
    )

    out_path = Path.home() / ".memory-bank" / "context.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    from datetime import UTC, datetime
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# Memory Bank Context  ·  {now}",
        f"Project: **{project or 'unknown'}**\n",
        "## Relevant past work\n",
    ]

    if not results:
        lines.append("_No relevant past sessions found._\n")
    else:
        for r in results:
            date = (r.get("timestamp") or "")[:10]
            role = r.get("role", "?")
            proj = r.get("project", "")
            snippet = r.get("content", "")[:300]
            if len(r.get("content", "")) > 300:
                snippet += "…"
            sid = r.get("session_id", "")
            cat = r.get("category", "")
            meta = f"project: {proj}  |  session: `{sid[:16]}`"
            if cat:
                meta += f"  |  [{cat}]"
            lines.append(f"**[{role}]** {date}  |  {meta}")
            lines.append(f"> {snippet}\n")

    summary_text = "\n".join(lines)
    out_path.write_text(summary_text)
    console.print(f"[dim]Context summary written to {out_path}[/dim]")

    # Inject into project CLAUDE.local.md (untracked) for automatic Claude Code pickup
    if project_root:
        try:
            _inject_claude_local(project_root, summary_text)
            console.print(f"[dim]Injected context into {project_root / 'CLAUDE.local.md'}[/dim]")
        except Exception as exc:
            console.print(f"[yellow]Warning:[/yellow] could not update CLAUDE.local.md: {exc}")


def _read_hook_prompt() -> str:
    """Resolve the user prompt for the recall hook.

    Order of precedence:
      1. ``CLAUDE_USER_PROMPT`` env var (legacy / manual invocation).
      2. JSON on stdin — Claude Code's actual ``UserPromptSubmit`` contract
         delivers ``{"prompt": ...}`` on stdin, not via an env var.
      3. Raw stdin text (if it isn't JSON).

    Reading stdin is skipped when it is an interactive TTY so a manual
    ``memory-bank hooks recall`` doesn't block waiting for input.
    """
    env_prompt = os.environ.get("CLAUDE_USER_PROMPT", "")
    if env_prompt.strip():
        return env_prompt

    try:
        if sys.stdin is None or sys.stdin.isatty():
            return env_prompt
        raw = sys.stdin.read()
    except Exception:
        return env_prompt

    if not raw.strip():
        return env_prompt
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return raw  # not JSON — treat the whole payload as the prompt
    if isinstance(data, dict):
        return str(data.get("prompt", "") or "")
    return env_prompt


@hooks.command("recall", context_settings=CONTEXT_SETTINGS, hidden=True)
@click.option(
    "--db",
    type=click.Path(),
    default=None,
    envvar="MEMORY_BANK_DB",
    metavar="DIR",
)
def recall(db):
    """
    [Internal] Called by the UserPromptSubmit hook.

    Searches memory-bank for context relevant to the current user prompt
    and prints it to stdout for injection into Claude's context.
    Disable with MEMORY_BANK_RECALL=0.
    """
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as FuturesTimeoutError

    # Toggle check
    if os.environ.get("MEMORY_BANK_RECALL") == "0":
        return

    # Read the prompt. Claude Code delivers the UserPromptSubmit payload as
    # JSON on stdin ({"prompt": ...}); older builds / manual runs may set the
    # CLAUDE_USER_PROMPT env var. Prefer the env var when present (keeps manual
    # invocation predictable), otherwise fall back to stdin.
    prompt = _read_hook_prompt()
    if not prompt.strip():
        return

    # Skip guard
    if should_skip_recall(prompt):
        return

    # Truncate query
    query = prompt[:512]

    # Detect project
    project = None
    project_name = None
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        project_root = r.stdout.strip()
        project_name = Path(project_root).name
        project = project_name
    except Exception:
        pass

    # Search with timeout — MemoryDB init included so Docker/Qdrant connection
    # attempts are also bounded by the timeout, not just the search itself.
    db_path = Path(db) if db else None

    from memory_bank.commands.distill import SUMMARY_ROLE

    def _search():
        db = MemoryDB(db_path)
        # Over-fetch so we have enough candidates after summary/raw preference logic.
        return db.search(query=query, limit=15, project=project)

    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            results = pool.submit(_search).result(timeout=2.0)
        except FuturesTimeoutError:
            return
        except Exception as exc:
            print(f"recall: search error: {exc}", file=sys.stderr)
            return

    # Filter by min score
    results = [r for r in results if r.get("score", 0) >= RECALL_MIN_SCORE]

    # Prefer distilled summaries over raw turns.
    # If a session has a summary record, use it instead of the raw snippet.
    summaries: dict[str, dict] = {}
    raw: list[dict] = []
    for r in results:
        if r.get("role") == SUMMARY_ROLE:
            sid = r.get("session_id", "")
            if sid not in summaries or r.get("score", 0) > summaries[sid].get("score", 0):
                summaries[sid] = r
        else:
            raw.append(r)

    summarized_sessions = set(summaries.keys())
    deduplicated: list[dict] = list(summaries.values())[:RECALL_LIMIT]
    seen_sessions: set[str] = set(summarized_sessions)

    for r in raw:
        sid = r.get("session_id", "")
        if sid not in seen_sessions:
            deduplicated.append(r)
            seen_sessions.add(sid)
        if len(deduplicated) >= RECALL_LIMIT:
            break

    if not deduplicated:
        return

    # Format output
    lines = [
        "<!-- memory-bank:recall -->",
        "The following past context is semantically relevant to the current prompt. "
        "Reference it if it helps — do not repeat it back to the user.",
        "",
    ]

    for r in deduplicated:
        date = (r.get("timestamp") or "")[:10]
        role = r.get("role", "?")
        sid = r.get("session_id", "")
        result_project = r.get("project", "")
        is_summary = role == SUMMARY_ROLE

        meta = f"{date} | session: `{sid[:16]}`"
        if result_project and result_project != project_name:
            meta += f" | project: {result_project}"
        if is_summary:
            meta += " (distilled)"
        else:
            meta += f" ({role})"

        lines.append(f"- {meta}")

        if is_summary:
            # Summaries are already condensed — show full content up to a wider limit.
            content = r.get("content", "")
            for bullet in content.splitlines():
                bullet = bullet.strip()
                if bullet:
                    lines.append(f"  {bullet}")
        else:
            snippet = r.get("content", "")[:RECALL_SNIPPET_LENGTH]
            if len(r.get("content", "")) > RECALL_SNIPPET_LENGTH:
                snippet += "…"
            lines.append(f"  > {snippet}")

        lines.append("")

    lines.append("<!-- /memory-bank:recall -->")

    # Print to stdout for Claude injection
    click.echo("\n".join(lines))


@hooks.command(context_settings=CONTEXT_SETTINGS)
@click.option(
    "--settings",
    "settings_path",
    type=click.Path(),
    default=None,
    metavar="FILE",
    help="Override path to settings.json.",
)
def uninstall(settings_path):
    """Remove all memory-bank auto-ingest hooks from ~/.claude/settings.json."""
    path = Path(settings_path).expanduser() if settings_path else SETTINGS_PATH
    if not path.exists():
        console.print("[yellow]No settings.json found — nothing to remove.[/yellow]")
        return

    removed = remove_hooks(path)
    for event in removed:
        console.print(f"[bold green]Removed:[/bold green] {event} hook.")
    if removed:
        console.print(f"[dim]Saved to {path}[/dim]")
    else:
        console.print("[yellow]No memory-bank hooks found.[/yellow]")


@hooks.command(context_settings=CONTEXT_SETTINGS)
@click.option(
    "--settings",
    "settings_path",
    type=click.Path(),
    default=None,
    metavar="FILE",
    help="Override path to settings.json.",
)
def status(settings_path):
    """Show whether auto-ingest hooks are currently installed."""
    path = Path(settings_path).expanduser() if settings_path else SETTINGS_PATH
    if not path.exists():
        console.print(f"[yellow]No settings.json found at {path}[/yellow]")
        return

    settings = load_settings(path)

    checks = [
        ("Stop", STOP_HOOK_MARKER, "ingest"),
        ("Stop", DISTILL_HOOK_MARKER, "distill"),
        ("SessionStart", START_HOOK_MARKER, "context-summary"),
        ("PreCompact", PRECOMPACT_HOOK_MARKER, "pre-compaction ingest"),
        ("UserPromptSubmit", RECALL_HOOK_MARKER, "recall"),
    ]
    for event, marker, kind in checks:
        if is_installed(settings, event, marker):
            console.print(f"[bold green]✓[/bold green]  {event} hook  [dim]({kind}) installed[/dim]")
        else:
            console.print(f"[dim]✗  {event} hook  ({kind}) not installed[/dim]")

    console.print(f"\n[dim]Settings file: {path}[/dim]")
