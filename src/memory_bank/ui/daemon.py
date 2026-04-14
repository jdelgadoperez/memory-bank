from __future__ import annotations

from pathlib import Path

import rich_click as click

from memory_bank.cli import CONTEXT_SETTINGS, console


_UI_PID_FILE = Path.home() / ".memory-bank" / "ui.pid"
_UI_LOG_FILE = Path.home() / ".memory-bank" / "ui.log"
_LOCAL_DOMAIN = "memory.local"


def _ui_url(port: int) -> str:
    """Return the best URL for the UI, preferring memory.local over localhost."""
    import socket

    try:
        socket.getaddrinfo(_LOCAL_DOMAIN, port, socket.AF_INET)
        return f"http://{_LOCAL_DOMAIN}:{port}"
    except socket.gaierror:
        return f"http://localhost:{port}"


def _read_ui_pid():
    """Read PID file, return (pid, port) or None."""
    import json

    try:
        data = json.loads(_UI_PID_FILE.read_text())
        return data["pid"], data["port"]
    except (json.JSONDecodeError, KeyError, OSError):
        return None


def _is_pid_alive(pid: int) -> bool:
    """Check whether a process with the given PID is still running."""
    import os

    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _register_daemon_commands(ui_group):
    @ui_group.command("start", context_settings=CONTEXT_SETTINGS)
    @click.option("--port", "-p", type=int, default=None, help="Override the UI port.")
    @click.pass_context
    def ui_start(ctx, port):
        """Start the UI server in the background.

        Spawns a detached process and writes its PID to
        [dim]~/.memory-bank/ui.pid[/dim]. Logs go to [dim]~/.memory-bank/ui.log[/dim].

        \b
        Examples:
          memory-bank ui start
          memory-bank ui start -p 8080
        """
        import json
        import shutil
        import subprocess

        port = port if port is not None else ctx.obj["port"]
        db = ctx.obj["db"]

        existing = _read_ui_pid()
        if existing:
            pid, old_port = existing
            if _is_pid_alive(pid):
                console.print(
                    f"[yellow]UI is already running[/yellow] (PID {pid}, port {old_port}).\n"
                    f"[dim]Run [cyan]memory-bank ui stop[/cyan] first.[/dim]"
                )
                return

        mb_bin = shutil.which("memory-bank")
        if not mb_bin:
            console.print("[bold red]Error:[/bold red] memory-bank not found on PATH.")
            return

        cmd = [mb_bin, "ui", "--no-browser", "-p", str(port)]
        if db:
            cmd.extend(["--db", db])

        _UI_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        log_fh = open(_UI_LOG_FILE, "a")

        proc = subprocess.Popen(
            cmd,
            stdout=log_fh,
            stderr=log_fh,
            start_new_session=True,
        )

        _UI_PID_FILE.write_text(json.dumps({"pid": proc.pid, "port": port}) + "\n")

        url = _ui_url(port)
        console.print(
            f"[bold green]Started[/bold green] UI server in background "
            f"(PID [cyan]{proc.pid}[/cyan], [cyan]{url}[/cyan])"
        )
        console.print(f"[dim]Log: {_UI_LOG_FILE}[/dim]")
        console.print(f"[dim]Stop with: [cyan]memory-bank ui stop[/cyan][/dim]")

        if not ctx.obj["no_browser"]:
            import webbrowser
            webbrowser.open(url)

    @ui_group.command("stop", context_settings=CONTEXT_SETTINGS)
    def ui_stop():
        """Stop a background UI server."""
        import os
        import signal

        existing = _read_ui_pid()
        if not existing:
            console.print("[yellow]No background UI server found.[/yellow]")
            return

        pid, port = existing
        if not _is_pid_alive(pid):
            console.print(f"[yellow]PID {pid} is not running (stale pid file).[/yellow]")
            _UI_PID_FILE.unlink(missing_ok=True)
            return

        os.kill(pid, signal.SIGTERM)
        _UI_PID_FILE.unlink(missing_ok=True)
        console.print(
            f"[bold green]Stopped[/bold green] UI server (PID {pid}, port {port})."
        )

    @ui_group.command("restart", context_settings=CONTEXT_SETTINGS)
    @click.option("--port", "-p", type=int, default=None, help="Override the UI port.")
    @click.pass_context
    def ui_restart(ctx, port):
        """Restart the background UI server."""
        ctx.invoke(ui_stop)
        ctx.invoke(ui_start, port=port)

    @ui_group.command("status", context_settings=CONTEXT_SETTINGS)
    def ui_status():
        """Check whether a background UI server is running."""
        existing = _read_ui_pid()
        if not existing:
            console.print("[dim]No background UI server configured.[/dim]")
            return

        pid, port = existing
        if _is_pid_alive(pid):
            console.print(
                f"[bold green]Running[/bold green]  PID [cyan]{pid}[/cyan]  "
                f"Port [cyan]{port}[/cyan]  [dim]{_ui_url(port)}[/dim]"
            )
        else:
            console.print(f"[yellow]Not running[/yellow] (stale pid file, PID {pid}).")
            _UI_PID_FILE.unlink(missing_ok=True)

    @ui_group.command("dev", context_settings=CONTEXT_SETTINGS)
    @click.option("--port", "-p", type=int, default=None, help="Override the UI port.")
    @click.pass_context
    def ui_dev(ctx, port):
        """Run the UI with auto-reload on source changes.

        Watches the memory_bank source directory and restarts the background
        server whenever a Python file changes. Press Ctrl+C to stop.

        \b
        Requires the dev extras:
          uv pip install -e '.[dev]'
        """
        try:
            from watchfiles import watch
        except ImportError:
            console.print(
                "[bold red]Error:[/bold red] watchfiles is not installed.\n"
                "[dim]Install dev extras: [cyan]uv pip install -e '.[dev]'[/cyan][/dim]"
            )
            return

        src_dir = Path(__file__).resolve().parent.parent
        console.print(
            f"[bold blue]Watching[/bold blue] [cyan]{src_dir}[/cyan] for changes\u2026"
        )
        console.print("[dim]Press Ctrl+C to stop.[/dim]\n")

        # Suppress browser opens during dev — restarts should be silent
        ctx.obj["no_browser"] = True
        ctx.invoke(ui_stop)
        ctx.invoke(ui_start, port=port)

        try:
            for changes in watch(src_dir, watch_filter=lambda _, path: path.endswith(".py")):
                changed_files = [str(Path(p).name) for _, p in changes]
                console.print(
                    f"\n[yellow]Changed:[/yellow] {', '.join(changed_files)}"
                )
                ctx.invoke(ui_stop)
                ctx.invoke(ui_start, port=port)
        except KeyboardInterrupt:
            console.print("\n[dim]Dev mode stopped.[/dim]")
