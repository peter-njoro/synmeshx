"""
CLI commands for managing the Contexa daemon process.

Commands:
  contexa daemon start   — start the daemon in the background
  contexa daemon stop    — send SIGTERM to the daemon
  contexa daemon status  — check if the daemon is running
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

import typer
import httpx

app = typer.Typer(help="Manage the Contexa daemon")

PID_FILE = Path("~/.local/share/contexa/daemon.pid").expanduser()
DAEMON_URL = "http://127.0.0.1:7474"


@app.command()
def start():
    """Start the Contexa daemon in the background."""
    if _is_running():
        typer.echo("Daemon is already running.")
        raise typer.Exit(0)

    PID_FILE.parent.mkdir(parents=True, exist_ok=True)

    proc = subprocess.Popen(
        [sys.executable, "-m", "contexa.daemon"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    PID_FILE.write_text(str(proc.pid))
    typer.echo(f"Daemon started (PID {proc.pid})")


@app.command()
def stop():
    """Stop the Contexa daemon."""
    if not PID_FILE.exists():
        typer.echo("Daemon is not running (no PID file found).", err=True)
        raise typer.Exit(1)

    pid = int(PID_FILE.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        PID_FILE.unlink(missing_ok=True)
        typer.echo(f"Daemon stopped (PID {pid})")
    except ProcessLookupError:
        PID_FILE.unlink(missing_ok=True)
        typer.echo("Daemon process not found — PID file removed.", err=True)
        raise typer.Exit(1)


@app.command()
def status():
    """Check whether the Contexa daemon is running."""
    if not _is_running():
        typer.echo("Daemon is not running.", err=True)
        raise typer.Exit(1)

    try:
        r = httpx.get(f"{DAEMON_URL}/health", timeout=5.0)
        health = r.json()
        overall = health.get("status", "unknown")
        typer.echo(f"Daemon is running — status: {overall}")
        for component, info in health.items():
            if isinstance(info, dict):
                typer.echo(f"  {component}: {info.get('status', 'unknown')}")
    except httpx.ConnectError:
        typer.echo("Daemon process exists but API is not responding.", err=True)
        raise typer.Exit(1)


def _is_running() -> bool:
    """Return True if the daemon PID file exists and the process is alive."""
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)  # signal 0 = check existence only
        return True
    except (ProcessLookupError, ValueError):
        PID_FILE.unlink(missing_ok=True)
        return False
