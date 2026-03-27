"""
Contexa Python SDK.

The SDK provides a typed Python client for the Contexa local context engine.
Install with: pip install contexa

Quick start:
    from contexa.sdk import ContexaClient

    client = ContexaClient()
    ctx = client.create_context({"task": "my task"}, label="my-label")
    print(ctx["context_id"])
"""

from contexa.sdk.client import ContexaClient
from contexa.sdk.exceptions import (
    ContexaConnectionError,
    ContexaError,
    ContexaNotFoundError,
    ContexaValidationError,
)

__all__ = [
    "ContexaClient",
    "ContexaError",
    "ContexaConnectionError",
    "ContexaNotFoundError",
    "ContexaValidationError",
]
