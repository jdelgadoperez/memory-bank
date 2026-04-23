"""Distill recent sessions into high-signal summaries stored in the vector DB."""
from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import rich_click as click

from memory_bank.cli import CONTEXT_SETTINGS, cli, console
from memory_bank.db import MemoryDB, parse_time_expr
from memory_bank.schema import ChatMessage

DISTILL_MODEL = "claude-haiku-3-5-20241022"
DISTILL_MAX_TOKENS = 400
TRANSCRIPT_MAX_CHARS = 8_000
SUMMARY_ROLE = "summary"

_SYSTEM_PROMPT = (
    "You are a precise technical summarizer for coding session transcripts. "
    "Your output will be stored as a searchable memory record.\n\n"
    "Rules:\n"
    "- Output ONLY a bullet list using '-' as the prefix. No preamble, no headers, no trailing prose.\n"
    "- Produce 3-5 bullets. Each bullet must be a single line.\n"
    "- Stay strictly within the provided transcript. Do not infer or speculate.\n"
    "- If something is unclear from the transcript, omit it rather than guess.\n\n"
    "Cover (where present in the transcript):\n"
    "- What was built, fixed, or changed (be specific: file names, function names, commands)\n"
    "- Key decisions and the reason given for them\n"
    "- Errors encountered and the resolution applied\n"
    "- Patterns, techniques, or tools used"
)


def _build_transcript(messages: list[dict[str, object]]) -> str:
    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "")
        content = (msg.get("content") or "").strip()  # type: ignore[union-attr]
        if not content:
            continue
        if content.startswith("[tool:") or content.startswith("[tool_result:"):
            continue
        if role == "user":
            parts.append(f"[User]: {content[:150]}")
        elif role == "assistant":
            parts.append(content)
    joined = "\n\n".join(parts)
    # Prefer the end of the transcript (resolutions appear last).
    if len(joined) > TRANSCRIPT_MAX_CHARS:
        joined = joined[-TRANSCRIPT_MAX_CHARS:]
    return joined


def _summarize(transcript: str, api_key: str, *, project: str = "") -> str:
    import anthropic

    header = f"Project: {project}\n\n---\n\n" if project else ""
    user_content = header + transcript

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=DISTILL_MODEL,
        max_tokens=DISTILL_MAX_TOKENS,
        system=[{"type": "text", "text": _SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_content}],
    )
    if not response.content:
        raise ValueError("API returned empty content list")
    return response.content[0].text.strip()


@cli.command(context_settings=CONTEXT_SETTINGS)
@click.option(
    "--since",
    default="3h",
    show_default=True,
    help="Only distill sessions with activity in this window. Accepts: 1h, 7d, 2w, etc.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print sessions that would be summarized without writing anything.",
)
@click.option(
    "--db",
    "db_path",
    type=click.Path(),
    default=None,
    envvar="MEMORY_BANK_DB",
    metavar="DIR",
)
def distill(since: str, dry_run: bool, db_path: str | None) -> None:
    """Generate distilled summaries for recent sessions and store them in the DB.

    Reads assistant responses from each session, calls the Anthropic API to
    produce a concise bullet-point summary, and stores it as a searchable
    record. The recall hook then prefers these over raw session snippets.

    \b
    Requires ANTHROPIC_API_KEY to be set in your environment.

    \b
    Examples:
      memory-bank distill                  # summarize sessions from last 3 hours
      memory-bank distill --since 7d       # re-summarize last week
      memory-bank distill --dry-run        # preview without writing
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key and not dry_run:
        raise click.ClickException(
            "ANTHROPIC_API_KEY is not set. Export it before running distill."
        )

    since_iso = parse_time_expr(since)
    db = MemoryDB(Path(db_path) if db_path else None)

    sessions = db.list_sessions(since=since_iso)
    if not sessions:
        console.print(f"[dim]No sessions found since {since}.[/dim]")
        return

    # Find sessions already summarized in this window via a role-filtered scroll.
    # Using scroll (not semantic search) avoids false negatives from embedding distance.
    already_summarized: set[str] = db.list_summarized_session_ids(since=since_iso)

    # Filter out summary pseudo-sessions and already-summarized real sessions.
    pending = [
        s for s in sessions
        if s["session_id"] not in already_summarized
    ]

    if not pending:
        console.print(f"[dim]All sessions since {since} are already distilled.[/dim]")
        return

    console.print(
        f"[bold]Distilling[/bold] {len(pending)} session(s) since [cyan]{since}[/cyan]"
        + (" [dim](dry run)[/dim]" if dry_run else "") + "…"
    )

    inserted = 0
    skipped = 0

    for session_meta in pending:
        session_id = session_meta["session_id"]
        project = session_meta.get("project", "")
        last_ts = session_meta.get("last_ts", datetime.now(UTC).isoformat())
        title = session_meta.get("title", "")[:60]

        label = f"[cyan]{project}[/cyan] / [dim]{session_id[:12]}…[/dim]"
        if title:
            label += f" — {title}"

        if dry_run:
            console.print(f"  [dim]would summarize[/dim] {label}")
            continue

        messages = db.get_session(session_id)
        # Exclude any existing summary records from the transcript input.
        raw_messages = [m for m in messages if m.get("role") != SUMMARY_ROLE]
        transcript = _build_transcript(raw_messages)

        if not transcript.strip():
            console.print(f"  [yellow]skip[/yellow] {label} — no assistant content")
            skipped += 1
            continue

        try:
            summary_text = _summarize(transcript, api_key, project=project)
        except Exception as exc:
            console.print(f"  [red]error[/red] {label} — {exc}")
            skipped += 1
            continue

        msg_id = ChatMessage.make_id(
            source="claude-code",
            session_id=session_id,
            role=SUMMARY_ROLE,
            content=summary_text,
            timestamp=last_ts,
        )
        summary_msg = ChatMessage(
            id=msg_id,
            source="claude-code",
            session_id=session_id,
            project=project,
            role=SUMMARY_ROLE,
            content=summary_text,
            timestamp=last_ts,
            metadata={"distilled_from": session_id},
        )
        db.upsert([summary_msg])
        console.print(f"  [green]✓[/green] {label}")
        inserted += 1

    if not dry_run:
        console.print(
            f"\n[bold green]Done:[/bold green] {inserted} summarized, {skipped} skipped."
        )
