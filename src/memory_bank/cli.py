"""CLI entry point: memory-bank <command>"""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()
BATCH_SIZE = 256
CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------


@click.group(context_settings=CONTEXT_SETTINGS, invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """memory-bank — search and ingest Claude chat histories into a local vector DB."""
    if ctx.invoked_subcommand is None:
        banner = Text.assemble(
            ("memory-bank", "bold magenta"),
            ("  v0.1.0\n", "dim"),
            ("Search and ingest Claude chat histories into a local vector DB.", "italic"),
        )
        console.print(Panel(banner, border_style="magenta", padding=(0, 2)))
        console.print()
        console.print(click.format_help(ctx.info_name, ctx))


# ---------------------------------------------------------------------------
# ingest group
# ---------------------------------------------------------------------------


@cli.group(context_settings=CONTEXT_SETTINGS)
def ingest():
    """Ingest chat history from a supported source."""


@ingest.command("claude-code", context_settings=CONTEXT_SETTINGS)
@click.option(
    "--path",
    "-p",
    type=click.Path(),
    default=None,
    help="Path to ~/.claude/projects (default: auto-detect)",
)
@click.option(
    "--db",
    type=click.Path(),
    default=None,
    envvar="MEMORY_BANK_DB",
    help="Override Qdrant DB path",
)
def ingest_claude_code(path, db):
    """Ingest all Claude Code sessions from ~/.claude/projects/."""
    from .ingestors.claude_code import ClaudeCodeIngestor

    ingestor = ClaudeCodeIngestor(claude_dir=Path(path) if path else None)
    _run_ingest(ingestor, db_path=Path(db) if db else None)


@ingest.command("claude-desktop", context_settings=CONTEXT_SETTINGS)
@click.option(
    "--path",
    "-p",
    type=click.Path(),
    required=True,
    help="Path to exported conversations JSON file or directory",
)
@click.option(
    "--db",
    type=click.Path(),
    default=None,
    envvar="MEMORY_BANK_DB",
    help="Override Qdrant DB path",
)
def ingest_claude_desktop(path, db):
    """Ingest Claude Desktop conversations from an exported JSON file."""
    from .ingestors.claude_desktop import ClaudeDesktopIngestor

    ingestor = ClaudeDesktopIngestor(path=Path(path))
    _run_ingest(ingestor, db_path=Path(db) if db else None)


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


@ingest.command("all", context_settings=CONTEXT_SETTINGS)
@click.option(
    "--db",
    type=click.Path(),
    default=None,
    envvar="MEMORY_BANK_DB",
    help="Override Qdrant DB path",
)
def ingest_all(db):
    """Ingest from all auto-detectable sources (Claude Code + Claude Desktop if found)."""
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
            "(not found — run 'ingest claude-desktop --path ...' manually)[/yellow]"
        )

    for ingestor in ingestors:
        _run_ingest(ingestor, db_path=db_path)


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
@click.option("--limit", "-n", default=10, show_default=True, help="Number of results")
@click.option(
    "--source", "-s", default=None, help="Filter by source (claude-code, claude-desktop, ...)"
)
@click.option("--project", "-p", default=None, help="Filter by project name")
@click.option(
    "--role",
    "-r",
    default=None,
    type=click.Choice(["user", "assistant"]),
    help="Filter by message role",
)
@click.option("--session", default=None, help="Filter by session ID")
@click.option(
    "--db",
    type=click.Path(),
    default=None,
    envvar="MEMORY_BANK_DB",
    help="Override Qdrant DB path",
)
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON (for agent use)")
def search(query, limit, source, project, role, session, db, as_json):
    """Semantic search over ingested chat history."""
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
    help="Override Qdrant DB path",
)
def stats(db):
    """Show DB statistics."""
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

    console.print(Panel(info, title="[bold magenta]Memory Bank Stats[/bold magenta]", border_style="magenta", padding=(0, 1)))

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
    help="Override Qdrant DB path",
)
@click.confirmation_option(prompt="Are you sure you want to delete all messages from this source?")
def delete(source, db):
    """Delete all messages from a given source."""
    from .db import MemoryDB

    db_obj = MemoryDB(Path(db) if db else None)
    n = db_obj.delete_by_source(source)
    console.print(f"[bold green]Deleted[/bold green] [cyan]{n}[/cyan] messages from source '[bold]{source}[/bold]'.")


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
