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
            "commands": ["search", "sessions", "session", "stats", "delete", "ui"],
        },
        {
            "name": "Hooks",
            "commands": ["hooks"],
        },
        {
            "name": "Integrations",
            "commands": ["mcp"],
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


# ---------------------------------------------------------------------------
# Register command groups
# ---------------------------------------------------------------------------

from memory_bank.commands import ingest, search, manage, hooks, mcp  # noqa: E402, F401
from memory_bank.ui import server  # noqa: E402, F401
