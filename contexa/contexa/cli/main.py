"""
Contexa CLI root application.

Entry point: `contexa` (defined in pyproject.toml [project.scripts])

Command groups:
  contexa daemon   — start, stop, status
  contexa context  — create, get, list, label, delete
  contexa trust    — list, add, remove (task 8)
  contexa sync     — trigger, log (task 11)
  contexa config   — show
"""

from __future__ import annotations

import typer

from contexa.cli.commands import config, context, daemon, sync, trust

app = typer.Typer(
    name="contexa",
    help="Contexa — local-first context engine for AI agents and tools",
    no_args_is_help=True,
)

app.add_typer(daemon.app, name="daemon")
app.add_typer(context.app, name="context")
app.add_typer(trust.app, name="trust")
app.add_typer(sync.app, name="sync")
app.add_typer(config.app, name="config")


if __name__ == "__main__":
    app()
