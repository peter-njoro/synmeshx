"""
Shared HTTP client for CLI commands.

All CLI commands communicate with the daemon exclusively via the Local API.
This module provides a thin wrapper around httpx that handles the base URL,
timeout, and the "daemon offline" error case uniformly.
"""

from __future__ import annotations

import sys
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:7474"
TIMEOUT = 10.0


def get_base_url() -> str:
    """Return the daemon base URL (reads config in future; uses default now)."""
    return DEFAULT_BASE_URL


def api_get(path: str) -> dict[str, Any]:
    """GET request to the Local API. Exits with error if daemon is offline."""
    try:
        r = httpx.get(f"{get_base_url()}{path}", timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except httpx.ConnectError:
        _daemon_offline()
    except httpx.HTTPStatusError as e:
        _http_error(e)


def api_post(path: str, json: dict[str, Any]) -> dict[str, Any]:
    """POST request to the Local API."""
    try:
        r = httpx.post(f"{get_base_url()}{path}", json=json, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except httpx.ConnectError:
        _daemon_offline()
    except httpx.HTTPStatusError as e:
        _http_error(e)


def api_put(path: str, json: dict[str, Any]) -> dict[str, Any]:
    """PUT request to the Local API."""
    try:
        r = httpx.put(f"{get_base_url()}{path}", json=json, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except httpx.ConnectError:
        _daemon_offline()
    except httpx.HTTPStatusError as e:
        _http_error(e)


def api_patch(path: str, json: dict[str, Any]) -> dict[str, Any]:
    """PATCH request to the Local API."""
    try:
        r = httpx.patch(f"{get_base_url()}{path}", json=json, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except httpx.ConnectError:
        _daemon_offline()
    except httpx.HTTPStatusError as e:
        _http_error(e)


def api_delete(path: str) -> None:
    """DELETE request to the Local API."""
    try:
        r = httpx.delete(f"{get_base_url()}{path}", timeout=TIMEOUT)
        r.raise_for_status()
    except httpx.ConnectError:
        _daemon_offline()
    except httpx.HTTPStatusError as e:
        _http_error(e)


def _daemon_offline() -> None:
    print("Error: Contexa daemon is not running. Start it with: contexa daemon start", file=sys.stderr)
    sys.exit(1)


def _http_error(e: httpx.HTTPStatusError) -> None:
    try:
        detail = e.response.json()
    except Exception:
        detail = e.response.text
    print(f"Error: {e.response.status_code} — {detail}", file=sys.stderr)
    sys.exit(1)
