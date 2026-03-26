"""
CLI commands for sync operations.

Commands:
  contexa sync trigger  — trigger a manual sync now
  contexa sync log      — query the sync log with optional filters
"""

from __future__ import annotations

import json
from typing import Optional

import typer

from contexa.cli.client import api_get, api_post

app = typer.Typer(help="Manage sync operations")


@app.command()
def trigger():
    """Trigger a manual sync now."""
    result = api_post("/sync/trigger", {})
    typer.echo(f"Sync triggered: {result.get('message', 'queued')}")


@app.command()
def log(
    device: Optional[str] = typer.Option(None, "--device", help="Filter by device ID"),
    context: Optional[str] = typer.Option(None, "--context", help="Filter by context ID"),
    status: Optional[str] = typer.Option(None, "--status", help="Filter by status (success/conflict/failed/pending)"),
    since: Optional[str] = typer.Option(None, "--since", help="Filter entries after this ISO-8601 datetime"),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Query the sync log."""
    params = []
    if device:
        params.append(f"device_id={device}")
    if context:
        params.append(f"context_id={context}")
    if status:
        params.append(f"status={status}")
    if since:
        params.append(f"since={since}")

    path = "/sync/log"
    if params:
        path += "?" + "&".join(params)

    results = api_get(path)

    if output_json:
        typer.echo(json.dumps(results, indent=2))
        return

    if not results:
        typer.echo("No sync log entries found.")
        return

    for entry in results:
        status_str = entry["status"].upper()
        typer.echo(f"[{status_str}] {entry['created_at']}")
        typer.echo(f"  context: {entry['context_id']}  version: {entry['version_tag']}")
        typer.echo(f"  device:  {entry['device_id']}")
        if entry.get("error_msg"):
            typer.echo(f"  error:   {entry['error_msg']}")
