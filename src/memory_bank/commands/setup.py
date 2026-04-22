from __future__ import annotations

import importlib.resources
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


def _is_editable_install() -> bool:
    """Return True if running from an editable (source) install.

    In an editable install the source tree is live — we can symlink directly
    to the SKILL.md files so edits take effect immediately. In a non-editable
    install (uv tool install, pip install) we copy instead.
    """
    # commands/ -> memory_bank/ -> src/ -> repo root
    root = Path(__file__).resolve().parent.parent.parent.parent
    return (root / "pyproject.toml").is_file()


def _skills_source_dir() -> Path | None:
    """Return the path to the bundled skills directory inside the package.

    Works for both editable and non-editable installs by using
    importlib.resources to locate the installed package data.
    Returns None only if the package data is missing entirely.

    Note: casts the Traversable ref to a Path directly. This is valid for
    all real-filesystem installs (editable, uv tool, pip). zipimport is not
    a concern here — memory-bank is never distributed as a zip.
    """
    try:
        ref = importlib.resources.files("memory_bank") / "skills"
        path = Path(str(ref))
        return path if path.is_dir() else None
    except (TypeError, FileNotFoundError, NotImplementedError):
        return None


def _available_skills() -> list[tuple[str, Path]]:
    """Return (name, path) pairs for all bundled skills."""
    skills_dir = _skills_source_dir()
    if skills_dir is None:
        return []
    return [
        (d.name, d)
        for d in sorted(skills_dir.iterdir())
        if d.is_dir() and (d / "SKILL.md").exists()
    ]


def _install_skill(name: str, skill_path: Path, editable: bool) -> str | None:
    """Install a single skill into ~/.claude/skills/.

    For editable installs: symlink to the source so edits are live.
    For non-editable installs: copy the skill directory.

    Returns a status string for display, or None if already up to date.
    """
    target = _SKILLS_TARGET / name

    if editable:
        if target.is_symlink():
            if Path(os.readlink(target)).resolve() == skill_path.resolve():
                return None  # already up to date
            target.unlink()
        elif target.exists():
            shutil.rmtree(target)
        target.symlink_to(skill_path)
        return f"[bold green]Installed:[/bold green] {name} → [dim]{skill_path}[/dim]"
    else:
        if target.exists():
            # Check if already current by comparing SKILL.md content
            existing = target / "SKILL.md"
            source = skill_path / "SKILL.md"
            if existing.is_file() and existing.read_bytes() == source.read_bytes():
                return None  # already up to date
            shutil.rmtree(target)
        shutil.copytree(skill_path, target)
        return f"[bold green]Installed:[/bold green] {name} [dim](copied)[/dim]"


def _installed_memory_bank_skills() -> list[tuple[str, Path]]:
    """Find memory-bank skill entries in ~/.claude/skills/.

    Detects both symlinks (editable installs) and copied directories
    (non-editable installs) that contain a SKILL.md with memory-bank content.
    """
    if not _SKILLS_TARGET.is_dir():
        return []
    results: list[tuple[str, Path]] = []
    for entry in sorted(_SKILLS_TARGET.iterdir()):
        skill_md = entry / "SKILL.md"
        if not skill_md.exists():
            continue
        # Symlink path check (editable)
        if entry.is_symlink() and _MEMORY_BANK_SKILL_MARKER in str(os.readlink(entry)):
            results.append((entry.name, entry))
            continue
        # Copied directory check (non-editable) — look for memory-bank marker in SKILL.md
        if entry.is_dir() and "memory-bank" in skill_md.read_text():
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
    default="recommended",
    show_default=True,
    help="Which hook event to use (ignored with --skip-hooks).",
)
def install(skip_hooks: bool, trigger: str) -> None:
    """Install skills, hooks, and MCP server for Claude Code integration.

    Installs memory-bank skills into ~/.claude/skills/, registers
    auto-ingest hooks, and configures the MCP server in
    ~/.claude/settings.json.

    Works with both uv tool installs and editable (source) installs.

    \b
    Examples:
      memory-bank setup install
      memory-bank setup install --skip-hooks
      memory-bank setup install --on all
    """
    skills = _available_skills()
    if not skills:
        raise click.ClickException(
            "No skills found in the installed package. "
            "Try reinstalling: uv tool install memory-bank"
        )

    editable = _is_editable_install()

    # Install skills
    console.print("[bold]Skills[/bold]")
    _SKILLS_TARGET.mkdir(parents=True, exist_ok=True)
    for name, skill_path in skills:
        result = _install_skill(name, skill_path, editable)
        if result is None:
            console.print(f"  [dim]{name} — already up to date[/dim]")
        else:
            console.print(f"  {result}")

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

    Removes skill entries from ~/.claude/skills/ and
    auto-ingest hooks from ~/.claude/settings.json.
    """
    skills = _available_skills()
    editable = _is_editable_install()
    removed_skills = False

    console.print("[bold]Skills[/bold]")
    if skills and editable:
        for name, skill_path in skills:
            target = _SKILLS_TARGET / name
            if target.is_symlink() and target.resolve() == skill_path.resolve():
                target.unlink()
                console.print(f"  [bold green]Removed:[/bold green] {name}")
                removed_skills = True
    else:
        # Non-editable install or repo not found — detect by content pattern
        for name, entry in _installed_memory_bank_skills():
            if entry.is_symlink():
                entry.unlink()
            else:
                shutil.rmtree(entry)
            console.print(f"  [bold green]Removed:[/bold green] {name}")
            removed_skills = True

    if not removed_skills:
        console.print("  [dim]No memory-bank skills found.[/dim]")

    console.print("\n[bold]Hooks[/bold]")
    removed_events = remove_hooks()
    for event in removed_events:
        console.print(f"  [bold green]Removed:[/bold green] {event} hook")
    if not removed_events:
        console.print("  [dim]No memory-bank hooks found.[/dim]")

    console.print("\n[bold]MCP Server[/bold]")
    settings = load_settings()
    if remove_mcp(settings):
        save_settings(settings)
        console.print("  [bold green]Removed:[/bold green] memory-bank MCP server")
    else:
        console.print("  [dim]No memory-bank MCP server found.[/dim]")


@setup.command(context_settings=CONTEXT_SETTINGS)
def status() -> None:
    """Show what's currently installed.

    Checks skill entries and hook registrations.
    """
    skills = _available_skills()
    editable = _is_editable_install()

    console.print("[bold]Skills[/bold]")
    if skills:
        for name, skill_path in skills:
            target = _SKILLS_TARGET / name
            if editable:
                if target.is_symlink() and target.resolve() == skill_path.resolve():
                    console.print(f"  [bold green]✓[/bold green] {name}")
                elif target.is_symlink() and not target.exists():
                    console.print(f"  [yellow]⚠[/yellow] {name} — dangling symlink")
                elif target.exists():
                    console.print(f"  [yellow]⚠[/yellow] {name} — exists but not linked to repo")
                else:
                    console.print(f"  [dim]✗ {name} — not installed[/dim]")
            else:
                if target.is_dir() and (target / "SKILL.md").exists():
                    console.print(f"  [bold green]✓[/bold green] {name}")
                else:
                    console.print(f"  [dim]✗ {name} — not installed[/dim]")
    else:
        installed = _installed_memory_bank_skills()
        if installed:
            for name, _ in installed:
                console.print(f"  [bold green]✓[/bold green] {name}")
        else:
            console.print("  [dim]No memory-bank skills found[/dim]")

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
            "add ~/.local/bin to PATH or run: uv tool install memory-bank"
        )
