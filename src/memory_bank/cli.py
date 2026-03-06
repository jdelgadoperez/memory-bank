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
        console.print(ctx.get_help())


# ---------------------------------------------------------------------------
# ingest group
# ---------------------------------------------------------------------------


@cli.group(context_settings=CONTEXT_SETTINGS)
def ingest():
    """Ingest chat history from Claude Code, Claude Desktop, or a custom source.

    [bold]Quick start:[/bold]

      [cyan]memory-bank ingest claude-code[/cyan]              # auto-detects ~/.claude/projects
      [cyan]memory-bank ingest claude-desktop -p export.json[/cyan]
      [cyan]memory-bank ingest all[/cyan]                      # all auto-detectable sources
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

    [bold]Examples:[/bold]

      [cyan]memory-bank ingest claude-code[/cyan]
      [cyan]memory-bank ingest claude-code -p ~/work/.claude/projects[/cyan]
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

    [bold]Examples:[/bold]

      [cyan]memory-bank ingest claude-desktop -p ~/Downloads/claude_export.json[/cyan]
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

    [bold]Examples:[/bold]

      [cyan]memory-bank search "docker networking fix"[/cyan]
      [cyan]memory-bank search "auth bug" -s claude-code -r assistant -n 5[/cyan]
      [cyan]memory-bank search "deployment" -p my-project --json | jq '.[0].content'[/cyan]
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

    [bold]SOURCE[/bold] must match the source name exactly (e.g. [dim]claude-code[/dim]).
    Use [cyan]memory-bank stats[/cyan] to see available source names.

    [bold]Example:[/bold]

      [cyan]memory-bank delete claude-desktop[/cyan]
    """
    from .db import MemoryDB

    db_obj = MemoryDB(Path(db) if db else None)
    n = db_obj.delete_by_source(source)
    console.print(
        f"[bold green]Deleted[/bold green] [cyan]{n}[/cyan] messages "
        f"from source '[bold]{source}[/bold]'."
    )


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
