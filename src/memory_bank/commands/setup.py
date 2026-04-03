from __future__ import annotations

import os
import shutil
from pathlib import Path

import rich_click as click

from memory_bank.cli import CONTEXT_SETTINGS, cli, console
from memory_bank.commands.hooks import (
    PRECOMPACT_HOOK_COMMAND,
    PRECOMPACT_HOOK_MARKER,
    RECALL_HOOK_COMMAND,
    RECALL_HOOK_MARKER,
    SETTINGS_PATH,
    START_CONTEXT_COMMAND,
    START_HOOK_MARKER,
    STOP_HOOK_COMMAND,
    STOP_HOOK_MARKER,
    hook_entry,
    install_mcp,
    is_installed,
    is_mcp_installed,
    load_settings,
    remove_hooks,
    remove_mcp,
    save_settings,
)

_SKILLS_TARGET = Path("~/.claude/skills").expanduser()
_MEMORY_BANK_SKILL_MARKER = "memory-bank/skills/"


def _repo_root() -> Path | None:
    """Resolve the memory-bank repo root from this file's location.

    Returns None if the skills/ directory is not found (e.g. non-editable install).
    """
    # commands/ -> memory_bank/ -> src/ -> repo root
    root = Path(__file__).resolve().parent.parent.parent.parent
    if not (root / "skills").is_dir():
        return None
    return root


def _available_skills() -> list[tuple[str, Path]]:
    """Return (name, path) pairs for all skills in the repo."""
    root = _repo_root()
    if root is None:
        return []
    skills_dir = root / "skills"
    return [
        (d.name, d)
        for d in sorted(skills_dir.iterdir())
        if d.is_dir() and (d / "SKILL.md").exists()
    ]


def _installed_memory_bank_skills() -> list[tuple[str, Path]]:
    """Find memory-bank skill symlinks in ~/.claude/skills/, even if repo has moved.

    Detects symlinks whose target path contains 'memory-bank/skills/'.
    """
    if not _SKILLS_TARGET.is_dir():
        return []
    results: list[tuple[str, Path]] = []
    for entry in sorted(_SKILLS_TARGET.iterdir()):
        if not entry.is_symlink():
            continue
        target = Path(os.readlink(entry))
        if _MEMORY_BANK_SKILL_MARKER in str(target):
            results.append((entry.name, entry))
    return results


@cli.group(context_settings=CONTEXT_SETTINGS)
def setup():
    """Set up memory-bank integration with Claude Code.

    Installs skills into ~/.claude/skills/ and hooks into
    ~/.claude/settings.json so memory-bank is available in
    every Claude Code session.

    \b
    Quick start:
      memory-bank setup install
      memory-bank setup status
      memory-bank setup uninstall
    """


