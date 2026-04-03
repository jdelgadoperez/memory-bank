from __future__ import annotations

import shutil
from pathlib import Path

import rich_click as click

from memory_bank.cli import CONTEXT_SETTINGS, console, cli
from memory_bank.commands.hooks import (
    SETTINGS_PATH,
    STOP_HOOK_COMMAND,
    STOP_HOOK_MARKER,
    START_CONTEXT_COMMAND,
    START_HOOK_MARKER,
    hook_entry,
    is_installed,
    load_settings,
    save_settings,
    remove_hooks,
)


_SKILLS_TARGET = Path("~/.claude/skills").expanduser()


def _repo_root() -> Path:
    """Resolve the memory-bank repo root from this file's location."""
    # commands/ -> memory_bank/ -> src/ -> repo root
    root = Path(__file__).resolve().parent.parent.parent.parent
    if not (root / "skills").is_dir():
        raise click.ClickException(
            f"Cannot find skills/ directory at {root}. "
            "memory-bank must be installed in editable mode (uv pip install -e .)."
        )
    return root


def _available_skills() -> list[tuple[str, Path]]:
    """Return (name, path) pairs for all skills in the repo."""
    skills_dir = _repo_root() / "skills"
    return [
        (d.name, d)
        for d in sorted(skills_dir.iterdir())
        if d.is_dir() and (d / "SKILL.md").exists()
    ]


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
    help="Only install skills, skip hook installation.",
)
@click.option(
    "--on",
    "trigger",
    type=click.Choice(["stop", "start", "both"]),
    default="stop",
    show_default=True,
    help="Which hook event to use (ignored with --skip-hooks).",
)
def install(skip_hooks: bool, trigger: str) -> None:
    """Install skills and hooks for Claude Code integration.

    Symlinks memory-bank skills into ~/.claude/skills/ and
    installs auto-ingest hooks into ~/.claude/settings.json.

    \b
    Examples:
      memory-bank setup install
      memory-bank setup install --skip-hooks
      memory-bank setup install --on both
    """
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

    # Install hooks
    if not skip_hooks:
        console.print("\n[bold]Hooks[/bold]")
        event_map: dict[str, list[tuple[str, str, str]]] = {
            "stop": [("Stop", STOP_HOOK_COMMAND, STOP_HOOK_MARKER)],
            "start": [("SessionStart", START_CONTEXT_COMMAND, START_HOOK_MARKER)],
            "both": [
                ("Stop", STOP_HOOK_COMMAND, STOP_HOOK_MARKER),
                ("SessionStart", START_CONTEXT_COMMAND, START_HOOK_MARKER),
            ],
        }

        settings = load_settings()
        hooks_cfg = settings.setdefault("hooks", {})
        installed_any = False

        for event, command, marker in event_map[trigger]:
            if is_installed(settings, event, marker):
                console.print(f"  [dim]{event} hook — already installed[/dim]")
                continue
            hooks_cfg.setdefault(event, []).append(hook_entry(command))
            console.print(
                f"  [bold green]Installed:[/bold green] {event} hook → [dim]{command}[/dim]"
            )
            installed_any = True

        if installed_any:
            save_settings(settings)

    console.print(
        "\n[bold green]Setup complete.[/bold green] "
        "Skills and hooks are ready for your next Claude Code session."
    )


@setup.command(context_settings=CONTEXT_SETTINGS)
def uninstall() -> None:
    """Remove memory-bank skills and hooks from Claude Code.

    Removes skill symlinks from ~/.claude/skills/ and
    auto-ingest hooks from ~/.claude/settings.json.
    """
    skills = _available_skills()
    removed_skills = False

    console.print("[bold]Skills[/bold]")
    for name, skill_path in skills:
        target = _SKILLS_TARGET / name
        if target.is_symlink() and target.resolve() == skill_path.resolve():
            target.unlink()
            console.print(f"  [bold green]Removed:[/bold green] {name}")
            removed_skills = True

    if not removed_skills:
        console.print("  [dim]No memory-bank skills found.[/dim]")

    console.print("\n[bold]Hooks[/bold]")
    removed_hooks = remove_hooks()
    if not removed_hooks:
        console.print("  [dim]No memory-bank hooks found.[/dim]")

    if not removed_skills and not removed_hooks:
        console.print("\n[dim]Nothing to remove.[/dim]")


@setup.command(context_settings=CONTEXT_SETTINGS)
def status() -> None:
    """Show what's currently installed.

    Checks skill symlinks and hook registrations.
    """
    skills = _available_skills()

    console.print("[bold]Skills[/bold]")
    for name, skill_path in skills:
        target = _SKILLS_TARGET / name
        if target.is_symlink() and target.resolve() == skill_path.resolve():
            console.print(f"  [bold green]✓[/bold green] {name}")
        elif target.exists():
            console.print(f"  [yellow]⚠[/yellow] {name} — exists but not linked to repo")
        else:
            console.print(f"  [dim]✗ {name} — not installed[/dim]")

    console.print("\n[bold]Hooks[/bold]")
    if SETTINGS_PATH.exists():
        settings = load_settings()
        for event, marker, kind in [
            ("Stop", STOP_HOOK_MARKER, "ingest"),
            ("SessionStart", START_HOOK_MARKER, "context-summary"),
        ]:
            if is_installed(settings, event, marker):
                console.print(
                    f"  [bold green]✓[/bold green] {event} [dim]({kind})[/dim]"
                )
            else:
                console.print(f"  [dim]✗ {event} ({kind}) — not installed[/dim]")
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
