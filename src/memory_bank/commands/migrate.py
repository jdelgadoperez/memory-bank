from __future__ import annotations

import warnings
from pathlib import Path

import rich_click as click

from memory_bank.cli import CONTEXT_SETTINGS, cli, console

_LOCK_HINT = (
    "Stop the UI server ('memory-bank ui stop') and quit Claude Code / "
    "Claude Desktop so the hooks and MCP server release it, then retry."
)


def _open_embedded(path: Path):
    """Open the embedded store, turning lock and size warnings into clean output."""
    from qdrant_client import QdrantClient

    path.mkdir(parents=True, exist_ok=True)
    with warnings.catch_warnings():
        # Embedded mode warns above 20k points; irrelevant for a one-off copy.
        warnings.filterwarnings("ignore", message=".*Local mode is not recommended.*")
        try:
            return QdrantClient(path=str(path))
        except RuntimeError as exc:
            if "already accessed by another instance" in str(exc):
                raise click.ClickException(
                    f"The embedded store at {path} is in use by another process.\n{_LOCK_HINT}"
                ) from exc
            raise


def _open_server(url: str, db_path: Path, *, autostart: bool):
    """Connect to the Qdrant server at *url*, starting the Docker container if allowed."""
    from qdrant_client import QdrantClient

    from memory_bank.db import (
        QDRANT_DOCKER_URL,
        _docker_daemon_running,
        _ensure_qdrant_container,
        _ping_qdrant,
    )

    if not _ping_qdrant(url):
        if autostart and url == QDRANT_DOCKER_URL and _docker_daemon_running():
            console.print("[dim]→ Starting Qdrant via Docker…[/dim]")
            if not _ensure_qdrant_container(db_path):
                raise click.ClickException("The Qdrant container failed to start.")
        else:
            raise click.ClickException(
                f"No Qdrant server is reachable at {url}.\n"
                "Start Docker (memory-bank starts the container for you), or pass --url "
                "/ set QDRANT_URL to a running server."
            )
    return QdrantClient(url=url, timeout=60)


def _count(client) -> int:
    from memory_bank.db import COLLECTION

    if not client.collection_exists(COLLECTION):
        return 0
    return client.count(collection_name=COLLECTION, exact=True).count


@cli.command(context_settings=CONTEXT_SETTINGS)
@click.option(
    "--to",
    "target",
    type=click.Choice(["server", "embedded"]),
    required=True,
    help="Which mode to copy your data [bold]into[/bold]. The other mode is the source.",
)
@click.option(
    "--db",
    type=click.Path(),
    default=None,
    envvar="MEMORY_BANK_DB",
    metavar="DIR",
    help="Embedded store path. Env: [dim]MEMORY_BANK_DB[/dim].",
)
@click.option(
    "--url",
    default=None,
    envvar="QDRANT_URL",
    metavar="URL",
    help="Qdrant server URL. Env: [dim]QDRANT_URL[/dim]. Default: http://localhost:6333.",
)
@click.option(
    "--batch-size",
    type=click.IntRange(1, 10_000),
    default=256,
    show_default=True,
    help="Points copied per request.",
)
@click.option(
    "--pause",
    type=click.FloatRange(0, 60),
    default=0.0,
    metavar="SECONDS",
    help="Sleep between batches to throttle the copy, e.g. 0.1. Default: no pause.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be copied without writing anything.",
)
def migrate(target, db, url, batch_size, pause, dry_run):
    """Copy your memory bank between embedded and server (Docker) Qdrant.

    The two modes share ~/.memory-bank/qdrant but store data in different
    formats, so switching modes does not carry your history across. This copies
    every point, with its stored vector and payload: nothing is re-embedded and
    soft-deleted points stay soft-deleted.

    It [bold]merges[/bold] into the destination: points are keyed by message ID,
    so a message already there is overwritten with the source copy and
    re-running is safe. Nothing is deleted from the source.

    [bold]Resource use:[/bold] --to server streams the embedded store a batch at
    a time and pauses the server's indexing until the upload finishes, so memory
    stays flat. Afterwards Qdrant indexes once in the background, which can keep
    CPU busy for a while. --to embedded holds the whole destination in memory,
    as embedded mode always does, so it suits smaller collections. Use --pause
    to slow either direction down.

    \b
    Examples:
      memory-bank migrate --to server --dry-run
      memory-bank migrate --to server
      memory-bank migrate --to embedded
    """
    from contextlib import ExitStack

    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        TextColumn,
        TimeRemainingColumn,
    )

    from memory_bank.db import (
        QDRANT_DOCKER_URL,
        DatabaseLockedError,
        EmbeddedReader,
        copy_points,
        get_db_path,
        iter_client_batches,
    )

    db_path = Path(db).expanduser() if db else get_db_path()
    server_url = url or QDRANT_DOCKER_URL

    with ExitStack() as stack:
        # Open the source first so a missing/locked source fails before touching the target.
        if target == "server":
            try:
                reader = stack.enter_context(EmbeddedReader(db_path))
            except DatabaseLockedError as exc:
                raise click.ClickException(f"{exc}\n{_LOCK_HINT}") from exc
            dst = _open_server(server_url, db_path, autostart=True)
            stack.callback(dst.close)
            src_count = reader.count()
            batches = reader.batches(batch_size)
            src_label, dst_label = f"embedded ({db_path})", f"server ({server_url})"
        else:
            src = _open_server(server_url, db_path, autostart=False)
            stack.callback(src.close)
            dst = _open_embedded(db_path)
            stack.callback(dst.close)
            src_count = _count(src)
            batches = iter_client_batches(src, batch_size)
            src_label, dst_label = f"server ({server_url})", f"embedded ({db_path})"

        dst_before = _count(dst)
        console.print(f"[bold]From[/bold]  {src_label}: [cyan]{src_count}[/cyan] points")
        console.print(f"[bold]To[/bold]    {dst_label}: [cyan]{dst_before}[/cyan] points")

        if src_count == 0:
            console.print("[yellow]Nothing to migrate: the source is empty.[/yellow]")
            return
        if dry_run:
            console.print(
                f"[dim]Dry run: would copy {src_count} points (merging by message ID). "
                "Nothing was written.[/dim]"
            )
            return

        with Progress(
            TextColumn("[bold]Copying"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeRemainingColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("copy", total=src_count)
            copied = copy_points(
                batches,
                dst,
                dst_is_server=(target == "server"),
                on_batch=lambda n: progress.advance(task, n),
                pause=pause,
            )

        dst_after = _count(dst)

    console.print(
        f"[green]✓[/green] Copied {copied} points. Destination now has "
        f"[bold cyan]{dst_after}[/bold cyan] (was {dst_before})."
    )
    if dst_after < copied:
        raise click.ClickException(
            f"Destination has fewer points ({dst_after}) than were copied ({copied})."
        )

    if target == "server":
        console.print(
            "[dim]Qdrant is now building its search index in the background; CPU "
            "may stay busy for a while. Search works meanwhile.[/dim]"
        )
        console.print(
            "[dim]Restart the UI server and Claude Code / Claude Desktop so they "
            "reconnect in server mode.[/dim]"
        )
    else:
        console.print(
            "[dim]memory-bank keeps using the server while one is reachable. To run "
            "embedded, stop the container and quit Docker (see README → Storage modes).[/dim]"
        )
