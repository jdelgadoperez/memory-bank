from __future__ import annotations

import importlib.metadata
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


def _uv_tool_root(executable: str | None = None) -> Path | None:
    """Return the uv tool root if running from a uv tool install, else None."""
    exec_path = Path(executable or sys.executable)  # no .resolve() — avoid following pyenv symlinks
    tool_root = exec_path.parent.parent
    return tool_root if (tool_root / "uv-receipt.toml").exists() else None


def _detect_uv_tool_install(executable: str | None = None) -> bool:
    return _uv_tool_root(executable) is not None


def _uv_tool_local_path(executable: str | None = None) -> Path | None:
    """Return the local directory path if memory-bank was installed from a local path, else None.

    uv writes directory = "..." in uv-receipt.toml for path installs.
    PyPI installs have only name/version, no directory key.
    """
    import tomllib

    tool_root = _uv_tool_root(executable)
    if tool_root is None:
        return None
    receipt = tool_root / "uv-receipt.toml"
    data = tomllib.loads(receipt.read_text())
    for req in data.get("tool", {}).get("requirements", []):
        if "directory" in req:
            return Path(req["directory"])
    return None


def _detect_install_dir(executable: str | None = None) -> Path | None:
    """Resolve the memory-bank repo root from the running Python executable.

    In git-based (install.sh) installs the Python binary lives at:
      <repo>/.venv/bin/python

    So the repo root is three parents up from sys.executable.
    Returns None if the path doesn't look like a venv install.

    Note: deliberately avoids Path.resolve() to prevent following pyenv
    symlinks, which would cause the pyvenv.cfg check to look in the wrong dir.
    """
    exec_path = Path(executable or sys.executable)  # no .resolve()
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


def _update_uv_tool(before_version: str, force: bool = False) -> None:
    local_path = _uv_tool_local_path()

    if local_path is not None:
        console.print(f"[dim]Detected local path install ({local_path}) — running git pull + uv tool install[/dim]\n")
        pull = subprocess.run(
            ["git", "-C", str(local_path), "pull", "--ff-only"],
            capture_output=True,
            text=True,
        )
        if pull.returncode != 0:
            console.print(f"[red]{pull.stderr.strip()}[/red]")
            raise click.ClickException("git pull failed — see above for details.")
        if pull.stdout.strip():
            console.print(f"  [dim]{pull.stdout.strip()}[/dim]")

        console.print("[bold]Reinstalling package[/bold]")
        cmd = ["uv", "tool", "install", str(local_path), "--reinstall"]
    else:
        if force:
            console.print("[dim]Detected uv tool install — running uv tool install --reinstall[/dim]\n")
            console.print("[bold]Reinstalling package[/bold]")
            cmd = ["uv", "tool", "install", "memory-bank", "--reinstall"]
        else:
            console.print("[dim]Detected uv tool install — running uv tool upgrade[/dim]\n")
            console.print("[bold]Upgrading package[/bold]")
            cmd = ["uv", "tool", "upgrade", "memory-bank"]

    upgrade = subprocess.run(cmd, capture_output=True, text=True)
    if upgrade.returncode != 0:
        console.print(f"[red]{upgrade.stderr.strip()}[/red]")
        recovery = f"uv tool install {local_path} --reinstall" if local_path else "uv tool install memory-bank --reinstall"
        raise click.ClickException(
            f"Upgrade failed — see above for details.\n\n"
            f"  To recover, run: [cyan]{recovery}[/cyan]"
        )
    output = (upgrade.stdout + upgrade.stderr).strip()
    if output:
        console.print(f"  [dim]{output}[/dim]")

    after_version = _current_version()
    console.print()
    _print_version_result(before_version, after_version)
    console.print("\n  Hooks and MCP configuration were not changed.")


def _update_git(resolved_dir: Path, before_version: str = "", force: bool = False) -> None:
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

    # git pull --ff-only exits 0 even when autostash reapplication leaves conflict
    # markers (the pull itself succeeded). Detect and abort before uv sync chokes.
    conflicts = subprocess.run(
        ["git", "-C", str(resolved_dir), "diff", "--name-only", "--diff-filter=U"],
        capture_output=True,
        text=True,
    )
    if conflicts.stdout.strip():
        conflicted = conflicts.stdout.strip().replace("\n", ", ")
        raise click.ClickException(
            f"Autostash reapplication left merge conflicts in: {conflicted}\n\n"
            f"  Resolve with: git -C {resolved_dir} checkout -- uv.lock\n"
            f"  Then re-run:  memory-bank update"
        )

    # uv sync may nuke and recreate .venv; force-load rich's unicode data now so
    # the lazy import doesn't fail after the venv files are gone.
    try:
        from rich.cells import cell_len as _cell_len
        _cell_len("preload")
    except Exception:
        pass

    console.print("\n[bold]Syncing dependencies[/bold]")
    sync_cmd = ["uv", "sync", "--reinstall"] if force else ["uv", "sync"]
    sync = subprocess.run(
        sync_cmd,
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
        from memory_bank.commands.setup import _install_skill, _is_editable_install

        editable = _is_editable_install()
        _SKILLS_TARGET.mkdir(parents=True, exist_ok=True)
        for name, skill_path in skills:
            result = _install_skill(name, skill_path, editable)
            if result is None:
                console.print(f"  [dim]{name} — already up to date[/dim]")
            else:
                console.print(f"  {result}")
    else:
        console.print("  [dim]No skills found (non-editable install?)[/dim]")

    if before_version:
        after_version = _current_version()
        console.print()
        _print_version_result(before_version, after_version)
        console.print("\n  Hooks and MCP configuration were not changed.")


@cli.command(context_settings=CONTEXT_SETTINGS)
@click.option(
    "--dir",
    "install_dir",
    type=click.Path(),
    default=None,
    metavar="DIR",
    help="Override the install directory. Auto-detected from the running binary by default.",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Force reinstall of all packages even if already on the latest version.",
)
def update(install_dir: str | None, force: bool) -> None:
    """Update memory-bank to the latest version.

    Detects the install type automatically:

    \b
    - git-based install (install.sh): runs git pull + uv sync, refreshes skills
    - uv tool install: runs uv tool upgrade memory-bank

    Existing hook and MCP configuration is preserved in both cases.

    \b
    Examples:
      memory-bank update
      memory-bank update --force
      memory-bank update --dir ~/.local/share/memory-bank
    """
    before_version = _current_version()
    console.print(f"[bold]memory-bank update[/bold]  [dim](current: v{before_version})[/dim]\n")

    # Explicit --dir always means a git-based install
    if install_dir:
        resolved_dir = Path(install_dir).expanduser().resolve()
        if not resolved_dir.is_dir():
            raise click.ClickException(f"Install directory does not exist: {resolved_dir}")
        _update_git(resolved_dir, before_version, force=force)
        return

    # uv tool install — detected via uv-receipt.toml at the tool root
    if _detect_uv_tool_install():
        _update_uv_tool(before_version, force=force)
        return

    # git-based install (install.sh)
    resolved_dir = _detect_install_dir()
    if resolved_dir is None:
        raise click.ClickException(
            "Could not detect the memory-bank install directory from the running Python binary. "
            "Pass --dir explicitly: memory-bank update --dir ~/.local/share/memory-bank"
        )
    if not resolved_dir.is_dir():
        raise click.ClickException(f"Install directory does not exist: {resolved_dir}")

    _update_git(resolved_dir, before_version, force=force)
