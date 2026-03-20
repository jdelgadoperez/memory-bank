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
    "--since",
    default=None,
    metavar="EXPR",
    help=(
        "Only return results after this time. "
        "Accepts relative ([dim]7d[/dim], [dim]2w[/dim], [dim]1m[/dim]) "
        "or absolute ([dim]2025-01-01[/dim]) expressions."
    ),
)
@click.option(
    "--before",
    default=None,
    metavar="EXPR",
    help="Only return results before this time. Same format as [dim]--since[/dim].",
)
@click.option(
    "--context",
    "context_n",
    default=0,
    type=int,
    metavar="N",
    help=(
        "Include N messages of context before/after each hit from the same session. "
        "Helps understand whether a result is a solution or a dead-end."
    ),
)
@click.option(
    "--current-project",
    is_flag=True,
    help=(
        "Auto-scope to the current git repo name. "
        "Equivalent to [dim]--project $(basename $(git rev-parse --show-toplevel))[/dim]. "
        "Ignored if [dim]--project[/dim] is already set."
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
    "--json", "as_json",
    is_flag=True,
    help="Emit raw JSON — useful for piping into other tools or agent scripts.",
)
@click.option(
    "--agent",
    is_flag=True,
    help=(
        "Compact JSON for LLM consumption. "
        "Drops the id field, shortens timestamps to dates, truncates content, "
        "and defaults to limit=5 / min-score=0.5. "
        "Overrides --json."
    ),
)
@click.option(
    "--min-score",
    default=0.0,
    show_default=False,
    metavar="FLOAT",
    help="Discard results below this similarity score (0–1). Default: 0 (no filter). "
         "Recommended: 0.5 in agent contexts to avoid low-quality hits.",
)
@click.option(
    "--snippet",
    default=None,
    type=int,
    metavar="N",
    help="Truncate content to N characters in JSON / agent output. "
         "Default: 300 in --agent mode, no truncation otherwise.",
)
@click.option(
    "--dedupe",
    is_flag=True,
    help=(
        "Collapse near-duplicate results. "
        "When the same message appears in multiple sessions (e.g. repeated code blocks), "
        "keeps only the highest-scoring copy."
    ),
)
def search(
    query, limit, source, project, role, session, since, before, context_n,
    current_project, db, as_json, agent, min_score, snippet, dedupe,
):
    """Semantically search your ingested chat history.

    Uses vector similarity to find messages that [italic]mean[/italic] what you're looking for,
    not just messages that contain the exact words. Filters can be combined freely.

    \b
    Examples:
      memory-bank search "docker networking fix"
      memory-bank search "auth bug" -s claude-code -r assistant -n 5
      memory-bank search "deployment" --since 7d --before 2d
      memory-bank search "kubernetes" --current-project --context 3
      memory-bank search "deployment" -p my-project --json | jq '.[0].content'
    """
    import json as _json

    from .db import MemoryDB, parse_time_expr

    # Resolve --current-project
    if current_project and not project:
        try:
            import subprocess
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, check=True,
            )
            project = Path(result.stdout.strip()).name
        except Exception:
            console.print("[yellow]Warning:[/yellow] --current-project: not in a git repo, ignoring.")

    # Parse time expressions
    since_iso = parse_time_expr(since) if since else None
    before_iso = parse_time_expr(before) if before else None

    # --agent mode: apply token-frugal defaults unless the caller overrode them
    if agent:
        if limit == 10:   # user didn't explicitly pass --limit
            limit = 5
        if min_score == 0.0:
            min_score = 0.5
        if snippet is None:
            snippet = 300

    db_obj = MemoryDB(Path(db) if db else None)
    results = db_obj.search(
        query=query,
        limit=limit,
        source=source,
        project=project,
        role=role,
        session_id=session,
        since=since_iso,
        before=before_iso,
    )

    # Apply score filter
    if min_score > 0.0:
        results = [r for r in results if r.get("score", 0) >= min_score]

    # Deduplicate: keep highest-scoring result per content fingerprint
    if dedupe:
        seen: dict[str, float] = {}
        deduped = []
        for r in results:
            fp = r.get("content", "")[:120]
            score = r.get("score", 0.0)
            if fp not in seen or score > seen[fp]:
                seen[fp] = score
                deduped.append(r)
        # Re-sort by score (order may have changed)
        results = sorted(deduped, key=lambda x: x.get("score", 0), reverse=True)

    if not results:
        if agent or as_json:
            click.echo(_json.dumps([]))
        else:
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

    # Attach context if requested
    if context_n > 0:
        for r in results:
            sid = r.get("session_id", "")
            ts = r.get("timestamp", "")
            if sid:
                r["_context"] = db_obj.get_context(sid, ts, context_n)

    if agent:
        def _compact(r: dict) -> dict:
            content = r.get("content", "")
            if snippet and len(content) > snippet:
                content = content[:snippet] + "…"
            out: dict = {
                "score": round(r["score"], 2),
                "role": r.get("role", ""),
                "src": r.get("source", ""),
                "date": (r.get("timestamp") or "")[:10],  # YYYY-MM-DD only
                "text": content,
            }
            if r.get("project"):
                out["proj"] = r["project"]
            if r.get("session_id"):
                out["sid"] = r["session_id"]
            if r.get("_context"):
                out["context"] = [
                    {
                        "role": c.get("role", ""),
                        "date": (c.get("timestamp") or "")[:10],
                        "text": (c.get("content", "")[:snippet] + "…")
                        if snippet and len(c.get("content", "")) > snippet
                        else c.get("content", ""),
                    }
                    for c in r["_context"]
                ]
            return out

        click.echo(_json.dumps([_compact(r) for r in results]))
        return

    if as_json:
        if snippet:
            for r in results:
                if len(r.get("content", "")) > snippet:
                    r["content"] = r["content"][:snippet] + "…"
        # Remove internal key before output
        for r in results:
            r.pop("_context", None)
        click.echo(_json.dumps(results, indent=2))
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
        score_str = f"{r['score']:.3f}"
        role_str = r.get("role", "?")
        role_styled = Text(role_str, style=ROLE_STYLES.get(role_str, "bold"))
        src = r.get("source", "")
        proj = r.get("project", "")
        src_proj = f"{src}/{proj}" if proj else src
        ts = r.get("timestamp", "")[:19].replace("T", " ")
        content = r.get("content", "")
        if len(content) > 400:
            content = content[:397] + "…"
        table.add_row(score_str, role_styled, src_proj, ts, content)

        # Show context messages inline (dimmed, no score)
        for ctx in r.get("_context", []):
            ctx_role = ctx.get("role", "?")
            ctx_content = ctx.get("content", "")
            if len(ctx_content) > 300:
                ctx_content = ctx_content[:297] + "…"
            ctx_ts = ctx.get("timestamp", "")[:19].replace("T", " ")
            table.add_row(
                "[dim]ctx[/dim]",
                Text(ctx_role, style="dim " + ROLE_STYLES.get(ctx_role, "bold")),
                "[dim]—[/dim]",
                f"[dim]{ctx_ts}[/dim]",
                f"[dim]{ctx_content}[/dim]",
            )

    console.print(table)
    console.print(f"[dim]{len(results)} result(s)[/dim]")


