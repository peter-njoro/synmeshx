"""
CLI commands for managing trusted devices.
Fully implemented in task 8 (Device Identity and Trust_Store).

Commands:
  contexa trust list    — list trusted devices
  contexa trust add     — add a trusted device
  contexa trust remove  — remove a trusted device
"""

from __future__ import annotations

import typer

app = typer.Typer(help="Manage trusted devices")


@app.command(name="list")
def list_devices():
    """List all trusted devices. (Implemented in task 8)"""
    typer.echo("Trust store not yet implemented.", err=True)
    raise typer.Exit(1)


@app.command()
def add(device_id: str, public_key_file: str):
    """Add a trusted device. (Implemented in task 8)"""
    typer.echo("Trust store not yet implemented.", err=True)
    raise typer.Exit(1)


@app.command()
def remove(device_id: str):
    """Remove a trusted device. (Implemented in task 8)"""
    typer.echo("Trust store not yet implemented.", err=True)
    raise typer.Exit(1)