@setup.command(context_settings=CONTEXT_SETTINGS)
@click.option(
    "--skip-hooks",
    is_flag=True,
    default=False,
    help="Only install skills, skip hook and MCP installation.",
)
@click.option(
    "--on",
    "trigger",
    type=click.Choice(["stop", "start", "precompact", "recall", "both", "recommended", "all"]),
    default="stop",
    show_default=True,
    help="Which hook event to use (ignored with --skip-hooks).",
)
def install(skip_hooks: bool, trigger: str) -> None:
    """Install skills, hooks, and MCP server for Claude Code integration.

    Symlinks memory-bank skills into ~/.claude/skills/, installs
    auto-ingest hooks, and registers the MCP server in
    ~/.claude/settings.json.

    \b
    Examples:
      memory-bank setup install
      memory-bank setup install --skip-hooks
      memory-bank setup install --on all
    """
    if _repo_root() is None:
        raise click.ClickException(
            "Cannot find skills/ directory. "
            "memory-bank must be installed in editable mode (uv pip install -e .)."
        )
    skills = _available_skills()

    # Install skills
    console.print("[bold]Skills[/bold]")
    _SKILLS_TARGET.mkdir(parents=True, exist_ok=True)
    for name, skill_path in skills:
        target = _SKILLS_TARGET / name
        if target.is_symlink():
            existing = target.resolve()
            if existing == skill_path.resolve():
                console.print(f"  [dim]{name} — already linked[/dim]")
                continue
            else:
                target.unlink()
        elif target.exists():
            console.print(
                f"  [yellow]{name} — exists but is not a symlink, skipping[/yellow]"
            )
            continue
        target.symlink_to(skill_path)
        console.print(
            f"  [bold green]Installed:[/bold green] {name} → [dim]{skill_path}[/dim]"
        )

    # Install hooks and MCP
    if not skip_hooks:
        settings = load_settings()
        changed = False

        console.print("\n[bold]Hooks[/bold]")
        event_map: dict[str, list[tuple[str, str, str]]] = {
            "stop": [("Stop", STOP_HOOK_COMMAND, STOP_HOOK_MARKER)],
            "start": [("SessionStart", START_CONTEXT_COMMAND, START_HOOK_MARKER)],
            "precompact": [("PreCompact", PRECOMPACT_HOOK_COMMAND, PRECOMPACT_HOOK_MARKER)],
            "recall": [("UserPromptSubmit", RECALL_HOOK_COMMAND, RECALL_HOOK_MARKER)],
            "both": [
                ("Stop", STOP_HOOK_COMMAND, STOP_HOOK_MARKER),
                ("SessionStart", START_CONTEXT_COMMAND, START_HOOK_MARKER),
            ],
            "recommended": [
                ("Stop", STOP_HOOK_COMMAND, STOP_HOOK_MARKER),
                ("UserPromptSubmit", RECALL_HOOK_COMMAND, RECALL_HOOK_MARKER),
            ],
            "all": [
                ("Stop", STOP_HOOK_COMMAND, STOP_HOOK_MARKER),
                ("SessionStart", START_CONTEXT_COMMAND, START_HOOK_MARKER),
                ("PreCompact", PRECOMPACT_HOOK_COMMAND, PRECOMPACT_HOOK_MARKER),
                ("UserPromptSubmit", RECALL_HOOK_COMMAND, RECALL_HOOK_MARKER),
            ],
        }

        hooks_cfg = settings.setdefault("hooks", {})
        for event, command, marker in event_map[trigger]:
            if is_installed(settings, event, marker):
                console.print(f"  [dim]{event} hook — already installed[/dim]")
                continue
            hooks_cfg.setdefault(event, []).append(hook_entry(command))
            console.print(
                f"  [bold green]Installed:[/bold green] {event} hook → [dim]{command}[/dim]"
            )
            changed = True

        console.print("\n[bold]MCP Server[/bold]")
        if install_mcp(settings):
            console.print(
                "  [bold green]Installed:[/bold green] memory-bank MCP server"
            )
            changed = True
        else:
            console.print("  [dim]memory-bank MCP server — already configured[/dim]")

        if changed:
            save_settings(settings)

    console.print("\n[bold green]Setup complete![/bold green]")
    console.print("\n[bold]Next steps[/bold]")
    console.print("  1. Index your history:    [bold]memory-bank ingest claude-code[/bold]")
    console.print("  2. Open the browser UI:   [bold]memory-bank ui[/bold]")
    console.print("  3. Search from the CLI:   [bold]memory-bank search \"your query\"[/bold]")
    console.print(
        "\n  MCP tools available in your next Claude Code session: "
        "[dim]search_memory, list_sessions, get_session[/dim]"
    )


