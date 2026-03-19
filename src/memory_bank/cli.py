"""CLI entry point: memory-bank <command>"""

from __future__ import annotations

import os
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
            "commands": ["search", "stats", "delete", "ui"],
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
    "memory-bank ui": [
        {
            "name": "Background",
            "commands": ["start", "stop", "status"],
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
    from .db import DatabaseLockedError, MemoryDB

    db_obj = MemoryDB(Path(db) if db else None)
    try:
        results = db_obj.search(
            query=query,
            limit=limit,
            source=source,
            project=project,
            role=role,
            session_id=session,
        )
    except DatabaseLockedError:
        _print_lock_error()
        return

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

    from .db import DatabaseLockedError, MemoryDB

    db_obj = MemoryDB(Path(db) if db else None)
    try:
        s = db_obj.stats()
    except DatabaseLockedError:
        _print_lock_error()
        return

    info = Table.grid(padding=(0, 2))
    info.add_column(style="dim")
    info.add_column()
    info.add_row("DB path", str(s["db_path"]))
    info.add_row("Collections", ", ".join(s.get("collections", [])))
    info.add_row("Embedding model", s["embedding_model"])
    info.add_row("Total messages", f"[bold cyan]{s['total_messages']}[/bold cyan]")
    info.add_row("Total sessions", f"[bold cyan]{s.get('total_sessions', 0)}[/bold cyan]")

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
    from .db import DatabaseLockedError, MemoryDB

    db_obj = MemoryDB(Path(db) if db else None)
    try:
        n = db_obj.delete_by_source(source)
    except DatabaseLockedError:
        _print_lock_error()
        return
    console.print(
        f"[bold green]Deleted[/bold green] [cyan]{n}[/cyan] messages "
        f"from source '[bold]{source}[/bold]'."
    )


# ---------------------------------------------------------------------------
# ui command
# ---------------------------------------------------------------------------


_UI_PID_FILE = Path.home() / ".memory-bank" / "ui.pid"
_UI_LOG_FILE = Path.home() / ".memory-bank" / "ui.log"


@cli.group(context_settings=CONTEXT_SETTINGS, invoke_without_command=True)
@click.option(
    "--port", "-p",
    default=6333,
    show_default=True,
    metavar="PORT",
    help="Local port for the web UI.",
)
@click.option(
    "--no-browser",
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

    Run with no subcommand for a foreground server, or use
    [cyan]start[/cyan] / [cyan]stop[/cyan] / [cyan]status[/cyan]
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
    HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Memory Bank</title>
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
  select,input[type="text"],#q{background:#0f1117;border:1px solid var(--border);color:var(--text);border-radius:6px;padding:.4rem .6rem;font-size:.82rem;width:100%}
  select:focus,input:focus{outline:none;border-color:var(--accent)}
  #content{flex:1;display:flex;flex-direction:column;overflow:hidden}
  .tab-bar{display:flex;gap:0;border-bottom:1px solid var(--border);background:var(--surface)}
  .tab-btn{background:none;border:none;border-bottom:2px solid transparent;color:var(--muted);padding:.6rem 1.2rem;font-size:.85rem;cursor:pointer;font-weight:600}
  .tab-btn.active{color:var(--accent2);border-bottom-color:var(--accent)}
  .tab-btn:hover:not(.active){color:var(--text)}
  #search-bar{padding:var(--gap);display:flex;gap:.5rem;border-bottom:1px solid var(--border);display:none}
  #search-bar #q{flex:1;font-size:.95rem;padding:.5rem .75rem}
  button{background:var(--accent);color:#fff;border:none;border-radius:6px;padding:.5rem 1.1rem;font-size:.85rem;cursor:pointer;white-space:nowrap}
  button:hover{background:var(--accent2)}
  button:disabled{opacity:.4;cursor:default}
  #view-area{flex:1;overflow-y:auto;padding:var(--gap);display:flex;flex-direction:column;gap:.75rem}
  #empty{text-align:center;color:var(--muted);padding:3rem;display:none}
  #loading{text-align:center;color:var(--muted);padding:3rem;display:none}
  .err{color:#f87171;font-size:.82rem;padding:.5rem var(--gap)}
  /* Session list table */
  .session-table{width:100%;border-collapse:collapse}
  .session-table th{text-align:left;font-size:.7rem;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);padding:.5rem .75rem;border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--bg);z-index:1;cursor:pointer;user-select:none}
  .session-table th:hover{color:var(--text)}
  .session-table th .sort-arrow{margin-left:.3em;font-size:.6rem;color:var(--accent)}
  .session-table td{padding:.6rem .75rem;border-bottom:1px solid var(--border);font-size:.82rem;vertical-align:top}
  .session-table tr{cursor:pointer}
  .session-table tbody tr:hover{background:var(--surface)}
  .session-table .title-cell{color:#cbd5e1;max-width:400px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .session-table .muted-cell{color:var(--muted);font-size:.75rem;white-space:nowrap}
  /* Detail view */
  .detail-header{padding:var(--gap);border-bottom:1px solid var(--border);display:flex;align-items:center;gap:1rem;flex-wrap:wrap}
  .detail-header .back-btn{background:none;border:1px solid var(--border);color:var(--muted);padding:.3rem .7rem;font-size:.8rem;border-radius:6px}
  .detail-header .back-btn:hover{color:var(--text);border-color:var(--accent)}
  .detail-meta{display:flex;gap:1rem;flex-wrap:wrap;font-size:.78rem;color:var(--muted)}
  .detail-meta b{color:var(--text)}
  .thread{max-width:800px;margin:0 auto;width:100%;display:flex;flex-direction:column;gap:.75rem;padding:var(--gap) 0}
  .msg{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:.75rem 1rem;border-left:3px solid var(--muted);content-visibility:auto}
  .msg.msg-user{border-left-color:var(--user)}
  .msg.msg-assistant{border-left-color:var(--assistant)}
  .msg-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:.4rem}
  .msg-role{font-size:.72rem;font-weight:600;text-transform:uppercase;letter-spacing:.05em}
  .msg-user .msg-role{color:var(--user)}
  .msg-assistant .msg-role{color:var(--assistant)}
  .msg-ts{font-size:.7rem;color:var(--muted)}
  .msg-body{white-space:pre-wrap;word-break:break-word;font-size:.85rem;line-height:1.65;color:#cbd5e1;max-height:400px;overflow:hidden}
  .msg-body.expanded{max-height:none}
  .msg-body pre{background:#0d0f15;border-radius:6px;padding:.6rem;overflow-x:auto;margin:.4rem 0}
  .msg-body code{font-family:ui-monospace,monospace;font-size:.82rem}
  .msg-expand{background:none;border:none;color:var(--accent);font-size:.75rem;padding:.2rem 0;cursor:pointer;margin-top:.3rem}
  /* Search result cards */
  .card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:1rem;transition:border-color .15s}
  .card:hover{border-color:var(--accent)}
  .card-meta{display:flex;gap:.75rem;align-items:center;margin-bottom:.5rem;flex-wrap:wrap}
  .badge{font-size:.7rem;padding:.15rem .5rem;border-radius:999px;font-weight:600}
  .role-user{background:#1e3a5f;color:var(--user)}
  .role-assistant{background:#064e3b;color:var(--assistant)}
  .source-badge{background:#1e1b4b;color:var(--accent2)}
  .score{margin-left:auto;font-size:.75rem;color:var(--muted)}
  .card-content{white-space:pre-wrap;word-break:break-word;font-size:.85rem;line-height:1.65;max-height:300px;overflow-y:auto;color:#cbd5e1}
  .card-content.expanded{max-height:none}
  .expand-btn{background:none;border:none;color:var(--accent);font-size:.75rem;padding:.2rem 0;cursor:pointer;margin-top:.4rem}
  .session-link{background:none;border:none;color:var(--accent);font-size:.72rem;cursor:pointer;padding:0;text-decoration:underline}
</style>
</head>
<body>
<header>
  <h1>&#x1F9E0; Memory Bank</h1>
  <span id="db-path"></span>
  <div id="stats-bar">
    <span>Messages: <b id="stat-total">...</b></span>
    <span>Sessions: <b id="stat-sessions">...</b></span>
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
    <div class="filter-group" id="role-filter" style="display:none">
      <label style="font-size:.75rem;color:var(--muted)">Role</label>
      <select id="f-role">
        <option value="">Both</option>
        <option value="user">User</option>
        <option value="assistant">Assistant</option>
      </select>
    </div>
    <div class="filter-group">
      <label style="font-size:.75rem;color:var(--muted)">Project</label>
      <input type="text" id="f-project" placeholder="any project...">
    </div>
    <div class="filter-group">
      <label style="font-size:.75rem;color:var(--muted)">From</label>
      <input type="date" id="f-date-from" style="width:100%">
    </div>
    <div class="filter-group">
      <label style="font-size:.75rem;color:var(--muted)">To</label>
      <input type="date" id="f-date-to" style="width:100%">
    </div>
    <div class="filter-group">
      <label style="font-size:.75rem;color:var(--muted)">Limit</label>
      <select id="f-limit">
        <option value="25">25</option>
        <option value="50" selected>50</option>
        <option value="100">100</option>
      </select>
    </div>
  </aside>
  <div id="content">
    <div class="tab-bar">
      <button class="tab-btn active" id="tab-sessions" onclick="switchTab('sessions')">Sessions</button>
      <button class="tab-btn" id="tab-search" onclick="switchTab('search')">Search</button>
    </div>
    <div id="search-bar">
      <input type="text" id="q" placeholder="Search your chat history..." autofocus>
      <button id="search-btn" onclick="doSearch()">Search</button>
    </div>
    <div class="err" id="err-msg"></div>
    <div id="loading">Loading...</div>
    <div id="empty"></div>
    <div id="view-area"></div>
  </div>
</main>
<script>
let currentTab='sessions';
let currentDetail=null;
let sessionData=[];
let sortCol='date';
let sortAsc=false;

function escHtml(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function fmtDate(iso){if(!iso)return '';try{return new Date(iso).toLocaleDateString()}catch(e){return iso;}}
function fmtDateTime(iso){if(!iso)return '';try{return new Date(iso).toLocaleString()}catch(e){return iso;}}

async function loadStats(){
  try{
    const d=await fetch('/api/stats').then(r=>r.json());
    document.getElementById('stat-total').textContent=d.total_messages.toLocaleString();
    document.getElementById('stat-sessions').textContent=(d.total_sessions||0).toLocaleString();
    document.getElementById('db-path').textContent=d.db_path;
    const sources=Object.keys(d.by_source||{});
    const sel=document.getElementById('f-source');
    sources.forEach(s=>{const o=document.createElement('option');o.value=s;o.textContent=s+' ('+d.by_source[s]+')';sel.appendChild(o);});
    const bar=sources.map(s=>'<span>'+s+': <b>'+d.by_source[s]+'</b></span>').join(' &middot; ');
    document.getElementById('stat-sources').innerHTML=bar;
  }catch(e){console.error(e)}
}

function switchTab(tab){
  currentTab=tab;
  currentDetail=null;
  document.getElementById('tab-sessions').classList.toggle('active',tab==='sessions');
  document.getElementById('tab-search').classList.toggle('active',tab==='search');
  document.getElementById('search-bar').style.display=tab==='search'?'flex':'none';
  document.getElementById('role-filter').style.display=tab==='search'?'flex':'none';
  document.getElementById('err-msg').textContent='';
  if(tab==='sessions') loadSessions();
  else{ document.getElementById('view-area').innerHTML=''; document.getElementById('empty').style.display='none'; }
}

// --- Sessions list ---
const SORT_KEYS={
  project:s=>(s.project||'').toLowerCase(),
  title:s=>(s.title||'').toLowerCase(),
  date:s=>s.last_timestamp||'',
  messages:s=>s.message_count||0,
  model:s=>(s.model||'').toLowerCase(),
};

function toggleSort(col){
  if(sortCol===col) sortAsc=!sortAsc;
  else{ sortCol=col; sortAsc=col==='project'||col==='title'||col==='model'; }
  renderSessions();
}

async function loadSessions(){
  const area=document.getElementById('view-area');
  area.innerHTML='';
  document.getElementById('loading').style.display='block';
  document.getElementById('empty').style.display='none';
  const params=new URLSearchParams({
    limit:document.getElementById('f-limit').value,
    source:document.getElementById('f-source').value,
    project:document.getElementById('f-project').value,
    date_from:document.getElementById('f-date-from').value,
    date_to:document.getElementById('f-date-to').value,
  });
  try{
    sessionData=await fetch('/api/sessions?'+params).then(r=>r.json());
    document.getElementById('loading').style.display='none';
    if(!sessionData.length){
      document.getElementById('empty').style.display='block';
      document.getElementById('empty').innerHTML='No sessions found.<br><span style="font-size:.82rem">Run <code>memory-bank ingest claude-code</code> to get started.</span>';
      return;
    }
    renderSessions();
  }catch(e){
    document.getElementById('loading').style.display='none';
    document.getElementById('err-msg').textContent='Error: '+e.message;
  }
}

function renderSessions(){
  const area=document.getElementById('view-area');
  area.innerHTML='';
  const keyFn=SORT_KEYS[sortCol]||SORT_KEYS.date;
  const sorted=[...sessionData].sort((a,b)=>{
    const va=keyFn(a),vb=keyFn(b);
    let cmp=va<vb?-1:va>vb?1:0;
    return sortAsc?cmp:-cmp;
  });
  const cols=[
    {key:'project',label:'Project'},
    {key:'title',label:'Title'},
    {key:'date',label:'Date'},
    {key:'messages',label:'Messages'},
    {key:'model',label:'Model'},
  ];
  const table=document.createElement('table');table.className='session-table';
  const hrow=cols.map(c=>{
    const arrow=sortCol===c.key?(sortAsc?'&#9650;':'&#9660;'):'';
    return '<th onclick="toggleSort(\''+c.key+'\')">'+c.label+(arrow?'<span class="sort-arrow">'+arrow+'</span>':'')+'</th>';
  }).join('');
  table.innerHTML='<thead><tr>'+hrow+'</tr></thead>';
  const tbody=document.createElement('tbody');
  sorted.forEach(s=>{
    const tr=document.createElement('tr');
    const dateRange=fmtDate(s.first_timestamp)+(s.first_timestamp!==s.last_timestamp?' - '+fmtDate(s.last_timestamp):'');
    const model=(s.model||'').replace('claude-','').replace('-20250514','');
    tr.innerHTML='<td class="muted-cell">'+escHtml(s.project||'')+'</td>'
      +'<td class="title-cell">'+escHtml(s.title||'(untitled)')+'</td>'
      +'<td class="muted-cell">'+dateRange+'</td>'
      +'<td style="text-align:center">'+s.message_count+'</td>'
      +'<td class="muted-cell">'+escHtml(model)+'</td>';
    tr.onclick=()=>loadDetail(s.session_id,s);
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  area.appendChild(table);
}

// --- Session detail ---
async function loadDetail(sessionId,sessionMeta){
  history.pushState({view:'detail',sessionId},'','#session/'+sessionId);
  currentDetail=sessionId;
  const area=document.getElementById('view-area');
  area.innerHTML='';
  document.getElementById('loading').style.display='block';
  try{
    const data=await fetch('/api/sessions/'+encodeURIComponent(sessionId)).then(r=>r.json());
    document.getElementById('loading').style.display='none';
    if(data.error){document.getElementById('err-msg').textContent=data.error;return;}
    const session=data.session;
    const messages=data.messages;
    // Header
    const hdr=document.createElement('div');hdr.className='detail-header';
    const model=(session.model||'').replace('claude-','').replace('-20250514','');
    hdr.innerHTML='<button class="back-btn" onclick="goBackToSessions()">&larr; Back</button>'
      +'<div class="detail-meta">'
      +'<span>Project: <b>'+escHtml(session.project||'')+'</b></span>'
      +'<span>'+fmtDateTime(session.first_timestamp)+' &mdash; '+fmtDateTime(session.last_timestamp)+'</span>'
      +'<span>'+messages.length+' messages</span>'
      +(model?'<span>Model: <b>'+escHtml(model)+'</b></span>':'')
      +(session.git_branch?'<span>Branch: <b>'+escHtml(session.git_branch)+'</b></span>':'')
      +'</div>';
    area.appendChild(hdr);
    // Thread
    const thread=document.createElement('div');thread.className='thread';
    messages.forEach(m=>{
      const msg=document.createElement('div');
      msg.className='msg msg-'+m.role;
      const ts=fmtDateTime(m.timestamp);
      msg.innerHTML='<div class="msg-header"><span class="msg-role">'+m.role+'</span><span class="msg-ts">'+ts+'</span></div>'
        +'<div class="msg-body">'+escHtml(m.content||'')+'</div>';
      const body=msg.querySelector('.msg-body');
      // defer height check
      setTimeout(()=>{
        if(body.scrollHeight>410){
          const btn=document.createElement('button');btn.className='msg-expand';btn.textContent='Show more';
          btn.onclick=()=>{body.classList.toggle('expanded');btn.textContent=body.classList.contains('expanded')?'Show less':'Show more';};
          msg.appendChild(btn);
        }
      },0);
      thread.appendChild(msg);
    });
    area.appendChild(thread);
  }catch(e){
    document.getElementById('loading').style.display='none';
    document.getElementById('err-msg').textContent='Error: '+e.message;
  }
}

function goBackToSessions(){
  history.pushState({view:'sessions'},'','#');
  currentDetail=null;
  loadSessions();
}

window.addEventListener('popstate',()=>{
  if(currentDetail){currentDetail=null;loadSessions();}
});

// --- Search ---
async function doSearch(){
  const q=document.getElementById('q').value.trim();
  if(!q)return;
  const btn=document.getElementById('search-btn');
  btn.disabled=true;
  document.getElementById('loading').style.display='block';
  document.getElementById('view-area').innerHTML='';
  document.getElementById('empty').style.display='none';
  document.getElementById('err-msg').textContent='';
  const params=new URLSearchParams({q,
    limit:document.getElementById('f-limit').value,
    source:document.getElementById('f-source').value,
    role:document.getElementById('f-role').value,
    project:document.getElementById('f-project').value,
    date_from:document.getElementById('f-date-from').value,
    date_to:document.getElementById('f-date-to').value,
  });
  try{
    const data=await fetch('/api/search?'+params).then(r=>r.json());
    document.getElementById('loading').style.display='none';
    btn.disabled=false;
    if(!data.length){document.getElementById('empty').style.display='block';document.getElementById('empty').textContent='No results. Try a different query.';return;}
    const area=document.getElementById('view-area');
    data.forEach(r=>{
      const ts=fmtDateTime(r.timestamp);
      const score=r.score!=null?'<span class="score">score '+r.score.toFixed(3)+'</span>':'';
      const proj=r.project?'<span style="color:var(--muted);font-size:.75rem">'+escHtml(r.project)+'</span>':'';
      const sessionLink=r.session_id?'<button class="session-link" onclick="event.stopPropagation();loadDetailFromSearch(\''+escHtml(r.session_id)+'\')">View session</button>':'';
      const card=document.createElement('div');card.className='card';
      card.innerHTML='<div class="card-meta">'
        +'<span class="badge role-'+r.role+'">'+r.role+'</span>'
        +'<span class="badge source-badge">'+(r.source||'')+'</span>'
        +proj
        +'<span style="color:var(--muted);font-size:.72rem">'+ts+'</span>'
        +score
        +sessionLink
        +'</div>'
        +'<div class="card-content">'+escHtml(r.content||'')+'</div>';
      const cc=card.querySelector('.card-content');
      if(cc.scrollHeight>310){
        const btn2=document.createElement('button');btn2.className='expand-btn';btn2.textContent='Show more';
        btn2.onclick=()=>{cc.classList.toggle('expanded');btn2.textContent=cc.classList.contains('expanded')?'Show less':'Show more';};
        card.appendChild(btn2);
      }
      area.appendChild(card);
    });
  }catch(e){
    document.getElementById('loading').style.display='none';
    btn.disabled=false;
    document.getElementById('err-msg').textContent='Error: '+e.message;
  }
}

function loadDetailFromSearch(sessionId){
  switchTab('sessions');
  loadDetail(sessionId,{});
}

document.getElementById('q').addEventListener('keydown',e=>{if(e.key==='Enter')doSearch();});

// Re-fetch when any filter changes
function onFilterChange(){
  if(currentTab==='sessions'&&!currentDetail) loadSessions();
  else if(currentTab==='search'&&document.getElementById('q').value.trim()) doSearch();
}
['f-source','f-limit','f-role'].forEach(id=>document.getElementById(id).addEventListener('change',onFilterChange));
['f-date-from','f-date-to'].forEach(id=>document.getElementById(id).addEventListener('change',onFilterChange));
let projectDebounce;
document.getElementById('f-project').addEventListener('input',()=>{clearTimeout(projectDebounce);projectDebounce=setTimeout(onFilterChange,400);});

loadStats().then(()=>loadSessions());
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

            elif path == "/api/sessions":
                qs = parse_qs(parsed.query)
                limit = int(qs.get("limit", ["50"])[0])
                source = qs.get("source", [""])[0] or None
                project = qs.get("project", [""])[0] or None
                date_from = qs.get("date_from", [""])[0] or None
                date_to = qs.get("date_to", [""])[0] or None
                results = memory_db.list_sessions(
                    limit=limit, source=source, project=project,
                    date_from=date_from, date_to=date_to,
                )
                self.send_json(results)

            elif path.startswith("/api/sessions/"):
                session_id = path.split("/")[-1]
                if not session_id:
                    self.send_json({"error": "missing session id"}, 400)
                    return
                session = memory_db.get_session_by_id(session_id)
                if not session:
                    self.send_json({"error": "session not found"}, 404)
                    return
                messages = memory_db.get_session_messages(session_id)
                self.send_json({"session": session, "messages": messages})

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
                date_from = qs.get("date_from", [""])[0] or None
                date_to = qs.get("date_to", [""])[0] or None
                results = memory_db.search(
                    q, limit=limit, source=source, role=role,
                    project=project, date_from=date_from, date_to=date_to,
                )
                self.send_json(results)

            else:
                self.send_json({"error": "not found"}, 404)

    # ------------------------------------------------------------------
    # Start server
    # ------------------------------------------------------------------
    server = HTTPServer(("127.0.0.1", port), Handler)
    url = f"http://localhost:{port}"
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
# ui background subcommands
# ---------------------------------------------------------------------------


def _read_ui_pid() -> tuple[int, int] | None:
    """Read (pid, port) from the PID file, or None if not present."""
    if not _UI_PID_FILE.exists():
        return None
    try:
        import json
        data = json.loads(_UI_PID_FILE.read_text())
        return (data["pid"], data["port"])
    except (json.JSONDecodeError, KeyError, OSError):
        return None


def _is_pid_alive(pid: int) -> bool:
    """Check whether a process with the given PID is still running."""
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

    # Check if already running
    existing = _read_ui_pid()
    if existing:
        pid, old_port = existing
        if _is_pid_alive(pid):
            console.print(
                f"[yellow]UI is already running[/yellow] (PID {pid}, port {old_port}).\n"
                f"[dim]Run [cyan]memory-bank ui stop[/cyan] first.[/dim]"
            )
            return

    # Find the memory-bank executable
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

    url = f"http://localhost:{port}"
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
            f"Port [cyan]{port}[/cyan]  [dim]http://localhost:{port}[/dim]"
        )
    else:
        console.print(f"[yellow]Not running[/yellow] (stale pid file, PID {pid}).")
        _UI_PID_FILE.unlink(missing_ok=True)


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


PENDING_DIR = Path.home() / ".memory-bank" / "pending"


def _print_lock_error() -> None:
    console.print(
        "[bold red]Error:[/bold red] Database is locked by another process.\n"
        "[dim]If the UI server is running, stop it with Ctrl+C, "
        "or use the UI's built-in search.[/dim]"
    )


def _run_ingest(ingestor, db_path: Path | None = None):
    from .db import DatabaseLockedError, MemoryDB
    from .schema import IngestResult, Session

    source = ingestor.source_name
    result = IngestResult(source=source)

    errors = ingestor.validate()
    if errors:
        for e in errors:
            console.print(f"[bold red]Error:[/bold red] {e}")
        return result

    db = MemoryDB(db_path)

    # Accumulate session metadata while iterating messages
    session_acc: dict[str, dict] = {}

    try:
        with console.status(f"[bold magenta]Ingesting [cyan]{source}[/cyan]…[/bold magenta]"):
            batch: list = []
            for msg in ingestor.iter_messages():
                result.total_found += 1
                batch.append(msg)

                # Accumulate session info
                sid = msg.session_id
                if sid not in session_acc:
                    session_acc[sid] = {
                        "source": msg.source,
                        "project": msg.project,
                        "first_timestamp": msg.timestamp,
                        "last_timestamp": msg.timestamp,
                        "message_count": 0,
                        "first_user_message": "",
                        "slug": "",
                        "model": "",
                        "git_branch": "",
                        "cwd": "",
                        "project_path": "",
                    }
                acc = session_acc[sid]
                acc["message_count"] += 1
                if msg.timestamp < acc["first_timestamp"]:
                    acc["first_timestamp"] = msg.timestamp
                if msg.timestamp > acc["last_timestamp"]:
                    acc["last_timestamp"] = msg.timestamp
                if msg.role == "user" and not acc["first_user_message"]:
                    acc["first_user_message"] = msg.content[:500]
                if msg.metadata.get("slug") and not acc["slug"]:
                    acc["slug"] = msg.metadata["slug"]
                if msg.metadata.get("model") and not acc["model"]:
                    acc["model"] = msg.metadata["model"]
                if msg.metadata.get("git_branch") and not acc["git_branch"]:
                    acc["git_branch"] = msg.metadata["git_branch"]
                if msg.metadata.get("cwd") and not acc["cwd"]:
                    acc["cwd"] = msg.metadata["cwd"]

                if len(batch) >= BATCH_SIZE:
                    ins, skp = db.upsert(batch)
                    result.inserted += ins
                    result.skipped += skp
                    batch = []

            if batch:
                ins, skp = db.upsert(batch)
                result.inserted += ins
                result.skipped += skp

            # Build and upsert session records
            sessions = []
            for sid, acc in session_acc.items():
                title = acc["slug"] or acc["first_user_message"][:120] or sid
                summary = acc["first_user_message"] or title
                session = Session(
                    id=Session.make_id(acc["source"], sid),
                    source=acc["source"],
                    session_id=sid,
                    project=acc["project"],
                    title=title,
                    summary=summary,
                    message_count=acc["message_count"],
                    first_timestamp=acc["first_timestamp"],
                    last_timestamp=acc["last_timestamp"],
                    model=acc["model"],
                    metadata={
                        "git_branch": acc["git_branch"],
                        "cwd": acc["cwd"],
                    },
                )
                sessions.append(session)

            if sessions:
                result.sessions_upserted = db.upsert_sessions(sessions)

    except DatabaseLockedError:
        PENDING_DIR.mkdir(parents=True, exist_ok=True)
        (PENDING_DIR / source).touch()
        console.print(
            f"[yellow]DB is locked.[/yellow] Ingest for [cyan]{source}[/cyan] "
            f"queued — will run on next invocation."
        )
        return result
    except Exception as exc:
        import traceback

        console.print(
            f"[bold red]Error during ingest of [cyan]{source}[/cyan]:[/bold red] {exc}"
        )
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        return result

    console.print(
        f"[bold green]\u2713[/bold green] [cyan]{source}[/cyan]: "
        f"found [bold]{result.total_found}[/bold] messages, "
        f"[cyan]{result.inserted}[/cyan] inserted, "
        f"[dim]{result.skipped} already existed[/dim], "
        f"[cyan]{result.sessions_upserted}[/cyan] sessions"
    )

    # Drain any pending ingests from prior lock failures
    _drain_pending(db)

    return result


def _drain_pending(db) -> None:
    """Check for pending ingest markers and run them."""
    if not PENDING_DIR.exists():
        return
    markers = list(PENDING_DIR.iterdir())
    if not markers:
        return

    for marker in markers:
        pending_source = marker.name
        console.print(
            f"[dim]Draining pending ingest for [cyan]{pending_source}[/cyan]…[/dim]"
        )
        marker.unlink()

        # Re-run ingest for the pending source
        if pending_source == "claude-code":
            from .ingestors.claude_code import ClaudeCodeIngestor
            ingestor = ClaudeCodeIngestor()
        elif pending_source == "claude-desktop":
            from .ingestors.claude_desktop import ClaudeDesktopIngestor
            ingestor = ClaudeDesktopIngestor()
        else:
            console.print(
                f"[dim]Unknown pending source [cyan]{pending_source}[/cyan], skipping[/dim]"
            )
            continue

        _run_ingest(ingestor, db_path=db.path)
