"""
CLI commands for inspecting Contexa configuration.

Commands:
  contexa config show  — display the resolved configuration
"""

from __future__ import annotations

import json

import typer

from contexa.cli.client import api_get

app = typer.Typer(help="Inspect Contexa configuration")


@app.command()
def show(
    output_json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Display the current resolved configuration including defaults."""
    result = api_get("/config")

    if output_json:
        typer.echo(json.dumps(result, indent=2))
        return

    typer.echo("Contexa Configuration")
    typer.echo("─" * 40)
    for key, value in result.items():
        typer.echo(f"  {key}: {value}")