@setup.command(context_settings=CONTEXT_SETTINGS)
def uninstall() -> None:
    """Remove memory-bank skills and hooks from Claude Code.

    Removes skill symlinks from ~/.claude/skills/ and
    auto-ingest hooks from ~/.claude/settings.json.
    """
    # Try exact match first, fall back to pattern detection for moved repos
    skills = _available_skills()
    removed_skills = False

    console.print("[bold]Skills[/bold]")
    if skills:
        for name, skill_path in skills:
            target = _SKILLS_TARGET / name
            if target.is_symlink() and target.resolve() == skill_path.resolve():
                target.unlink()
                console.print(f"  [bold green]Removed:[/bold green] {name}")
                removed_skills = True
    else:
        # Repo not found or non-editable — detect by symlink target pattern
        for name, symlink in _installed_memory_bank_skills():
            symlink.unlink()
            console.print(f"  [bold green]Removed:[/bold green] {name}")
            removed_skills = True

    if not removed_skills:
        console.print("  [dim]No memory-bank skills found.[/dim]")

    settings = load_settings()
    settings_changed = False

    console.print("\n[bold]Hooks[/bold]")
    removed_events = remove_hooks()
    for event in removed_events:
        console.print(f"  [bold green]Removed:[/bold green] {event} hook")
    if not removed_events:
        console.print("  [dim]No memory-bank hooks found.[/dim]")

    console.print("\n[bold]MCP Server[/bold]")
    # Re-read settings since remove_hooks may have modified the file
    settings = load_settings()
    if remove_mcp(settings):
        save_settings(settings)
        console.print("  [bold green]Removed:[/bold green] memory-bank MCP server")
        settings_changed = True
    else:
        console.print("  [dim]No memory-bank MCP server found.[/dim]")

    if not removed_skills and not removed_events and not settings_changed:
        console.print("\n[dim]Nothing to remove.[/dim]")


@setup.command(context_settings=CONTEXT_SETTINGS)
def status() -> None:
    """Show what's currently installed.

    Checks skill symlinks and hook registrations.
    """
    skills = _available_skills()

    console.print("[bold]Skills[/bold]")
    if skills:
        for name, skill_path in skills:
            target = _SKILLS_TARGET / name
            if target.is_symlink() and target.resolve() == skill_path.resolve():
                console.print(f"  [bold green]✓[/bold green] {name}")
            elif target.is_symlink() and not target.exists():
                console.print(f"  [yellow]⚠[/yellow] {name} — dangling symlink")
            elif target.exists():
                console.print(f"  [yellow]⚠[/yellow] {name} — exists but not linked to repo")
            else:
                console.print(f"  [dim]✗ {name} — not installed[/dim]")
    else:
        # Repo not found — report what's installed by pattern
        installed = _installed_memory_bank_skills()
        if installed:
            for name, _ in installed:
                console.print(f"  [bold green]✓[/bold green] {name}")
        else:
            console.print("  [dim]No memory-bank skills found[/dim]")
        console.print("  [dim](repo root not found — showing installed skills only)[/dim]")

    console.print("\n[bold]Hooks[/bold]")
    if SETTINGS_PATH.exists():
        settings = load_settings()
        for event, marker, kind in [
            ("Stop", STOP_HOOK_MARKER, "ingest"),
            ("SessionStart", START_HOOK_MARKER, "context-summary"),
            ("PreCompact", PRECOMPACT_HOOK_MARKER, "pre-compaction ingest"),
            ("UserPromptSubmit", RECALL_HOOK_MARKER, "recall"),
        ]:
            if is_installed(settings, event, marker):
                console.print(
                    f"  [bold green]✓[/bold green] {event} [dim]({kind})[/dim]"
                )
            else:
                console.print(f"  [dim]✗ {event} ({kind}) — not installed[/dim]")

        console.print("\n[bold]MCP Server[/bold]")
        if is_mcp_installed(settings):
            console.print("  [bold green]✓[/bold green] memory-bank")
        else:
            console.print("  [dim]✗ memory-bank — not configured[/dim]")
    else:
        console.print("  [dim]No settings.json found[/dim]")

    console.print("\n[bold]CLI[/bold]")
    if shutil.which("memory-bank"):
        console.print("  [bold green]✓[/bold green] memory-bank on PATH")
    else:
        console.print(
            "  [yellow]⚠[/yellow] memory-bank not on PATH — "
            "run: uv pip install -e /path/to/memory-bank"
        )
