"""
ContexaClient — Python SDK for the Contexa local context engine.

The SDK wraps the Contexa Local API (running at localhost:7474 by default)
into a clean, typed Python interface. It is the primary integration surface
for AI agents and tools built on top of Contexa.

Quick start:
    from contexa.sdk import ContexaClient

    client = ContexaClient()

    # Store some context
    ctx = client.create_context(
        content={"task": "refactor auth module", "status": "in_progress"},
        label="auth-refactor"
    )

    # Read it back
    ctx = client.get_context(ctx["context_id"])

    # Search semantically (requires embeddings to be configured)
    results = client.search("authentication tasks")
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

import httpx

from contexa.sdk.exceptions import (
    ContexaConnectionError,
    ContexaNotFoundError,
    ContexaValidationError,
)

DEFAULT_BASE_URL = "http://127.0.0.1:7474"
DEFAULT_TIMEOUT = 10.0


class ContexaClient:
    """Python client for the Contexa Local API.

    All methods communicate with the Contexa daemon running on localhost.
    The daemon must be running before any method is called.

    Args:
        base_url: Base URL of the Local API. Defaults to http://127.0.0.1:7474.
        timeout: Request timeout in seconds. Defaults to 10.0.

    Raises:
        ContexaConnectionError: If the daemon is not running or unreachable.
        ContexaNotFoundError: If a requested resource does not exist.
        ContexaValidationError: If a request payload is invalid.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Internal HTTP helpers
    # ------------------------------------------------------------------

    def _get(self, path: str) -> Any:
        """Send a GET request and return the parsed JSON response."""
        try:
            r = httpx.get(f"{self._base_url}{path}", timeout=self._timeout)
        except httpx.ConnectError:
            raise ContexaConnectionError(self._base_url)
        self._raise_for_status(r)
        return r.json()

    def _post(self, path: str, json: dict[str, Any]) -> Any:
        """Send a POST request and return the parsed JSON response."""
        try:
            r = httpx.post(f"{self._base_url}{path}", json=json, timeout=self._timeout)
        except httpx.ConnectError:
            raise ContexaConnectionError(self._base_url)
        self._raise_for_status(r)
        return r.json()

    def _put(self, path: str, json: dict[str, Any]) -> Any:
        """Send a PUT request and return the parsed JSON response."""
        try:
            r = httpx.put(f"{self._base_url}{path}", json=json, timeout=self._timeout)
        except httpx.ConnectError:
            raise ContexaConnectionError(self._base_url)
        self._raise_for_status(r)
        return r.json()

    def _patch(self, path: str, json: dict[str, Any]) -> Any:
        """Send a PATCH request and return the parsed JSON response."""
        try:
            r = httpx.patch(f"{self._base_url}{path}", json=json, timeout=self._timeout)
        except httpx.ConnectError:
            raise ContexaConnectionError(self._base_url)
        self._raise_for_status(r)
        return r.json()

    def _delete(self, path: str) -> None:
        """Send a DELETE request."""
        try:
            r = httpx.delete(f"{self._base_url}{path}", timeout=self._timeout)
        except httpx.ConnectError:
            raise ContexaConnectionError(self._base_url)
        self._raise_for_status(r)

    def _raise_for_status(self, response: httpx.Response) -> None:
        """Raise a typed SDK exception for 4xx/5xx responses."""
        if response.status_code == 404:
            try:
                detail = response.json().get("detail", "")
                resource_id = response.json().get("context_id", "")
            except Exception:
                detail, resource_id = "", ""
            raise ContexaNotFoundError(resource_id=resource_id, detail=detail)

        if response.status_code in (400, 422):
            try:
                detail = str(response.json().get("detail", response.text))
            except Exception:
                detail = response.text
            raise ContexaValidationError(detail=detail)

        if response.status_code >= 500:
            try:
                msg = response.json().get("message", response.text)
            except Exception:
                msg = response.text
            from contexa.sdk.exceptions import ContexaError
            raise ContexaError(f"Daemon error ({response.status_code}): {msg}")

    # ------------------------------------------------------------------
    # Context operations
    # ------------------------------------------------------------------

    def create_context(
        self,
        content: dict[str, Any],
        label: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a new context with an initial version.

        Args:
            content: Arbitrary JSON-serialisable dict — the context payload.
            label: Optional human-readable label for this context.

        Returns:
            A dict representing the created ContextVersion with keys:
            version_id, context_id, version_tag, parent_version, content,
            checksum, created_at, label.

        Raises:
            ContexaConnectionError: If the daemon is not running.
            ContexaValidationError: If the content is not a valid dict.
        """
        payload: dict[str, Any] = {"content": content}
        if label is not None:
            payload["label"] = label
        return self._post("/contexts", payload)

    def get_context(
        self,
        context_id: str,
        version_tag: Optional[str] = None,
    ) -> dict[str, Any]:
        """Get a context by ID, returning the latest version by default.

        Args:
            context_id: UUID of the context to retrieve.
            version_tag: Specific version tag to retrieve. If None, returns latest.

        Returns:
            A dict representing the ContextVersion.

        Raises:
            ContexaConnectionError: If the daemon is not running.
            ContexaNotFoundError: If the context_id or version_tag does not exist.
        """
        if version_tag:
            return self._get(f"/contexts/{context_id}/versions/{version_tag}")
        return self._get(f"/contexts/{context_id}")

    def update_context(
        self,
        context_id: str,
        content: dict[str, Any],
    ) -> dict[str, Any]:
        """Write a new version of an existing context.

        Each call creates a new immutable version — the previous version
        is preserved and remains retrievable by its version_tag.

        Args:
            context_id: UUID of the context to update.
            content: New content payload.

        Returns:
            A dict representing the newly created ContextVersion.

        Raises:
            ContexaConnectionError: If the daemon is not running.
            ContexaNotFoundError: If the context_id does not exist.
        """
        return self._put(f"/contexts/{context_id}", {"content": content})

    def list_contexts(self) -> list[dict[str, Any]]:
        """List all contexts with their latest version summary.

        Returns:
            A list of dicts, each with keys: context_id, latest_version_tag,
            checksum, created_at, label.

        Raises:
            ContexaConnectionError: If the daemon is not running.
        """
        return self._get("/contexts")

    def delete_context(self, context_id: str) -> None:
        """Delete a context and all its versions.

        Args:
            context_id: UUID of the context to delete.

        Raises:
            ContexaConnectionError: If the daemon is not running.
            ContexaNotFoundError: If the context_id does not exist.
        """
        self._delete(f"/contexts/{context_id}")

    def update_label(
        self,
        context_id: str,
        label: Optional[str],
    ) -> dict[str, Any]:
        """Update the label on a context without creating a new version.

        Labels are mutable metadata — updating them does not affect
        versioning, sync, or conflict detection.

        Args:
            context_id: UUID of the context to relabel.
            label: New label string, or None to clear the label.

        Returns:
            A dict representing the updated ContextSummary.

        Raises:
            ContexaConnectionError: If the daemon is not running.
            ContexaNotFoundError: If the context_id does not exist.
        """
        return self._patch(f"/contexts/{context_id}/label", {"label": label})

    # ------------------------------------------------------------------
    # Semantic search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        top_n: int = 10,
    ) -> list[dict[str, Any]]:
        """Perform semantic similarity search over stored contexts.

        Requires an embedding model to be configured in config.toml:
            [embeddings]
            model = "all-MiniLM-L6-v2"

        Args:
            query: Natural language query string.
            top_n: Maximum number of results to return (1–100).

        Returns:
            A list of ContextVersion dicts ordered by descending similarity score.

        Raises:
            ContexaConnectionError: If the daemon is not running.
            ContexaError: If no embedding model is configured (HTTP 503).
        """
        return self._get(f"/contexts/search?q={query}&top_n={top_n}")

    # ------------------------------------------------------------------
    # Sync operations
    # ------------------------------------------------------------------

    def trigger_sync(self) -> dict[str, Any]:
        """Trigger a manual sync cycle.

        Returns immediately — the sync runs asynchronously in the daemon.

        Returns:
            A dict with status and message fields.

        Raises:
            ContexaConnectionError: If the daemon is not running.
        """
        return self._post("/sync/trigger", {})

    def get_sync_log(
        self,
        device_id: Optional[str] = None,
        context_id: Optional[str] = None,
        status: Optional[str] = None,
        since: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Query the sync log with optional filters.

        Args:
            device_id: Filter by peer device UUID.
            context_id: Filter by context UUID.
            status: Filter by status ('success', 'conflict', 'failed', 'pending').
            since: Filter entries after this ISO-8601 datetime string.

        Returns:
            A list of sync log entry dicts ordered by descending timestamp.

        Raises:
            ContexaConnectionError: If the daemon is not running.
        """
        params = []
        if device_id:
            params.append(f"device_id={device_id}")
        if context_id:
            params.append(f"context_id={context_id}")
        if status:
            params.append(f"status={status}")
        if since:
            params.append(f"since={since}")

        path = "/sync/log"
        if params:
            path += "?" + "&".join(params)
        return self._get(path)

    # ------------------------------------------------------------------
    # Health / config
    # ------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        """Return the daemon health status.

        Returns:
            A dict with status, context_store, sync_engine, trust_store fields.

        Raises:
            ContexaConnectionError: If the daemon is not running.
        """
        return self._get("/health")

    def get_config(self) -> dict[str, Any]:
        """Return the resolved daemon configuration including defaults.

        Returns:
            A dict of all configuration values.

        Raises:
            ContexaConnectionError: If the daemon is not running.
        """
        return self._get("/config")
