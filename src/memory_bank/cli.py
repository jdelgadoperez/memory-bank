"""CLI entry point: memory-bank <command>"""

from __future__ import annotations

from pathlib import Path

import rich_click as click
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

# ---------------------------------------------------------------------------
# rich-click appearance
# ---------------------------------------------------------------------------

click.rich_click.USE_RICH_MARKUP = True
click.rich_click.SHOW_ARGUMENTS = True
click.rich_click.GROUP_ARGUMENTS_OPTIONS = False
click.rich_click.STYLE_OPTION = "bold cyan"
click.rich_click.STYLE_SWITCH = "bold cyan"
click.rich_click.STYLE_METAVAR = "dim"
click.rich_click.STYLE_HELPTEXT = ""
click.rich_click.STYLE_ERRORS_SUGGESTION = "italic dim"
click.rich_click.MAX_WIDTH = 100
click.rich_click.COLOR_SYSTEM = "auto"

click.rich_click.COMMAND_GROUPS = {
    "memory-bank": [
        {
            "name": "Ingestion",
            "commands": ["ingest"],
        },
        {
            "name": "Query & Manage",
            "commands": ["search", "stats", "delete"],
        },
        {
            "name": "Hooks",
            "commands": ["hooks"],
        },
    ],
    "memory-bank ingest": [
        {
            "name": "Sources",
            "commands": ["claude-code", "claude-desktop", "all", "custom"],
        }
    ],
}

click.rich_click.OPTION_GROUPS = {
    "memory-bank search": [
        {
            "name": "Filters",
            "options": ["--source", "--project", "--role", "--session"],
        },
        {
            "name": "Output",
            "options": ["--limit", "--json"],
        },
        {
            "name": "Advanced",
            "options": ["--db", "--help"],
        },
    ],
}

# ---------------------------------------------------------------------------

console = Console()
BATCH_SIZE = 256
CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------


