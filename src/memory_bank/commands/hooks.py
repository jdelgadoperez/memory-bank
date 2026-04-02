from __future__ import annotations

from pathlib import Path

import rich_click as click

from memory_bank.cli import CONTEXT_SETTINGS, console, cli


_SETTINGS_PATH = Path("~/.claude/settings.json").expanduser()

_STOP_HOOK_COMMAND = (
    "memory-bank ingest claude-code"
    " >> ~/.memory-bank/ingest.log 2>&1 &"
)

_START_CONTEXT_COMMAND = (
    "memory-bank hooks context-summary"
    " >> ~/.memory-bank/ingest.log 2>&1 &"
)

_STOP_HOOK_MARKER = "memory-bank ingest claude-code"
_START_HOOK_MARKER = "memory-bank hooks context-summary"


def _load_settings() -> dict:
    if _SETTINGS_PATH.exists():
        import json
        return json.loads(_SETTINGS_PATH.read_text())
    return {}


def _save_settings(settings: dict) -> None:
    import json
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_PATH.write_text(json.dumps(settings, indent=2) + "\n")


def _hook_entry(command: str) -> dict:
    return {
        "matcher": "",
        "hooks": [{"type": "command", "command": command}],
    }


def _is_installed(settings: dict, hook_type: str, marker: str) -> bool:
    for entry in settings.get("hooks", {}).get(hook_type, []):
        for h in entry.get("hooks", []):
            if marker in h.get("command", ""):
                return True
    return False


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
    type=click.Choice(["stop", "start", "both"]),
    default="stop",
    show_default=True,
    help=(
        "Which Claude Code hook event to attach to.\n\n"
        "stop  = after each session ends — runs ingest (recommended)\n"
        "start = when a new session begins — writes a context summary\n"
        "both  = both events"
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
    [dim]CLAUDE.md[/dim] so Claude Code picks it up automatically.

    Appends entries to settings.json. Existing hooks are preserved.
    Re-running is safe — already-installed hooks are skipped.

    \b
    Examples:
      memory-bank hooks install
      memory-bank hooks install --on both
      memory-bank hooks install --settings /path/to/settings.json
    """
    import json

    path = Path(settings_path).expanduser() if settings_path else _SETTINGS_PATH
    settings = _load_settings() if path == _SETTINGS_PATH else (
        {} if not path.exists() else json.loads(path.read_text())
    )
    hooks_cfg = settings.setdefault("hooks", {})

    plan = []
    if trigger in ("stop", "both"):
        plan.append(("Stop", _STOP_HOOK_COMMAND, _STOP_HOOK_MARKER))
    if trigger in ("start", "both"):
        plan.append(("SessionStart", _START_CONTEXT_COMMAND, _START_HOOK_MARKER))

    installed_any = False
    for event, command, marker in plan:
        if _is_installed(settings, event, marker):
            console.print(f"[yellow]Already installed:[/yellow] {event} hook — skipping.")
            continue
        hooks_cfg.setdefault(event, []).append(_hook_entry(command))
        console.print(f"[bold green]Installed:[/bold green] {event} hook → [dim]{command}[/dim]")
        installed_any = True

    if installed_any:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=2) + "\n")
        console.print(f"[dim]Saved to {path}[/dim]")

        if trigger in ("start", "both"):
            console.print(
                "\n[dim]SessionStart hook writes context to "
                "[bold]~/.memory-bank/context.md[/bold] and injects it into "
                "the project's [bold]CLAUDE.md[/bold].[/dim]"
            )
    else:
        console.print("[dim]Nothing changed.[/dim]")


def _inject_claude_md(project_root: Path, content: str) -> None:
    """Inject or update the memory-bank section in the project's CLAUDE.md.

    Uses HTML comment markers to fence the memory-bank block so the rest of
    the file is preserved exactly.  Safe to call repeatedly — existing block
    is replaced, new block is appended if not present.
    """
    import re

    claude_md = project_root / "CLAUDE.md"
    start_marker = "<!-- memory-bank:start -->"
    end_marker = "<!-- memory-bank:end -->"
    block = f"{start_marker}\n{content}\n{end_marker}\n"

    if claude_md.exists():
        existing = claude_md.read_text()
        pattern = re.compile(
            r"<!-- memory-bank:start -->.*?<!-- memory-bank:end -->\n?",
            re.DOTALL,
        )
        if pattern.search(existing):
            new_text = pattern.sub(block, existing)
        else:
            new_text = existing.rstrip("\n") + "\n\n" + block
    else:
        new_text = block

    claude_md.write_text(new_text)


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
    import subprocess
    from memory_bank.db import MemoryDB

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

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
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

    # Also inject into project CLAUDE.md for automatic Claude Code pickup
    if project_root:
        try:
            _inject_claude_md(project_root, summary_text)
            console.print(f"[dim]Injected context into {project_root / 'CLAUDE.md'}[/dim]")
        except Exception as exc:
            console.print(f"[yellow]Warning:[/yellow] could not update CLAUDE.md: {exc}")


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
    path = Path(settings_path).expanduser() if settings_path else _SETTINGS_PATH
    if not path.exists():
        console.print("[yellow]No settings.json found — nothing to remove.[/yellow]")
        return

    import json
    settings = json.loads(path.read_text())
    removed = False

    _all_markers = (_STOP_HOOK_MARKER, _START_HOOK_MARKER)
    for event in list(settings.get("hooks", {}).keys()):
        before = settings["hooks"][event]
        after = [
            entry for entry in before
            if not any(
                any(marker in h.get("command", "") for marker in _all_markers)
                for h in entry.get("hooks", [])
            )
        ]
        if len(after) < len(before):
            if after:
                settings["hooks"][event] = after
            else:
                del settings["hooks"][event]
            console.print(f"[bold green]Removed:[/bold green] {event} hook.")
            removed = True

    if removed:
        path.write_text(json.dumps(settings, indent=2) + "\n")
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
    path = Path(settings_path).expanduser() if settings_path else _SETTINGS_PATH
    if not path.exists():
        console.print(f"[yellow]No settings.json found at {path}[/yellow]")
        return

    import json
    settings = json.loads(path.read_text())

    checks = [
        ("Stop", _STOP_HOOK_MARKER, "ingest"),
        ("SessionStart", _START_HOOK_MARKER, "context-summary"),
    ]
    for event, marker, kind in checks:
        if _is_installed(settings, event, marker):
            console.print(f"[bold green]✓[/bold green]  {event} hook  [dim]({kind}) installed[/dim]")
        else:
            console.print(f"[dim]✗  {event} hook  ({kind}) not installed[/dim]")

    console.print(f"\n[dim]Settings file: {path}[/dim]")