# ---------------------------------------------------------------------------
# sessions command
# ---------------------------------------------------------------------------


@cli.command(context_settings=CONTEXT_SETTINGS)
@click.option(
    "--source", "-s",
    default=None,
    metavar="NAME",
    help="Filter by source (e.g. [dim]claude-code[/dim]).",
)
@click.option(
    "--project", "-p",
    default=None,
    metavar="NAME",
    help="Filter by project name.",
)
@click.option(
    "--since",
    default=None,
    metavar="EXPR",
    help="Only show sessions with activity after this time ([dim]7d[/dim], [dim]2025-01-01[/dim], …).",
)
@click.option(
    "--before",
    default=None,
    metavar="EXPR",
    help="Only show sessions with activity before this time.",
)
@click.option(
    "--limit", "-n",
    default=None,
    type=int,
    metavar="N",
    help="Maximum number of sessions to return (newest first).",
)
@click.option(
    "--json", "as_json",
    is_flag=True,
    help="Emit raw JSON.",
)
@click.option(
    "--db",
    type=click.Path(),
    default=None,
    envvar="MEMORY_BANK_DB",
    metavar="DIR",
    help="Override the Qdrant DB storage path. Env: [dim]MEMORY_BANK_DB[/dim].",
)
def sessions(source, project, since, before, limit, as_json, db):
    """List indexed sessions with metadata.

    Shows session IDs, project, source, date range, and message count.
    Useful for discovering what's indexed before drilling into a session.

    \b
    Examples:
      memory-bank sessions
      memory-bank sessions --project my-app --since 7d
      memory-bank sessions --source claude-code -n 20 --json
    """
    import json as _json

    from .db import MemoryDB, parse_time_expr
    from rich.table import Table

    since_iso = parse_time_expr(since) if since else None
    before_iso = parse_time_expr(before) if before else None

    db_obj = MemoryDB(Path(db) if db else None)
    result = db_obj.list_sessions(
        source=source,
        project=project,
        since=since_iso,
        before=before_iso,
        limit=limit,
    )

    if not result:
        if as_json:
            click.echo(_json.dumps([]))
        else:
            console.print("[yellow]No sessions found.[/yellow]")
        return

    if as_json:
        click.echo(_json.dumps(result, indent=2))
        return

    table = Table(
        title="[bold magenta]Sessions[/bold magenta]",
        show_lines=True,
        expand=True,
        border_style="magenta",
        header_style="bold magenta",
    )
    table.add_column("Session ID", style="cyan", width=20, no_wrap=True)
    table.add_column("Source", style="dim", width=14, no_wrap=True)
    table.add_column("Project", width=18, no_wrap=True)
    table.add_column("Last Active", style="dim", width=20, no_wrap=True)
    table.add_column("Msgs", justify="right", width=6)

    for s in result:
        sid = s["session_id"]
        sid_short = sid[:16] + "…" if len(sid) > 16 else sid
        last_ts = s["last_ts"][:19].replace("T", " ")
        table.add_row(
            sid_short,
            s.get("source", ""),
            s.get("project", "") or "[dim]—[/dim]",
            last_ts,
            str(s["message_count"]),
        )

    console.print(table)
    console.print(f"[dim]{len(result)} session(s)[/dim]")


