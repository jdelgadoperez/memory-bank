from __future__ import annotations

from pathlib import Path

import rich_click as click

from memory_bank.cli import CONTEXT_SETTINGS, console, cli


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
    from rich.panel import Panel
    from rich.table import Table

    from memory_bank.db import DatabaseLockedError, MemoryDB

    db_obj = MemoryDB(Path(db) if db else None)
    try:
        s = db_obj.stats()
    except DatabaseLockedError as exc:
        raise click.ClickException(str(exc)) from exc

    mode_label = (
        f"[green]server[/green] [dim]({db_obj._url})[/dim]"
        if db_obj._url
        else "[dim]embedded[/dim]"
    )

    info = Table.grid(padding=(0, 2))
    info.add_column(style="dim")
    info.add_column()
    info.add_row("DB path", str(s["db_path"]))
    info.add_row("Collection", s["collection"])
    info.add_row("Qdrant mode", mode_label)
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


@cli.command(context_settings=CONTEXT_SETTINGS)
@click.argument("source", required=False, default=None)
@click.option(
    "--since",
    default=None,
    metavar="EXPR",
    help=(
        "Delete messages older than this time instead of a whole source. "
        "Accepts [dim]7d[/dim], [dim]30d[/dim], [dim]2025-01-01[/dim], etc. "
        "Can be combined with SOURCE to scope the prune."
    ),
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
    "--yes", "-y",
    is_flag=True,
    help="Skip the confirmation prompt.",
)
def delete(source, since, db, yes):
    """Delete ingested messages by source and/or age.

    SOURCE (optional) must match the source name exactly (e.g. claude-code).
    Use [dim]--since[/dim] to prune old data without wiping a whole source.
    Either SOURCE or [dim]--since[/dim] (or both) must be provided.

    Use 'memory-bank stats' to see available source names.

    \b
    Examples:
      memory-bank delete claude-desktop
      memory-bank delete --since 30d
      memory-bank delete claude-code --since 90d
    """
    from memory_bank.db import DatabaseLockedError, MemoryDB, parse_time_expr

    if not source and not since:
        raise click.UsageError("Provide SOURCE, --since, or both.")

    if since:
        since_iso = parse_time_expr(since)
        desc = f"messages older than {since}"
        if source:
            desc += f" from source '{source}'"
        prompt = f"Delete {desc}?"
    else:
        desc = f"all messages from source '{source}'"
        prompt = f"Delete {desc}?"

    if not yes:
        click.confirm(prompt, abort=True)

    db_obj = MemoryDB(Path(db) if db else None)

    try:
        if since:
            n = db_obj.delete_before(since_iso, source=source)
            console.print(
                f"[bold green]Deleted[/bold green] [cyan]{n}[/cyan] messages "
                f"older than [bold]{since}[/bold]"
                + (f" from source '[bold]{source}[/bold]'" if source else "")
                + "."
            )
        else:
            n = db_obj.delete_by_source(source)
            console.print(
                f"[bold green]Deleted[/bold green] [cyan]{n}[/cyan] messages "
                f"from source '[bold]{source}[/bold]'."
            )
    except DatabaseLockedError as exc:
        raise click.ClickException(str(exc)) from exc
