"""
CLI commands for managing trusted devices.

Commands:
  contexa trust list    — list trusted devices
  contexa trust add     — add a trusted device by device_id + public key file
  contexa trust remove  — revoke a trusted device
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from contexa.cli.client import api_delete, api_get, api_post

app = typer.Typer(help="Manage trusted devices")


@app.command(name="list")
def list_devices(
    output_json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """List all trusted devices."""
    results = api_get("/trust")

    if output_json:
        typer.echo(json.dumps(results, indent=2))
        return

    if not results:
        typer.echo("No trusted devices.")
        return

    for entry in results:
        label_str = f"  [{entry['label']}]" if entry.get("label") else ""
        typer.echo(f"{entry['device_id']}{label_str}")
        typer.echo(f"  key: {entry['public_key_hex'][:16]}...")
        typer.echo(f"  trusted since: {entry['trusted_at']}")


@app.command()
def add(
    device_id: str = typer.Argument(..., help="Device UUID to trust"),
    public_key_file: Path = typer.Argument(..., help="Path to file containing hex-encoded public key"),
    label: Optional[str] = typer.Option(None, "--label", help="Human-readable label for this device"),
):
    """Add a trusted device."""
    try:
        public_key_hex = public_key_file.read_text().strip()
    except OSError as e:
        typer.echo(f"Error: could not read public key file — {e}", err=True)
        raise typer.Exit(1)

    result = api_post("/trust", {
        "device_id": device_id,
        "public_key_hex": public_key_hex,
        "label": label,
    })
    typer.echo(f"Trusted device {result['device_id']}")
    if result.get("label"):
        typer.echo(f"  label: {result['label']}")


@app.command()
def remove(
    device_id: str = typer.Argument(..., help="Device UUID to revoke"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Revoke trust for a device."""
    if not yes:
        confirm = typer.confirm(f"Revoke trust for device {device_id}?")
        if not confirm:
            typer.echo("Aborted.")
            raise typer.Exit(0)

    api_delete(f"/trust/{device_id}")
    typer.echo(f"Revoked trust for device {device_id}")