# ---------------------------------------------------------------------------
# session command (replay)
# ---------------------------------------------------------------------------


@cli.command("session", context_settings=CONTEXT_SETTINGS)
@click.argument("session_id")
@click.option(
    "--json", "as_json",
    is_flag=True,
    help="Emit raw JSON — one object per message, in chronological order.",
)
@click.option(
    "--db",
    type=click.Path(),
    default=None,
    envvar="MEMORY_BANK_DB",
    metavar="DIR",
    help="Override the Qdrant DB storage path. Env: [dim]MEMORY_BANK_DB[/dim].",
)
def session_replay(session_id, as_json, db):
    """Replay a full session in chronological order.

    Prints every message from SESSION_ID sorted by timestamp.
    Use 'memory-bank sessions' to find session IDs.

    \b
    Examples:
      memory-bank session abc123def456
      memory-bank session abc123def456 --json | jq '.[].content'
    """
    import json as _json

    from .db import MemoryDB
    from rich.rule import Rule

    db_obj = MemoryDB(Path(db) if db else None)
    messages = db_obj.get_session(session_id)

    if not messages:
        console.print(f"[yellow]No messages found for session:[/yellow] {session_id}")
        return

    if as_json:
        click.echo(_json.dumps(messages, indent=2))
        return

    # Rich pretty-print
    proj = messages[0].get("project", "")
    src = messages[0].get("source", "")
    header = f"[bold magenta]Session:[/bold magenta] [cyan]{session_id[:32]}[/cyan]"
    if proj:
        header += f"  [dim]project:[/dim] {proj}"
    if src:
        header += f"  [dim]source:[/dim] {src}"
    console.print(header)
    console.print(f"[dim]{len(messages)} messages[/dim]\n")

    for msg in messages:
        role = msg.get("role", "?")
        ts = msg.get("timestamp", "")[:19].replace("T", " ")
        content = msg.get("content", "")
        style = ROLE_STYLES.get(role, "bold")
        console.print(Rule(f"[{style}]{role}[/{style}]  [dim]{ts}[/dim]", style="dim"))
        console.print(content)
        console.print()


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
    from .db import MemoryDB, parse_time_expr

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


