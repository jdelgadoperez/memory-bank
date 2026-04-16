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


def _print_version_result(before: str, after: str) -> None:
    if before != after:
        console.print(
            f"[bold green]✓ Updated[/bold green]  "
            f"[dim]v{before}[/dim] → [bold]v{after}[/bold]"
        )
    else:
        console.print(f"[bold green]✓ Already up to date[/bold green]  [dim]v{after}[/dim]")


def _update_uv_tool(before_version: str) -> None:
    console.print("[dim]Detected uv tool install — running uv tool upgrade[/dim]\n")
    console.print("[bold]Upgrading package[/bold]")
    upgrade = subprocess.run(
        ["uv", "tool", "upgrade", "memory-bank"],
        capture_output=True,
        text=True,
    )
    if upgrade.returncode != 0:
        console.print(f"[red]{upgrade.stderr.strip()}[/red]")
        raise click.ClickException("uv tool upgrade failed — see above for details.")
    output = (upgrade.stdout + upgrade.stderr).strip()
    if output:
        console.print(f"  [dim]{output}[/dim]")

    after_version = _current_version()
    console.print()
    _print_version_result(before_version, after_version)
    console.print("\n  Hooks and MCP configuration were not changed.")


def _update_git(resolved_dir: Path) -> None:
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
        ["uv", "sync"],
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
    """Update memory-bank to the latest version.

    Detects the install type automatically:

    \b
    - git-based install (install.sh): runs git pull + uv sync, refreshes skills
    - uv tool install: runs uv tool upgrade memory-bank

    Existing hook and MCP configuration is preserved in both cases.

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

    before_version = _current_version()
    console.print(f"[bold]memory-bank update[/bold]  [dim](current: v{before_version})[/dim]\n")

    if not (resolved_dir / ".git").is_dir():
        _update_uv_tool(before_version)
        return

    _update_git(resolved_dir)

    after_version = _current_version()
    console.print()
    _print_version_result(before_version, after_version)
    console.print("\n  Hooks and MCP configuration were not changed.")
