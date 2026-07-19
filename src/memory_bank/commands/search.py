from __future__ import annotations

from pathlib import Path

import rich_click as click

from memory_bank.cli import CONTEXT_SETTINGS, ROLE_STYLES, console, cli


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
    type=click.FloatRange(0.0, 1.0),
    metavar="FLOAT",
    help="Discard results below this similarity score (0–1). Default: 0 (no filter). "
         "Recommended: 0.5 in agent contexts to avoid low-quality hits.",
)
@click.option(
    "--snippet",
    default=None,
    type=click.IntRange(min=1),
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
@click.option(
    "--category",
    default=None,
    type=click.Choice(["bugfix", "feature", "refactor", "decision", "research"]),
    help="Only return assistant messages tagged with this category.",
)
def search(
    query, limit, source, project, role, session, since, before, context_n,
    current_project, db, as_json, agent, min_score, snippet, dedupe, category,
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

    from memory_bank.db import DatabaseLockedError, MemoryDB, parse_time_expr
    from rich.text import Text

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
    try:
        results = db_obj.search(
            query=query,
            limit=limit,
            source=source,
            project=project,
            role=role,
            session_id=session,
            since=since_iso,
            before=before_iso,
            category=category,
        )
    except DatabaseLockedError as exc:
        raise click.ClickException(str(exc)) from exc

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
            from rich.panel import Panel
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

    from memory_bank.db import DatabaseLockedError, MemoryDB, parse_time_expr
    from rich.table import Table

    since_iso = parse_time_expr(since) if since else None
    before_iso = parse_time_expr(before) if before else None

    db_obj = MemoryDB(Path(db) if db else None)
    try:
        result = db_obj.list_sessions(
            source=source,
            project=project,
            since=since_iso,
            before=before_iso,
            limit=limit,
        )
    except DatabaseLockedError as exc:
        raise click.ClickException(str(exc)) from exc

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

    from memory_bank.db import DatabaseLockedError, MemoryDB
    from rich.rule import Rule

    db_obj = MemoryDB(Path(db) if db else None)
    try:
        messages = db_obj.get_session(session_id)
    except DatabaseLockedError as exc:
        raise click.ClickException(str(exc)) from exc

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
