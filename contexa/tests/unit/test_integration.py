"""
Integration tests: full CLI → Local_API → Context_Store path.

These tests wire up a real in-process daemon (no network) and exercise
the complete stack from CLI command → httpx → FastAPI → ContextStore → SQLite.
Requirements: 5.2, 4.1, 2.1
"""

from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from typer.testing import CliRunner

from contexa.api.app import create_app
from contexa.cli.main import app as cli_app
from contexa.config import ContexaConfig
from contexa.store.context_store import ContextStore
from contexa.store.database import Base
from contexa.store.embedding_store import EmbeddingStore
from contexa.store.trust_store import TrustStore
from contexa.sync.crypto import generate_device_identity
from contexa.sync.engine import SyncEngine

runner = CliRunner()


# ---------------------------------------------------------------------------
# Shared fixture: in-process daemon with TestClient
# ---------------------------------------------------------------------------

@pytest.fixture
def live_app(tmp_path):
    """A fully wired FastAPI app with in-memory SQLite."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()

    identity = generate_device_identity()
    context_store = ContextStore(session)
    trust_store = TrustStore(session, data_dir=tmp_path)
    trust_store._identity = identity
    sync_engine = SyncEngine(
        session=session,
        context_store=context_store,
        trust_store=trust_store,
        identity=identity,
    )

    app = create_app()
    app.state.context_store = context_store
    app.state.trust_store = trust_store
    app.state.embedding_store = EmbeddingStore(session, model_name="")
    app.state.sync_engine = sync_engine
    app.state.config = ContexaConfig()
    app.state.device_id = identity.device_id
    app.state.start_time = time.time()
    app.state.syncs_completed = 0
    app.state.sync_failures = 0

    return app


# ---------------------------------------------------------------------------
# Helper: mock the CLI's HTTP calls to go through TestClient
# ---------------------------------------------------------------------------

def make_cli_caller(live_app):
    """Return a function that patches CLI HTTP calls to use TestClient."""
    http_client = TestClient(live_app, raise_server_exceptions=False)

    def mock_get(path):
        r = http_client.get(path)
        if r.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError(
                str(r.status_code), request=None, response=r
            )
        return r.json()

    def mock_post(path, json):
        r = http_client.post(path, json=json)
        if r.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError(
                str(r.status_code), request=None, response=r
            )
        return r.json()

    def mock_put(path, json):
        r = http_client.put(path, json=json)
        if r.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError(
                str(r.status_code), request=None, response=r
            )
        return r.json()

    def mock_patch(path, json):
        r = http_client.patch(path, json=json)
        if r.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError(
                str(r.status_code), request=None, response=r
            )
        return r.json()

    def mock_delete(path):
        r = http_client.delete(path)
        if r.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError(
                str(r.status_code), request=None, response=r
            )

    return mock_get, mock_post, mock_put, mock_patch, mock_delete


# ---------------------------------------------------------------------------
# Integration: create → get → list → delete round-trip
# ---------------------------------------------------------------------------

def test_context_create_get_list_delete_roundtrip(live_app):
    """Full CLI round-trip: create → get → list → delete."""
    mock_get, mock_post, mock_put, mock_patch, mock_delete = make_cli_caller(live_app)

    with patch("contexa.cli.commands.context.api_get", side_effect=mock_get), \
         patch("contexa.cli.commands.context.api_post", side_effect=mock_post), \
         patch("contexa.cli.commands.context.api_delete", side_effect=mock_delete):

        # Create
        result = runner.invoke(cli_app, [
            "context", "create", "--json", '{"task": "integration test"}'
        ])
        assert result.exit_code == 0, result.output
        assert "Created context" in result.output

        # Extract context_id from output
        context_id = result.output.split("Created context ")[1].split(" ")[0].strip()

        # List — should show the context
        result = runner.invoke(cli_app, ["context", "list"])
        assert result.exit_code == 0
        assert context_id in result.output

        # Get — should return the context
        result = runner.invoke(cli_app, ["context", "get", context_id])
        assert result.exit_code == 0
        assert context_id in result.output
        assert "integration test" in result.output

        # Get with --json flag
        result = runner.invoke(cli_app, ["context", "get", context_id, "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["context_id"] == context_id
        assert data["content"]["task"] == "integration test"

        # Delete
        result = runner.invoke(cli_app, ["context", "delete", context_id, "--yes"])
        assert result.exit_code == 0
        assert "Deleted" in result.output

        # List — should be empty now
        result = runner.invoke(cli_app, ["context", "list"])
        assert result.exit_code == 0
        assert "No contexts found" in result.output


def test_context_create_with_label_roundtrip(live_app):
    """Create with label, verify label appears in list and get."""
    mock_get, mock_post, _, mock_patch, mock_delete = make_cli_caller(live_app)

    with patch("contexa.cli.commands.context.api_get", side_effect=mock_get), \
         patch("contexa.cli.commands.context.api_post", side_effect=mock_post), \
         patch("contexa.cli.commands.context.api_patch", side_effect=mock_patch), \
         patch("contexa.cli.commands.context.api_delete", side_effect=mock_delete):

        result = runner.invoke(cli_app, [
            "context", "create",
            "--json", '{"x": 1}',
            "--label", "my-integration-test",
        ])
        assert result.exit_code == 0
        assert "my-integration-test" in result.output

        # List should show the label
        result = runner.invoke(cli_app, ["context", "list"])
        assert result.exit_code == 0
        assert "my-integration-test" in result.output


def test_context_update_creates_new_version(live_app):
    """Update a context via API and verify a new version is created."""
    http_client = TestClient(live_app, raise_server_exceptions=False)

    # Create
    r = http_client.post("/contexts", json={"content": {"v": 1}})
    assert r.status_code == 201
    v1 = r.json()

    # Update
    r = http_client.put(f"/contexts/{v1['context_id']}", json={"content": {"v": 2}})
    assert r.status_code == 200
    v2 = r.json()

    assert v2["version_tag"] != v1["version_tag"]
    assert v2["parent_version"] == v1["version_id"]
    assert v2["content"]["v"] == 2

    # Old version still accessible
    r = http_client.get(f"/contexts/{v1['context_id']}/versions/{v1['version_tag']}")
    assert r.status_code == 200
    assert r.json()["content"]["v"] == 1


def test_health_and_metrics_after_operations(live_app):
    """Health and metrics endpoints reflect actual state."""
    http_client = TestClient(live_app, raise_server_exceptions=False)

    # Create some contexts
    http_client.post("/contexts", json={"content": {"a": 1}})
    http_client.post("/contexts", json={"content": {"b": 2}})

    r = http_client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    r = http_client.get("/metrics")
    assert r.status_code == 200
    assert r.json()["contexts_stored"] == 2


def test_config_endpoint_returns_defaults(live_app):
    """Config endpoint returns the resolved configuration."""
    http_client = TestClient(live_app, raise_server_exceptions=False)
    r = http_client.get("/config")
    assert r.status_code == 200
    cfg = r.json()
    assert cfg["daemon_port"] == 7474
    assert cfg["sync_mode"] == "hosted"
