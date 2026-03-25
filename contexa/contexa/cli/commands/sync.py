"""
CLI commands for sync operations.
Fully implemented in task 11 (Sync Engine).

Commands:
  contexa sync trigger  — trigger a manual sync
  contexa sync log      — query the sync log
"""

from __future__ import annotations

import typer

app = typer.Typer(help="Manage sync operations")


@app.command()
def trigger():
    """Trigger a manual sync now. (Implemented in task 11)"""
    typer.echo("Sync engine not yet implemented.", err=True)
    raise typer.Exit(1)


@app.command()
def log():
    """Query the sync log. (Implemented in task 11)"""
    typer.echo("Sync engine not yet implemented.", err=True)
    raise typer.Exit(1)
