from __future__ import annotations

import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path

import rich_click as click

from memory_bank.cli import CONTEXT_SETTINGS, cli, console
from memory_bank.commands.setup import _SKILLS_TARGET, _available_skills


def _current_version() -> str:
    try:
        return importlib.metadata.version("memory-bank")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _detect_install_dir(executable: str | None = None) -> Path | None:
    """Resolve the memory-bank repo root from the running Python executable.

    In both dev and managed installs the Python binary lives at:
      <repo>/.venv/bin/python

    So the repo root is three parents up from sys.executable.
    Returns None if the path doesn't look like a venv install.
    """
    exec_path = Path(executable or sys.executable).resolve()
    candidate = exec_path.parent.parent.parent
    if not (exec_path.parent.parent / "pyvenv.cfg").exists():
        return None
    return candidate


@cli.command(context_settings=CONTEXT_SETTINGS)
@click.option(
    "--dir",
    "install_dir",
    type=click.Path(),
    default=None,
    metavar="DIR",
    help="Override the install directory. Auto-detected from the running binary by default.",
)
def update(install_dir: str | None) -> None:
    """Pull the latest code and sync dependencies.

    Detects the install directory from the running binary, runs
    [dim]git pull --ff-only[/dim] and [dim]uv sync[/dim], then refreshes
    skill symlinks. Existing hook and MCP configuration is preserved.

    \b
    Examples:
      memory-bank update
      memory-bank update --dir ~/.local/share/memory-bank
    """
    resolved_dir: Path | None = (
        Path(install_dir).expanduser().resolve() if install_dir else _detect_install_dir()
    )

    if resolved_dir is None:
        raise click.ClickException(
            "Could not detect the memory-bank install directory from the running Python binary. "
            "Pass --dir explicitly: memory-bank update --dir ~/.local/share/memory-bank"
        )

    if not resolved_dir.is_dir():
        raise click.ClickException(f"Install directory does not exist: {resolved_dir}")

    if not (resolved_dir / ".git").is_dir():
        console.print(
            "[yellow]This install was not set up via install.sh (no .git directory found).[/yellow]\n"
            "If you installed with [bold]uv tool install[/bold], update with:\n\n"
            "  [bold]uv tool upgrade memory-bank --with mcp[/bold]\n"
        )
        raise click.ClickException(
            "Cannot auto-update a non-git install. Run the command above instead."
        )

    before_version = _current_version()
    console.print(f"[bold]memory-bank update[/bold]  [dim](current: v{before_version})[/dim]")
    console.print(f"[dim]Install directory: {resolved_dir}[/dim]\n")

    console.print("[bold]Pulling latest code[/bold]")
    pull = subprocess.run(
        ["git", "-C", str(resolved_dir), "pull", "--ff-only"],
        capture_output=True,
        text=True,
    )
    if pull.returncode != 0:
        console.print(f"[red]{pull.stderr.strip()}[/red]")
        raise click.ClickException("git pull failed — see above for details.")
    console.print(f"  [dim]{pull.stdout.strip()}[/dim]")

    console.print("\n[bold]Syncing dependencies[/bold]")
    sync = subprocess.run(
        ["uv", "sync", "--extra", "mcp"],
        cwd=str(resolved_dir),
        capture_output=True,
        text=True,
    )
    if sync.returncode != 0:
        console.print(f"[red]{sync.stderr.strip()}[/red]")
        raise click.ClickException("uv sync failed — see above for details.")
    output = (sync.stdout + sync.stderr).strip()
    if output:
        console.print(f"  [dim]{output}[/dim]")
    else:
        console.print("  [dim]Dependencies already up to date.[/dim]")

    console.print("\n[bold]Refreshing skills[/bold]")
    skills = _available_skills()
    if skills:
        _SKILLS_TARGET.mkdir(parents=True, exist_ok=True)
        for name, skill_path in skills:
            target = _SKILLS_TARGET / name
            if target.is_symlink():
                if Path(os.readlink(target)).resolve() == skill_path.resolve():
                    console.print(f"  [dim]{name} — already up to date[/dim]")
                    continue
                target.unlink()
            elif target.exists():
                console.print(f"  [yellow]{name} — exists but is not a symlink, skipping[/yellow]")
                continue
            target.symlink_to(skill_path)
            console.print(f"  [bold green]Refreshed:[/bold green] {name}")
    else:
        console.print("  [dim]No skills found (non-editable install?)[/dim]")

    after_version = _current_version()
    console.print()
    if before_version != after_version:
        console.print(
            f"[bold green]✓ Updated[/bold green]  "
            f"[dim]v{before_version}[/dim] → [bold]v{after_version}[/bold]"
        )
    else:
        console.print(
            f"[bold green]✓ Already up to date[/bold green]  [dim]v{after_version}[/dim]"
        )
    console.print("\n  Hooks and MCP configuration were not changed.")