# ---------------------------------------------------------------------------
# ui command
# ---------------------------------------------------------------------------


@cli.group(context_settings=CONTEXT_SETTINGS, invoke_without_command=True)
@click.option(
    "--port", "-p",
    default=6333,
    show_default=True,
    metavar="PORT",
    help="Local port for the web UI.",
)
@click.option(
    "--no-browser", "-B",
    is_flag=True,
    help="Start the server but don't open a browser tab.",
)
@click.option(
    "--db",
    type=click.Path(),
    default=None,
    envvar="MEMORY_BANK_DB",
    metavar="DIR",
    help="Override the Qdrant DB storage path. Env: [dim]MEMORY_BANK_DB[/dim].",
)
@click.pass_context
def ui(ctx, port, no_browser, db):
    """Launch a web UI to browse and search your memory bank.

    Run with no subcommand for a foreground server, or use start / stop / status
    to manage a background server.

    \b
    Examples:
      memory-bank ui                    # foreground
      memory-bank ui start              # background daemon
      memory-bank ui stop               # stop background server
      memory-bank ui status             # check if running
      memory-bank ui --port 8080        # foreground on custom port
      memory-bank ui start -p 8080      # background on custom port
    """
    ctx.ensure_object(dict)
    ctx.obj["port"] = port
    ctx.obj["no_browser"] = no_browser
    ctx.obj["db"] = db

    if ctx.invoked_subcommand is not None:
        return
    import json
    import threading
    import time
    import webbrowser
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs, urlparse

    from .db import MemoryDB, get_db_path

    db_path = Path(db).expanduser() if db else get_db_path()
    memory_db = MemoryDB(path=db_path)

    # ------------------------------------------------------------------
    # HTML template (single-page app, no external deps)
    # ------------------------------------------------------------------
    HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Memory Bank</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🧠</text></svg>">
