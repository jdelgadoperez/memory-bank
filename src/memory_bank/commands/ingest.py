from __future__ import annotations

from pathlib import Path

import rich_click as click

from memory_bank.cli import CONTEXT_SETTINGS, console, _run_ingest, cli


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
    from memory_bank.ingestors.claude_code import ClaudeCodeIngestor

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
    from memory_bank.ingestors.claude_desktop import ClaudeDesktopIngestor

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
    from memory_bank.ingestors.claude_code import ClaudeCodeIngestor
    from memory_bank.ingestors.claude_desktop import ClaudeDesktopIngestor

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
