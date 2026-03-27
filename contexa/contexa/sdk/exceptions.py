"""
Exceptions raised by the Contexa Python SDK.

All SDK exceptions inherit from ContexaError so callers can catch
the base class if they don't need to distinguish between error types.

Example:
    from contexa.sdk import ContexaClient, ContexaConnectionError

    client = ContexaClient()
    try:
        ctx = client.get_context("some-id")
    except ContexaConnectionError:
        print("Daemon is not running. Start it with: contexa daemon start")
    except ContexaNotFoundError:
        print("Context not found")
"""

from __future__ import annotations


class ContexaError(Exception):
    """Base class for all Contexa SDK exceptions."""
    pass


class ContexaConnectionError(ContexaError):
    """Raised when the Contexa daemon is unreachable.

    This typically means the daemon is not running. Start it with:
        contexa daemon start
    """

    def __init__(self, base_url: str = "http://127.0.0.1:7474") -> None:
        self.base_url = base_url
        super().__init__(
            f"Cannot connect to Contexa daemon at {base_url}. "
            "Is it running? Start it with: contexa daemon start"
        )


class ContexaNotFoundError(ContexaError):
    """Raised when a requested resource does not exist (HTTP 404)."""

    def __init__(self, resource_id: str = "", detail: str = "") -> None:
        self.resource_id = resource_id
        msg = f"Resource not found: {resource_id}" if resource_id else "Resource not found"
        if detail:
            msg += f" — {detail}"
        super().__init__(msg)


class ContexaValidationError(ContexaError):
    """Raised when the request payload is invalid (HTTP 400)."""

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__(f"Validation error: {detail}" if detail else "Validation error")
