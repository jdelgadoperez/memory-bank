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
        from memory_bank.mcp_server import run_mcp_server
    except ImportError as e:
        console.print(
            f"[bold red]Error:[/bold red] MCP server requires the 'mcp' package.\n"
            f"Install it with: [cyan]pip install 'mcp>=1.0'[/cyan]\n\nDetails: {e}"
        )
        raise SystemExit(1)

    from memory_bank.db import MemoryDB

    db_obj = MemoryDB(Path(db) if db else None)
    run_mcp_server(db_obj)