<style>
  :root{--bg:#0f1117;--surface:#1a1d27;--border:#2a2d3a;--accent:#7c6af7;--accent2:#a78bfa;--text:#e2e8f0;--muted:#64748b;--user:#3b82f6;--assistant:#10b981;--gap:1rem}
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--text);font:14px/1.6 system-ui,sans-serif;min-height:100vh;display:flex;flex-direction:column}
  header{background:var(--surface);border-bottom:1px solid var(--border);padding:.75rem var(--gap);display:flex;align-items:center;gap:.75rem}
  header h1{font-size:1.1rem;font-weight:700;color:var(--accent2)}
  header span{color:var(--muted);font-size:.8rem}
  #stats-bar{display:flex;gap:1.5rem;margin-left:auto;font-size:.8rem;color:var(--muted)}
  #stats-bar b{color:var(--text)}
  main{display:flex;flex:1;gap:0;overflow:hidden}
  aside{width:220px;flex-shrink:0;background:var(--surface);border-right:1px solid var(--border);padding:var(--gap);display:flex;flex-direction:column;gap:.5rem}
  aside h2{font-size:.7rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:.25rem}
  .filter-group{display:flex;flex-direction:column;gap:.35rem}
  select,input{background:#0f1117;border:1px solid var(--border);color:var(--text);border-radius:6px;padding:.4rem .6rem;font-size:.82rem;width:100%}
  select:focus,input:focus{outline:none;border-color:var(--accent)}
  #content{flex:1;display:flex;flex-direction:column;overflow:hidden}
  #search-bar{padding:var(--gap);display:flex;gap:.5rem;border-bottom:1px solid var(--border)}
  #search-bar input{flex:1;font-size:.95rem;padding:.5rem .75rem}
  button{background:var(--accent);color:#fff;border:none;border-radius:6px;padding:.5rem 1.1rem;font-size:.85rem;cursor:pointer;white-space:nowrap}
  button:hover{background:var(--accent2)}
  button:disabled{opacity:.4;cursor:default}
  #results{flex:1;overflow-y:auto;padding:var(--gap);display:flex;flex-direction:column;gap:.75rem}
  .card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:1rem;transition:border-color .15s}
  .card:hover{border-color:var(--accent)}
  .card-meta{display:flex;gap:.75rem;align-items:center;margin-bottom:.5rem;flex-wrap:wrap}
  .badge{font-size:.7rem;padding:.15rem .5rem;border-radius:999px;font-weight:600}
  .role-user{background:#1e3a5f;color:var(--user)}
  .role-assistant{background:#064e3b;color:var(--assistant)}
  .source-badge{background:#1e1b4b;color:var(--accent2)}
  .score{margin-left:auto;font-size:.75rem;color:var(--muted)}
  .project{color:var(--muted);font-size:.75rem}
  .ts{color:var(--muted);font-size:.72rem}
  .card-content{white-space:pre-wrap;word-break:break-word;font-size:.85rem;line-height:1.65;max-height:300px;overflow-y:auto;color:#cbd5e1}
  .card-content.expanded{max-height:none}
  .expand-btn{background:none;border:none;color:var(--accent);font-size:.75rem;padding:.2rem 0;cursor:pointer;margin-top:.4rem}
  #empty{text-align:center;color:var(--muted);padding:3rem;display:none}
  #loading{text-align:center;color:var(--muted);padding:3rem;display:none}
  .err{color:#f87171;font-size:.82rem;padding:.5rem var(--gap)}
</style>
</head>
<body>
<header>
  <h1>&#x1F9E0; Memory Bank</h1>
  <span id="db-path"></span>
  <div id="stats-bar">
    <span>Messages: <b id="stat-total">…</b></span>
    <span id="stat-sources"></span>
  </div>
</header>
<main>
  <aside>
    <h2>Filters</h2>
    <div class="filter-group">
      <label style="font-size:.75rem;color:var(--muted)">Source</label>
      <select id="f-source"><option value="">All sources</option></select>
    </div>
    <div class="filter-group">
      <label style="font-size:.75rem;color:var(--muted)">Role</label>
      <select id="f-role">
        <option value="">Both</option>
        <option value="user">User</option>
        <option value="assistant">Assistant</option>
      </select>
    </div>
    <div class="filter-group">
      <label style="font-size:.75rem;color:var(--muted)">Project</label>
      <input id="f-project" placeholder="any project…">
    </div>
    <div class="filter-group">
      <label style="font-size:.75rem;color:var(--muted)">Limit</label>
      <select id="f-limit">
        <option value="10">10</option>
        <option value="25" selected>25</option>
        <option value="50">50</option>
        <option value="100">100</option>
      </select>
    </div>
  </aside>
  <div id="content">
    <div id="search-bar">
      <input id="q" placeholder="Search your chat history…" autofocus>
      <button id="search-btn" onclick="doSearch()">Search</button>
    </div>
    <div class="err" id="err-msg"></div>
    <div id="loading">Searching…</div>
    <div id="empty">No results. Try a different query or adjust the filters.</div>
    <div id="results"></div>
  </div>
</main>
<script>
async function loadStats(){
  try{
    const d=await fetch('/api/stats').then(r=>r.json());
    document.getElementById('stat-total').textContent=d.total_messages.toLocaleString();
    document.getElementById('db-path').textContent=d.db_path;
    const sources=Object.keys(d.by_source||{});
    const sel=document.getElementById('f-source');
    sources.forEach(s=>{const o=document.createElement('option');o.value=s;o.textContent=s+' ('+d.by_source[s]+')';sel.appendChild(o);});
    const bar=sources.map(s=>`<span>${s}: <b>${d.by_source[s]}</b></span>`).join(' &nbsp;·&nbsp; ');
    document.getElementById('stat-sources').innerHTML=bar;
  }catch(e){console.error(e)}
}

async function doSearch(){
  const q=document.getElementById('q').value.trim();
  if(!q)return;
  const btn=document.getElementById('search-btn');
  btn.disabled=true;
  document.getElementById('loading').style.display='block';
  document.getElementById('results').innerHTML='';
  document.getElementById('empty').style.display='none';
  document.getElementById('err-msg').textContent='';
  const params=new URLSearchParams({q,
    limit:document.getElementById('f-limit').value,
    source:document.getElementById('f-source').value,
    role:document.getElementById('f-role').value,
    project:document.getElementById('f-project').value,
  });
  try{
    const data=await fetch('/api/search?'+params).then(r=>r.json());
    document.getElementById('loading').style.display='none';
    btn.disabled=false;
    if(!data.length){document.getElementById('empty').style.display='block';return;}
    const div=document.getElementById('results');
    data.forEach(r=>{
      const ts=r.timestamp?new Date(r.timestamp*1000).toLocaleString():'';
      const score=r.score!=null?`<span class="score">score ${r.score.toFixed(3)}</span>`:'';
      const proj=r.project?`<span class="project">📁 ${r.project}</span>`:'';
      const card=document.createElement('div');card.className='card';
      card.innerHTML=`
        <div class="card-meta">
          <span class="badge role-${r.role}">${r.role}</span>
          <span class="badge source-badge">${r.source||''}</span>
          ${proj}
          <span class="ts">${ts}</span>
          ${score}
        </div>
        <div class="card-content" id="cc-${Math.random().toString(36).slice(2)}">${escHtml(r.content||'')}</div>
      `;
      const cc=card.querySelector('.card-content');
      if(cc.scrollHeight>310){
        const btn2=document.createElement('button');
        btn2.className='expand-btn';btn2.textContent='Show more';
        btn2.onclick=()=>{cc.classList.toggle('expanded');btn2.textContent=cc.classList.contains('expanded')?'Show less':'Show more';};
        card.appendChild(btn2);
      }
      div.appendChild(card);
    });
  }catch(e){
    document.getElementById('loading').style.display='none';
    btn.disabled=false;
    document.getElementById('err-msg').textContent='Error: '+e.message;
  }
}

function escHtml(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

document.getElementById('q').addEventListener('keydown',e=>{if(e.key==='Enter')doSearch();});
loadStats();
</script>
</body>
</html>"""

    # ------------------------------------------------------------------
    # Request handler
    # ------------------------------------------------------------------
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # silence default access log
            pass

        def send_json(self, data, status=200):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path

            if path in ("/", "/ui"):
                body = HTML.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            elif path == "/api/stats":
                self.send_json(memory_db.stats())

            elif path == "/api/search":
                qs = parse_qs(parsed.query)
                q = qs.get("q", [""])[0].strip()
                if not q:
                    self.send_json({"error": "missing query"}, 400)
                    return
                limit = int(qs.get("limit", ["25"])[0])
                source = qs.get("source", [""])[0] or None
                role = qs.get("role", [""])[0] or None
                project = qs.get("project", [""])[0] or None
                results = memory_db.search(
                    q, limit=limit, source=source, role=role, project=project
                )
                self.send_json(results)

            else:
                self.send_response(404)
                self.end_headers()

    # ------------------------------------------------------------------
    # Start server
    # ------------------------------------------------------------------
    server = HTTPServer(("127.0.0.1", port), Handler)
    url = _ui_url(port)
    console.print(
        f"[bold magenta]Memory Bank UI[/bold magenta]  [cyan]{url}[/cyan]"
    )
    console.print(f"[dim]DB: {db_path}[/dim]")
    console.print("[dim]Press Ctrl+C to stop.[/dim]\n")

    if not no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/dim]")
        server.shutdown()


# ---------------------------------------------------------------------------
# ui background helpers & subcommands
# ---------------------------------------------------------------------------

_UI_PID_FILE = Path.home() / ".memory-bank" / "ui.pid"
_UI_LOG_FILE = Path.home() / ".memory-bank" / "ui.log"
_LOCAL_DOMAIN = "memory.local"


def _ui_url(port: int) -> str:
    """Return the best URL for the UI, preferring memory.local over localhost."""
    import socket

    try:
        socket.getaddrinfo(_LOCAL_DOMAIN, port, socket.AF_INET)
        return f"http://{_LOCAL_DOMAIN}"
    except socket.gaierror:
        return f"http://localhost:{port}"


def _read_ui_pid():
    """Read PID file, return (pid, port) or None."""
    import json

    try:
        data = json.loads(_UI_PID_FILE.read_text())
        return data["pid"], data["port"]
    except (json.JSONDecodeError, KeyError, OSError):
        return None


def _is_pid_alive(pid: int) -> bool:
    """Check whether a process with the given PID is still running."""
    import os

    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


@ui.command("start", context_settings=CONTEXT_SETTINGS)
@click.pass_context
def ui_start(ctx):
    """Start the UI server in the background.

    Spawns a detached process and writes its PID to
    [dim]~/.memory-bank/ui.pid[/dim]. Logs go to [dim]~/.memory-bank/ui.log[/dim].

    \b
    Examples:
      memory-bank ui start
      memory-bank ui start -p 8080
    """
    import json
    import shutil
    import subprocess

    port = ctx.obj["port"]
    db = ctx.obj["db"]

    existing = _read_ui_pid()
    if existing:
        pid, old_port = existing
        if _is_pid_alive(pid):
            console.print(
                f"[yellow]UI is already running[/yellow] (PID {pid}, port {old_port}).\n"
                f"[dim]Run [cyan]memory-bank ui stop[/cyan] first.[/dim]"
            )
            return

    mb_bin = shutil.which("memory-bank")
    if not mb_bin:
        console.print("[bold red]Error:[/bold red] memory-bank not found on PATH.")
        return

    cmd = [mb_bin, "ui", "--no-browser", "-p", str(port)]
    if db:
        cmd.extend(["--db", db])

    _UI_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    log_fh = open(_UI_LOG_FILE, "a")

    proc = subprocess.Popen(
        cmd,
        stdout=log_fh,
        stderr=log_fh,
        start_new_session=True,
    )

    _UI_PID_FILE.write_text(json.dumps({"pid": proc.pid, "port": port}) + "\n")

    url = _ui_url(port)
    console.print(
        f"[bold green]Started[/bold green] UI server in background "
        f"(PID [cyan]{proc.pid}[/cyan], [cyan]{url}[/cyan])"
    )
    console.print(f"[dim]Log: {_UI_LOG_FILE}[/dim]")
    console.print(f"[dim]Stop with: [cyan]memory-bank ui stop[/cyan][/dim]")

    if not ctx.obj["no_browser"]:
        import webbrowser
        webbrowser.open(url)


@ui.command("stop", context_settings=CONTEXT_SETTINGS)
def ui_stop():
    """Stop a background UI server."""
    import os
    import signal

    existing = _read_ui_pid()
    if not existing:
        console.print("[yellow]No background UI server found.[/yellow]")
        return

    pid, port = existing
    if not _is_pid_alive(pid):
        console.print(f"[yellow]PID {pid} is not running (stale pid file).[/yellow]")
        _UI_PID_FILE.unlink(missing_ok=True)
        return

    os.kill(pid, signal.SIGTERM)
    _UI_PID_FILE.unlink(missing_ok=True)
    console.print(
        f"[bold green]Stopped[/bold green] UI server (PID {pid}, port {port})."
    )


@ui.command("restart", context_settings=CONTEXT_SETTINGS)
@click.pass_context
def ui_restart(ctx):
    """Restart the background UI server."""
    ctx.invoke(ui_stop)
    ctx.invoke(ui_start)


@ui.command("status", context_settings=CONTEXT_SETTINGS)
def ui_status():
    """Check whether a background UI server is running."""
    existing = _read_ui_pid()
    if not existing:
        console.print("[dim]No background UI server configured.[/dim]")
        return

    pid, port = existing
    if _is_pid_alive(pid):
        console.print(
            f"[bold green]Running[/bold green]  PID [cyan]{pid}[/cyan]  "
            f"Port [cyan]{port}[/cyan]  [dim]{_ui_url(port)}[/dim]"
        )
    else:
        console.print(f"[yellow]Not running[/yellow] (stale pid file, PID {pid}).")
        _UI_PID_FILE.unlink(missing_ok=True)


@ui.command("dev", context_settings=CONTEXT_SETTINGS)
@click.pass_context
def ui_dev(ctx):
    """Run the UI with auto-reload on source changes.

    Watches the memory_bank source directory and restarts the background
    server whenever a Python file changes. Press Ctrl+C to stop.

    \b
    Requires the dev extras:
      uv pip install -e '.[dev]'
    """
    try:
        from watchfiles import watch
    except ImportError:
        console.print(
            "[bold red]Error:[/bold red] watchfiles is not installed.\n"
            "[dim]Install dev extras: [cyan]uv pip install -e '.[dev]'[/cyan][/dim]"
        )
        return

    src_dir = Path(__file__).resolve().parent
    console.print(
        f"[bold blue]Watching[/bold blue] [cyan]{src_dir}[/cyan] for changes\u2026"
    )
    console.print("[dim]Press Ctrl+C to stop.[/dim]\n")

    # Suppress browser opens during dev — restarts should be silent
    ctx.obj["no_browser"] = True
    ctx.invoke(ui_stop)
    ctx.invoke(ui_start)

    try:
        for changes in watch(src_dir, watch_filter=lambda _, path: path.endswith(".py")):
            changed_files = [str(Path(p).name) for _, p in changes]
            console.print(
                f"\n[yellow]Changed:[/yellow] {', '.join(changed_files)}"
            )
            ctx.invoke(ui_stop)
            ctx.invoke(ui_start)
    except KeyboardInterrupt:
        console.print("\n[dim]Dev mode stopped.[/dim]")


# ---------------------------------------------------------------------------
# hooks command group
# ---------------------------------------------------------------------------

_SETTINGS_PATH = Path("~/.claude/settings.json").expanduser()

# The command that the Stop hook runs — ingest in background so session ends fast.
_STOP_HOOK_COMMAND = (
    "memory-bank ingest claude-code"
    " >> ~/.memory-bank/ingest.log 2>&1 &"
)

# The SessionStart context-summary hook: search for relevant past work based on the
# current project and write a brief summary to ~/.memory-bank/context.md.
_START_CONTEXT_COMMAND = (
    "memory-bank hooks context-summary"
    " >> ~/.memory-bank/ingest.log 2>&1 &"
)

# Sentinels used to detect already-installed hooks.
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
    related to the current project and writes a brief summary to
    [dim]~/.memory-bank/context.md[/dim].  Add that path to your CLAUDE.md to
    give Claude automatic memory.

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
                "[bold]~/.memory-bank/context.md[/bold].\n"
                "Add this to your CLAUDE.md to surface it automatically:\n"
                "  [cyan]{{read_file ~/.memory-bank/context.md}}[/cyan][/dim]"
            )
    else:
        console.print("[dim]Nothing changed.[/dim]")


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
    a Markdown summary to ~/.memory-bank/context.md.
    """
    import subprocess
    from .db import MemoryDB

    db_obj = MemoryDB(Path(db) if db else None)

    # Detect current project from git
    project = None
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        project = Path(r.stdout.strip()).name
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
            lines.append(f"**[{role}]** {date}  |  project: {proj}  |  session: `{sid[:16]}`")
            lines.append(f"> {snippet}\n")

    out_path.write_text("\n".join(lines))
    console.print(f"[dim]Context summary written to {out_path}[/dim]")


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


# ---------------------------------------------------------------------------
# mcp command
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
def mcp(db):
    """Start the Memory Bank MCP server (stdio transport).

    Exposes [bold cyan]search_memory[/bold cyan], [bold cyan]get_session[/bold cyan], and
    [bold cyan]list_sessions[/bold cyan] as native MCP tools so Claude can call them
    directly — no SKILL.md or shell-out required.

    \b
    Configure in Claude Desktop's claude_desktop_config.json:
      {
        "mcpServers": {
          "memory-bank": {
            "command": "memory-bank",
            "args": ["mcp"]
          }
        }
      }

    \b
    Or with Claude Code via settings.json mcpServers section.
    """
    try:
        from .mcp_server import run_mcp_server
    except ImportError as e:
        console.print(
            f"[bold red]Error:[/bold red] MCP server requires the 'mcp' package.\n"
            f"Install it with: [cyan]pip install 'mcp>=1.0'[/cyan]\n\nDetails: {e}"
        )
        raise SystemExit(1)

    from .db import MemoryDB

    db_obj = MemoryDB(Path(db) if db else None)
    run_mcp_server(db_obj)


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