@click.group(context_settings=CONTEXT_SETTINGS, invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """[bold magenta]memory-bank[/bold magenta] — your local semantic memory for Claude chat histories.

    Ingest conversations from Claude Code or Claude Desktop into a local vector DB,
    then search them semantically — no cloud, no API calls, fully offline.
    """
    if ctx.invoked_subcommand is None:
        banner = Text.assemble(
            ("memory-bank", "bold magenta"),
            ("  v0.1.0\n", "dim"),
            ("Search and ingest Claude chat histories into a local vector DB.", "italic"),
        )
        console.print(Panel(banner, border_style="magenta", padding=(0, 2)))
        console.print()
        click.echo(ctx.get_help())


# ---------------------------------------------------------------------------
# ingest group
# ---------------------------------------------------------------------------


@cli.group(context_settings=CONTEXT_SETTINGS)
def ingest():
    """Ingest chat history from Claude Code, Claude Desktop, or a custom source.

    \b
    Quick start:
      memory-bank ingest claude-code              # auto-detects ~/.claude/projects
      memory-bank ingest claude-desktop -p export.json
      memory-bank ingest all                      # all auto-detectable sources
    """


@ingest.command("claude-code", context_settings=CONTEXT_SETTINGS)
@click.option(
    "--path",
    "-p",
    type=click.Path(),
    default=None,
    metavar="DIR",
    help="Path to your Claude projects dir. Defaults to [dim]~/.claude/projects[/dim].",
)
@click.option(
    "--db",
    type=click.Path(),
    default=None,
    envvar="MEMORY_BANK_DB",
    metavar="DIR",
    help="Override the Qdrant DB storage path. Env: [dim]MEMORY_BANK_DB[/dim].",
)
def ingest_claude_code(path, db):
    """Ingest all Claude Code sessions from [dim]~/.claude/projects/[/dim].

    Reads every [dim].jsonl[/dim] conversation file, embeds each message locally using
    [cyan]BAAI/bge-small-en-v1.5[/cyan], and stores them in the vector DB.
    Re-running is safe — duplicate messages are skipped automatically.

    \b
    Examples:
      memory-bank ingest claude-code
      memory-bank ingest claude-code -p ~/work/.claude/projects
    """
    from .ingestors.claude_code import ClaudeCodeIngestor

    ingestor = ClaudeCodeIngestor(claude_dir=Path(path) if path else None)
    _run_ingest(ingestor, db_path=Path(db) if db else None)


@ingest.command("claude-desktop", context_settings=CONTEXT_SETTINGS)
@click.option(
    "--path",
    "-p",
    type=click.Path(),
    required=True,
    metavar="FILE",
    help="Path to your exported Claude Desktop conversations JSON file.",
)
@click.option(
    "--db",
    type=click.Path(),
    default=None,
    envvar="MEMORY_BANK_DB",
    metavar="DIR",
    help="Override the Qdrant DB storage path. Env: [dim]MEMORY_BANK_DB[/dim].",
)
def ingest_claude_desktop(path, db):
    """Ingest conversations exported from the Claude Desktop app.

    Export your history from Claude Desktop ([italic]Settings → Export[/italic]), then
    point this command at the resulting JSON file or directory.

    \b
    Examples:
      memory-bank ingest claude-desktop -p ~/Downloads/claude_export.json
    """
    from .ingestors.claude_desktop import ClaudeDesktopIngestor

    ingestor = ClaudeDesktopIngestor(path=Path(path))
    _run_ingest(ingestor, db_path=Path(db) if db else None)


@ingest.command("all", context_settings=CONTEXT_SETTINGS)
@click.option(
    "--db",
    type=click.Path(),
    default=None,
    envvar="MEMORY_BANK_DB",
    metavar="DIR",
    help="Override the Qdrant DB storage path. Env: [dim]MEMORY_BANK_DB[/dim].",
)
def ingest_all(db):
    """Ingest from all auto-detectable sources at once.

    Runs [cyan]claude-code[/cyan] automatically. Also runs [cyan]claude-desktop[/cyan] if its
    default path is found — otherwise prints a skip notice.
    """
    from .ingestors.claude_code import ClaudeCodeIngestor
    from .ingestors.claude_desktop import ClaudeDesktopIngestor

    db_path = Path(db) if db else None
    ingestors = [ClaudeCodeIngestor()]
    desktop_ingestor = ClaudeDesktopIngestor()
    if not desktop_ingestor.validate():
        ingestors.append(desktop_ingestor)
    else:
        console.print(
            "[yellow]Skipping Claude Desktop "
            "(not found — run 'ingest claude-desktop -p ...' manually)[/yellow]"
        )

    for ingestor in ingestors:
        _run_ingest(ingestor, db_path=db_path)


@ingest.command("custom", context_settings=CONTEXT_SETTINGS)
def ingest_custom():
    """Show how to ingest a custom data source via the Python API."""
    console.print("""
[bold]Custom data source ingestion[/bold]

There is no CLI flag for custom sources — use the Python API directly:

[bold cyan]1. Define a mapper function[/bold cyan]

    from memory_bank.ingestors.custom import CustomIngestor, SourceRecord

    def my_mapper(record: dict) -> SourceRecord | None:
        return SourceRecord(
            session_id=record["thread_id"],
            role="user" if record["from_me"] else "assistant",
            content=record["text"],
            timestamp=record["date"],
            project=record.get("channel", ""),
            metadata={"platform": "slack"},
        )

[bold cyan]2. Run the ingestor[/bold cyan]

    from memory_bank.db import MemoryDB

    ingestor = CustomIngestor(
        source_name="slack",
        file_path="slack_export.json",
        mapper=my_mapper,
    )

    db = MemoryDB()
    for msg in ingestor.iter_messages():
        db.upsert([msg])

[bold cyan]3. Search as usual[/bold cyan]

    memory-bank search "your query" --source slack

[dim]See CLAUDE.md § "Adding a custom data source" for full details.[/dim]
""")


# ---------------------------------------------------------------------------
# search command
# ---------------------------------------------------------------------------

ROLE_STYLES = {
    "user": "bold blue",
    "assistant": "bold green",
    "system": "bold yellow",
}


@cli.command(context_settings=CONTEXT_SETTINGS)
@click.argument("query")
@click.option(
    "--limit", "-n",
    default=10,
    show_default=True,
    metavar="N",
    help="Maximum number of results to return.",
)
@click.option(
    "--source", "-s",
    default=None,
    metavar="NAME",
    help="Only return results from this source (e.g. [dim]claude-code[/dim], [dim]claude-desktop[/dim]).",
)
@click.option(
    "--project", "-p",
    default=None,
    metavar="NAME",
    help="Only return results from this project name.",
)
@click.option(
    "--role", "-r",
    default=None,
    type=click.Choice(["user", "assistant"]),
    help="Only return messages from this role.",
)
@click.option(
    "--session",
    default=None,
    metavar="ID",
    help="Only return results from a specific session ID.",
)
@click.option(
    "--db",
    type=click.Path(),
    default=None,
    envvar="MEMORY_BANK_DB",
    metavar="DIR",
    help="Override the Qdrant DB storage path. Env: [dim]MEMORY_BANK_DB[/dim].",
)
@click.option(
    "--json", "as_json",
    is_flag=True,
    help="Emit raw JSON — useful for piping into other tools or agent scripts.",
)
def search(query, limit, source, project, role, session, db, as_json):
    """Semantically search your ingested chat history.

    Uses vector similarity to find messages that [italic]mean[/italic] what you're looking for,
    not just messages that contain the exact words. Filters can be combined freely.

    \b
    Examples:
      memory-bank search "docker networking fix"
      memory-bank search "auth bug" -s claude-code -r assistant -n 5
      memory-bank search "deployment" -p my-project --json | jq '.[0].content'
    """
    from .db import MemoryDB

    db_obj = MemoryDB(Path(db) if db else None)
    results = db_obj.search(
        query=query,
        limit=limit,
        source=source,
        project=project,
        role=role,
        session_id=session,
    )

    if not results:
        console.print(
            Panel(
                "[yellow]No results found.[/yellow]\n"
                "[dim]Try a different query or broaden your filters.[/dim]",
                border_style="yellow",
                title="[yellow]Search[/yellow]",
                padding=(0, 2),
            )
        )
        return

    if as_json:
        import json

        click.echo(json.dumps(results, indent=2))
        return

    from rich.table import Table

    table = Table(
        title=f'[bold magenta]Search:[/bold magenta] [italic]"{query}"[/italic]',
        show_lines=True,
        expand=True,
        border_style="magenta",
        header_style="bold magenta",
    )
    table.add_column("Score", style="cyan", width=7, no_wrap=True)
    table.add_column("Role", width=11, no_wrap=True)
    table.add_column("Source / Project", style="dim", width=24, no_wrap=True)
    table.add_column("Timestamp", style="dim", width=20, no_wrap=True)
    table.add_column("Content", ratio=1)

    for r in results:
        score = f"{r['score']:.3f}"
        role_str = r.get("role", "?")
        role_styled = Text(role_str, style=ROLE_STYLES.get(role_str, "bold"))
        src = r.get("source", "")
        proj = r.get("project", "")
        src_proj = f"{src}/{proj}" if proj else src
        ts = r.get("timestamp", "")[:19].replace("T", " ")
        content = r.get("content", "")
        if len(content) > 400:
            content = content[:397] + "…"
        table.add_row(score, role_styled, src_proj, ts, content)

    console.print(table)
    console.print(f"[dim]{len(results)} result(s)[/dim]")


# ---------------------------------------------------------------------------
# stats command
# ---------------------------------------------------------------------------


@cli.command(context_settings=CONTEXT_SETTINGS)
@click.option(
    "--db",
    type=click.Path(),
    default=None,
    envvar="MEMORY_BANK_DB",
    metavar="DIR",
    help="Override the Qdrant DB storage path. Env: [dim]MEMORY_BANK_DB[/dim].",
)
def stats(db):
    """Show a summary of what's in your memory bank.

    Displays total message count, breakdown by source, and DB configuration.
    """
    from rich.table import Table

    from .db import MemoryDB

    db_obj = MemoryDB(Path(db) if db else None)
    s = db_obj.stats()

    info = Table.grid(padding=(0, 2))
    info.add_column(style="dim")
    info.add_column()
    info.add_row("DB path", str(s["db_path"]))
    info.add_row("Collection", s["collection"])
    info.add_row("Embedding model", s["embedding_model"])
    info.add_row("Total messages", f"[bold cyan]{s['total_messages']}[/bold cyan]")

    console.print(
        Panel(
            info,
            title="[bold magenta]Memory Bank Stats[/bold magenta]",
            border_style="magenta",
            padding=(0, 1),
        )
    )

    if s["by_source"]:
        tbl = Table(show_header=True, header_style="bold magenta", border_style="dim", box=None)
        tbl.add_column("Source", style="cyan")
        tbl.add_column("Messages", justify="right", style="bold")
        for src, count in sorted(s["by_source"].items()):
            tbl.add_row(src, str(count))
        console.print(tbl)


# ---------------------------------------------------------------------------
# delete command
# ---------------------------------------------------------------------------


@cli.command(context_settings=CONTEXT_SETTINGS)
@click.argument("source")
@click.option(
    "--db",
    type=click.Path(),
    default=None,
    envvar="MEMORY_BANK_DB",
    metavar="DIR",
    help="Override the Qdrant DB storage path. Env: [dim]MEMORY_BANK_DB[/dim].",
)
@click.confirmation_option(prompt="Are you sure you want to delete all messages from this source?")
def delete(source, db):
    """Delete all ingested messages from a source.

    SOURCE must match the source name exactly (e.g. claude-code).
    Use 'memory-bank stats' to see available source names.

    \b
    Example:
      memory-bank delete claude-desktop
    """
    from .db import MemoryDB

    db_obj = MemoryDB(Path(db) if db else None)
    n = db_obj.delete_by_source(source)
    console.print(
        f"[bold green]Deleted[/bold green] [cyan]{n}[/cyan] messages "
        f"from source '[bold]{source}[/bold]'."
    )


# ---------------------------------------------------------------------------
# hooks command group
# ---------------------------------------------------------------------------

_SETTINGS_PATH = Path("~/.claude/settings.json").expanduser()

# The command that the hook will run.  We background it so Stop completes fast.
_HOOK_COMMAND = (
    "memory-bank ingest claude-code"
    " >> ~/.memory-bank/ingest.log 2>&1 &"
)

# Sentinel used to detect already-installed hooks.
_HOOK_MARKER = "memory-bank ingest claude-code"


def _load_settings() -> dict:
    if _SETTINGS_PATH.exists():
        import json
        return json.loads(_SETTINGS_PATH.read_text())
    return {}


def _save_settings(settings: dict) -> None:
    import json
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_PATH.write_text(json.dumps(settings, indent=2) + "\n")


def _hook_entry(hook_type: str) -> dict:
    return {
        "matcher": "",
        "hooks": [{"type": "command", "command": _HOOK_COMMAND}],
    }


def _is_installed(settings: dict, hook_type: str) -> bool:
    for entry in settings.get("hooks", {}).get(hook_type, []):
        for h in entry.get("hooks", []):
            if _HOOK_MARKER in h.get("command", ""):
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
      memory-bank hooks install           # adds a Stop hook
      memory-bank hooks install --on start  # adds a SessionStart hook instead
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
        "stop  = after each session ends (recommended)\n"
        "start = when a new session begins\n"
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

    Appends an entry to the Stop and/or SessionStart hook list.  Existing
    hooks are preserved.  Re-running is safe — already-installed hooks are
    skipped.

    \b
    Examples:
      memory-bank hooks install
      memory-bank hooks install --on both
      memory-bank hooks install --settings /path/to/settings.json
    """
    path = Path(settings_path).expanduser() if settings_path else _SETTINGS_PATH
    settings = _load_settings() if path == _SETTINGS_PATH else (
        {} if not path.exists() else __import__("json").loads(path.read_text())
    )
    hooks_cfg = settings.setdefault("hooks", {})

    event_map = {
        "stop": ["Stop"],
        "start": ["SessionStart"],
        "both": ["Stop", "SessionStart"],
    }
    events = event_map[trigger]
    installed_any = False

    for event in events:
        if _is_installed(settings, event):
            console.print(f"[yellow]Already installed:[/yellow] {event} hook — skipping.")
            continue
        hooks_cfg.setdefault(event, []).append(_hook_entry(event))
        console.print(f"[bold green]Installed:[/bold green] {event} hook → [dim]{_HOOK_COMMAND}[/dim]")
        installed_any = True

    if installed_any:
        import json
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=2) + "\n")
        console.print(f"[dim]Saved to {path}[/dim]")
    else:
        console.print("[dim]Nothing changed.[/dim]")


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

    for event in list(settings.get("hooks", {}).keys()):
        before = settings["hooks"][event]
        after = [
            entry for entry in before
            if not any(_HOOK_MARKER in h.get("command", "") for h in entry.get("hooks", []))
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

    for event in ("Stop", "SessionStart"):
        if _is_installed(settings, event):
            console.print(f"[bold green]✓[/bold green]  {event} hook  [dim]installed[/dim]")
        else:
            console.print(f"[dim]✗  {event} hook  not installed[/dim]")

    console.print(f"\n[dim]Settings file: {path}[/dim]")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _run_ingest(ingestor, db_path: Path | None = None):
    from .db import MemoryDB
    from .schema import IngestResult

    source = ingestor.source_name
    result = IngestResult(source=source)

    errors = ingestor.validate()
    if errors:
        for e in errors:
            console.print(f"[bold red]Error:[/bold red] {e}")
        return result

    db = MemoryDB(db_path)

    with console.status(f"[bold magenta]Ingesting [cyan]{source}[/cyan]…[/bold magenta]"):
        batch: list = []
        for msg in ingestor.iter_messages():
            result.total_found += 1
            batch.append(msg)
            if len(batch) >= BATCH_SIZE:
                ins, skp = db.upsert(batch)
                result.inserted += ins
                result.skipped += skp
                batch = []

        if batch:
            ins, skp = db.upsert(batch)
            result.inserted += ins
            result.skipped += skp

    console.print(
        f"[bold green]✓[/bold green] [cyan]{source}[/cyan]: "
        f"found [bold]{result.total_found}[/bold] messages, "
        f"[cyan]{result.inserted}[/cyan] inserted, "
        f"[dim]{result.skipped} already existed[/dim]"
    )
    return result
