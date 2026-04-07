from __future__ import annotations

import importlib.metadata
from pathlib import Path

import rich_click as click
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
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
            "commands": ["search", "sessions", "session", "stats", "delete", "ui"],
        },
        {
            "name": "Integration",
            "commands": ["setup", "hooks", "mcp"],
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
            "options": [
                "--source", "--project", "--role", "--session",
                "--since", "--before", "--min-score", "--current-project",
                "--category",
            ],
        },
        {
            "name": "Output",
            "options": ["--limit", "--context", "--json", "--agent", "--snippet", "--dedupe"],
        },
        {
            "name": "Advanced",
            "options": ["--db", "--help"],
        },
    ],
    "memory-bank sessions": [
        {
            "name": "Filters",
            "options": ["--source", "--project", "--since", "--before"],
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

ROLE_STYLES = {
    "user": "bold blue",
    "assistant": "bold green",
    "system": "bold yellow",
}


def _get_version() -> str:
    try:
        return importlib.metadata.version("memory-bank")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------


@click.group(context_settings=CONTEXT_SETTINGS, invoke_without_command=True)
@click.version_option(None, "--version", "-V", package_name="memory-bank", prog_name="memory-bank")
@click.pass_context
def cli(ctx):
    """[bold magenta]memory-bank[/bold magenta] — your local semantic memory for Claude chat histories.

    Ingest conversations from Claude Code or Claude Desktop into a local vector DB,
    then search them semantically — no cloud, no API calls, fully offline.
    """
    if ctx.invoked_subcommand is None:
        banner = Text.assemble(
            ("memory-bank", "bold magenta"),
            (f"  v{_get_version()}\n", "dim"),
            ("Search and ingest Claude chat histories into a local vector DB.", "italic"),
        )
        console.print(Panel(banner, border_style="magenta", padding=(0, 2)))
        console.print()
        click.echo(ctx.get_help())


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


PENDING_DIR = Path.home() / ".memory-bank" / "pending"


def _write_pending_marker(source: str) -> None:
    """Write a marker so the next successful ingest drains this source."""
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    (PENDING_DIR / source).touch()


def _drain_pending_markers(db_path: Path | None = None) -> None:
    """Re-run ingest for any sources that were queued by a previous lock collision."""
    if not PENDING_DIR.exists():
        return
    markers = list(PENDING_DIR.iterdir())
    if not markers:
        return

    from .ingestors.claude_code import ClaudeCodeIngestor

    # Only auto-detectable sources can be drained (others require a path argument)
    factories = {
        "claude-code": ClaudeCodeIngestor,
    }

    for marker in markers:
        source = marker.name
        factory = factories.get(source)
        if factory is None:
            console.print(f"[dim]Skipping pending marker for unknown source: {source}[/dim]")
            marker.unlink(missing_ok=True)
            continue
        console.print(f"[dim]Draining pending ingest for {source}…[/dim]")
        # Run ingest with drain=False to prevent recursion
        _run_ingest(factory(), db_path=db_path, _drain=False)
        # Only remove marker after successful ingest
        marker.unlink(missing_ok=True)


def _run_ingest(ingestor, db_path: Path | None = None, _drain: bool = True):
    from .db import DatabaseLockedError
    from .router import resolve_router
    from .schema import IngestResult

    source = ingestor.source_name
    result = IngestResult(source=source)

    errors = ingestor.validate()
    if errors:
        for e in errors:
            console.print(f"[bold red]Error:[/bold red] {e}")
        return result

    router = resolve_router(db_path=db_path)
    if type(router).__name__ == "HttpRouter":
        route_label = "via UI server"
    elif getattr(getattr(router, "_db", None), "_url", None):
        route_label = "server (Docker)"
    else:
        route_label = "embedded"
    console.print(f"[dim]Ingest mode: {route_label}[/dim]")

    from .categorizer import categorize

    console.print(
        f"[dim]Scanning [cyan]{source}[/cyan] — "
        "first run downloads the embedding model (~25 MB)[/dim]"
    )

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold magenta]{task.description}[/bold magenta]"),
            TextColumn("[dim]·[/dim]"),
            TextColumn("{task.completed:>6} messages"),
            TextColumn("[dim]({task.fields[ins]} new, {task.fields[skp]} skipped)[/dim]"),
            TimeElapsedColumn(),
            console=console,
            transient=False,
        ) as progress:
            task = progress.add_task(
                f"Ingesting [cyan]{source}[/cyan]",
                total=None,
                ins=0,
                skp=0,
            )
            batch: list = []
            for msg in ingestor.iter_messages():
                result.total_found += 1
                if msg.role == "assistant" and "category" not in msg.metadata:
                    cat = categorize(msg.content)
                    if cat:
                        msg.metadata["category"] = cat
                batch.append(msg)
                progress.advance(task)
                if len(batch) >= BATCH_SIZE:
                    ins, skp = router.upsert(batch)
                    result.inserted += ins
                    result.skipped += skp
                    batch = []
                    progress.update(task, ins=result.inserted, skp=result.skipped)

            if batch:
                ins, skp = router.upsert(batch)
                result.inserted += ins
                result.skipped += skp
                progress.update(task, ins=result.inserted, skp=result.skipped)
    except DatabaseLockedError:
        _write_pending_marker(source)
        console.print(
            f"[yellow]DB is locked. Ingest for {source} queued — "
            f"will run on next invocation.[/yellow]"
        )
        return result

    router.close()

    console.print(
        f"[bold green]✓[/bold green] [cyan]{source}[/cyan]: "
        f"found [bold]{result.total_found}[/bold] messages, "
        f"[cyan]{result.inserted}[/cyan] inserted, "
        f"[dim]{result.skipped} already existed[/dim]"
    )

    if _drain:
        _drain_pending_markers(db_path=db_path)

    return result


# ---------------------------------------------------------------------------
# Register command groups
# ---------------------------------------------------------------------------

from memory_bank.commands import ingest, search, manage, hooks, mcp, setup  # noqa: E402, F401
from memory_bank.ui import server  # noqa: E402, F401
