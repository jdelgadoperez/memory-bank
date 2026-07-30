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
    default=None,
    help="Only distill sessions with activity in this window. Accepts: 1h, 7d, 2w, etc.  [default: 3h]",
)
@click.option(
    "--before",
    default=None,
    help="Only distill sessions last active BEFORE this cutoff (e.g. 90d). "
    "Relaxes the --since default so old sessions are reachable.",
)
@click.option(
    "--replace-raw",
    is_flag=True,
    default=False,
    help="After a summary is written, delete that session's raw messages. "
    "Soft-delete unless --hard is also given.",
)
@click.option(
    "--hard",
    is_flag=True,
    default=False,
    help="With --replace-raw, permanently remove raw messages instead of soft-deleting. "
    "Irreversible.",
)
@click.option(
    "--limit",
    type=int,
    default=None,
    metavar="N",
    help="Process at most N sessions (oldest first), for batching large backlogs.",
)
@click.option(
    "--min-messages",
    type=int,
    default=None,
    metavar="N",
    help="Skip sessions with fewer than N messages — summarizing a tiny session "
    "costs an API call to reclaim almost nothing.",
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
def distill(
    since: str | None,
    before: str | None,
    replace_raw: bool,
    hard: bool,
    limit: int | None,
    min_messages: int | None,
    dry_run: bool,
    db_path: str | None,
) -> None:
    """Generate distilled summaries for sessions and store them in the DB.

    Reads assistant responses from each session, calls the Anthropic API to
    produce a concise bullet-point summary, and stores it as a searchable
    record. The recall hook then prefers these over raw session snippets.

    \b
    With --replace-raw the session's raw messages are deleted once its summary
    has been written, collapsing an old session to a single searchable record.

    \b
    Requires ANTHROPIC_API_KEY to be set in your environment.

    \b
    Examples:
      memory-bank distill                  # summarize sessions from last 3 hours
      memory-bank distill --since 7d       # re-summarize last week
      memory-bank distill --dry-run        # preview without writing
      memory-bank distill --before 90d --replace-raw --limit 200 --dry-run
    """
    if hard and not replace_raw:
        raise click.ClickException("--hard only applies together with --replace-raw.")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key and not dry_run:
        raise click.ClickException(
            "ANTHROPIC_API_KEY is not set. Export it before running distill."
        )

    # --since defaults to 3h, but that would exclude everything --before targets.
    # Only apply the default when the user gave neither bound.
    if since is None:
        since = None if before else "3h"

    since_iso = parse_time_expr(since) if since else None
    before_iso = parse_time_expr(before) if before else None
    db = MemoryDB(Path(db_path) if db_path else None)

    window = " and ".join(
        p for p in (f"since {since}" if since else "", f"before {before}" if before else "") if p
    ) or "all time"

    sessions = db.list_sessions(since=since_iso, before=before_iso)
    if not sessions:
        console.print(f"[dim]No sessions found {window}.[/dim]")
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
        console.print(f"[dim]All sessions {window} are already distilled.[/dim]")
        return

    if min_messages is not None:
        too_small = [s for s in pending if s.get("message_count", 0) < min_messages]
        pending = [s for s in pending if s.get("message_count", 0) >= min_messages]
        if too_small:
            console.print(
                f"[dim]Skipping {len(too_small)} session(s) under {min_messages} messages "
                f"({sum(s.get('message_count', 0) for s in too_small)} msgs).[/dim]"
            )
        if not pending:
            console.print(f"[dim]No sessions {window} meet the size threshold.[/dim]")
            return

    # Oldest first, so batched runs chew through the backlog from the far end.
    pending.sort(key=lambda s: s.get("last_ts", ""))
    total_matched = len(pending)
    if limit is not None:
        pending = pending[:limit]

    console.print(
        f"[bold]Distilling[/bold] {len(pending)} session(s) {window}"
        + (f" [dim](of {total_matched} matched)[/dim]" if len(pending) < total_matched else "")
        + (" [dim](dry run)[/dim]" if dry_run else "") + "…"
    )
    if replace_raw:
        mode = "[red]hard delete[/red]" if hard else "soft delete"
        console.print(
            f"  [yellow]--replace-raw[/yellow]: raw messages will be removed via {mode} "
            "after each summary is written."
        )
        if not hard:
            console.print(
                "  [dim]Soft-deleted points stay resident until purged (90d), so the "
                "collection will not shrink yet.[/dim]"
            )

    inserted = 0
    skipped = 0
    replaced = 0

    for session_meta in pending:
        session_id = session_meta["session_id"]
        project = session_meta.get("project", "")
        # Carry the session's real source so summaries of claude-desktop /
        # chatgpt sessions aren't mislabeled as claude-code (which would
        # corrupt --source filtering and stats breakdowns).
        source = session_meta.get("source") or "claude-code"
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
            source=source,
            session_id=session_id,
            role=SUMMARY_ROLE,
            content=summary_text,
            timestamp=last_ts,
        )
        summary_msg = ChatMessage(
            id=msg_id,
            source=source,
            session_id=session_id,
            project=project,
            role=SUMMARY_ROLE,
            content=summary_text,
            timestamp=last_ts,
            metadata={"distilled_from": session_id},
        )
        db.upsert([summary_msg])
        inserted += 1

        # Only ever runs after the summary above is durably written — a session
        # whose summarization failed took an earlier `continue` and keeps its raw
        # messages. The summary role is excluded so it survives its own cleanup.
        removed = 0
        if replace_raw:
            try:
                removed = db.delete_session(
                    session_id, exclude_role=SUMMARY_ROLE, hard=hard
                )
                replaced += removed
            except Exception as exc:
                console.print(
                    f"  [yellow]warn[/yellow] {label} — summary kept, raw delete failed: {exc}"
                )

        suffix = f" [dim]−{removed} raw[/dim]" if removed else ""
        console.print(f"  [green]✓[/green] {label}{suffix}")

    if not dry_run:
        console.print(
            f"\n[bold green]Done:[/bold green] {inserted} summarized, {skipped} skipped."
        )
        if replace_raw:
            # Net delta: each session trades N raw messages for 1 summary record.
            net = inserted - replaced
            console.print(
                f"[bold]Raw messages removed:[/bold] {replaced} "
                f"[dim](net point change: {net:+,})[/dim]"
            )
            if not hard and replaced:
                console.print(
                    "[dim]Soft-deleted — collection size is unchanged until these are "
                    "purged. Re-run with --hard to reclaim immediately.[/dim]"
                )
        if limit is not None and total_matched > len(pending):
            console.print(
                f"[dim]{total_matched - len(pending)} session(s) still pending — "
                "re-run to continue.[/dim]"
            )
