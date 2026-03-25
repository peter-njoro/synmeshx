"""
CLI commands for managing Context objects.

Commands:
  contexa context create  — create a new context
  contexa context get     — get a context by ID
  contexa context list    — list all contexts
  contexa context label   — update a context's label
  contexa context delete  — delete a context
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer

from contexa.cli.client import api_delete, api_get, api_patch, api_post, api_put

app = typer.Typer(help="Manage context objects")


@app.command()
def create(
    json_str: Optional[str] = typer.Option(None, "--json", help="JSON string as content"),
    file: Optional[Path] = typer.Option(None, "--file", help="Path to JSON file"),
    label: Optional[str] = typer.Option(None, "--label", help="Human-readable label"),
    output_json: bool = typer.Option(False, "--json-output", help="Output as JSON"),
):
    """Create a new context."""
    if json_str:
        try:
            content = json.loads(json_str)
        except json.JSONDecodeError as e:
            typer.echo(f"Error: invalid JSON — {e}", err=True)
            raise typer.Exit(1)
    elif file:
        try:
            content = json.loads(file.read_text())
        except (json.JSONDecodeError, OSError) as e:
            typer.echo(f"Error: could not read file — {e}", err=True)
            raise typer.Exit(1)
    else:
        typer.echo("Error: provide --json or --file", err=True)
        raise typer.Exit(1)

    payload: dict = {"content": content}
    if label:
        payload["label"] = label

    result = api_post("/contexts", payload)

    if output_json:
        typer.echo(json.dumps(result, indent=2, default=str))
    else:
        typer.echo(f"Created context {result['context_id']} (version {result['version_tag']})")
        if result.get("label"):
            typer.echo(f"  label: {result['label']}")


@app.command()
def get(
    context_id: str = typer.Argument(..., help="Context UUID"),
    version: Optional[str] = typer.Option(None, "--version", help="Specific version tag"),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Get a context by ID (latest version by default)."""
    if version:
        path = f"/contexts/{context_id}/versions/{version}"
    else:
        path = f"/contexts/{context_id}"

    result = api_get(path)

    if output_json:
        typer.echo(json.dumps(result, indent=2, default=str))
    else:
        typer.echo(f"Context: {result['context_id']}")
        typer.echo(f"  version:  {result['version_tag']}")
        typer.echo(f"  checksum: {result['checksum'][:16]}...")
        if result.get("label"):
            typer.echo(f"  label:    {result['label']}")
        typer.echo(f"  content:  {json.dumps(result['content'], indent=4)}")


@app.command(name="list")
def list_contexts(
    output_json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """List all contexts."""
    results = api_get("/contexts")

    if output_json:
        typer.echo(json.dumps(results, indent=2, default=str))
        return

    if not results:
        typer.echo("No contexts found.")
        return

    for item in results:
        label_str = f"  [{item['label']}]" if item.get("label") else ""
        typer.echo(f"{item['context_id']}  v{item['latest_version_tag']}{label_str}")


@app.command()
def label(
    context_id: str = typer.Argument(..., help="Context UUID"),
    new_label: Optional[str] = typer.Argument(None, help="New label (omit to clear)"),
):
    """Set or update the label on a context."""
    result = api_patch(f"/contexts/{context_id}/label", {"label": new_label})
    if new_label:
        typer.echo(f"Label updated: {result['context_id']} → \"{new_label}\"")
    else:
        typer.echo(f"Label cleared: {result['context_id']}")


@app.command()
def delete(
    context_id: str = typer.Argument(..., help="Context UUID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Delete a context and all its versions."""
    if not yes:
        confirm = typer.confirm(f"Delete context {context_id} and all its versions?")
        if not confirm:
            typer.echo("Aborted.")
            raise typer.Exit(0)

    api_delete(f"/contexts/{context_id}")
    typer.echo(f"Deleted context {context_id}")
