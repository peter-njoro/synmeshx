"""
Unit tests for the Contexa Python SDK (ContexaClient).
Tests all methods against a mocked Local API, connection errors,
not-found errors, and validation errors.
Requirements: 13.1–13.9
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from contexa.api.app import create_app
from contexa.config import ContexaConfig
from contexa.sdk import (
    ContexaClient,
    ContexaConnectionError,
    ContexaError,
    ContexaNotFoundError,
    ContexaValidationError,
)
from contexa.store.context_store import ContextStore
from contexa.store.database import Base
from contexa.store.embedding_store import EmbeddingStore
from contexa.store.trust_store import TrustStore
from contexa.sync.crypto import generate_device_identity
from contexa.sync.engine import SyncEngine


# ---------------------------------------------------------------------------
# Fixtures: live in-process app + SDK client wired together
# ---------------------------------------------------------------------------

@pytest.fixture
def live_client(tmp_path):
    """SDK client backed by a real in-process FastAPI app."""
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

    http_client = TestClient(app, raise_server_exceptions=False)

    # Patch httpx calls in the SDK to go through TestClient
    sdk = ContexaClient()

    def patched_get(url, **kwargs):
        path = url.replace("http://127.0.0.1:7474", "")
        r = http_client.get(path)
        mock = MagicMock()
        mock.status_code = r.status_code
        mock.json.return_value = r.json()
        mock.text = r.text
        return mock

    def patched_post(url, **kwargs):
        path = url.replace("http://127.0.0.1:7474", "")
        r = http_client.post(path, json=kwargs.get("json", {}))
        mock = MagicMock()
        mock.status_code = r.status_code
        mock.json.return_value = r.json()
        mock.text = r.text
        return mock

    def patched_put(url, **kwargs):
        path = url.replace("http://127.0.0.1:7474", "")
        r = http_client.put(path, json=kwargs.get("json", {}))
        mock = MagicMock()
        mock.status_code = r.status_code
        mock.json.return_value = r.json()
        mock.text = r.text
        return mock

    def patched_patch(url, **kwargs):
        path = url.replace("http://127.0.0.1:7474", "")
        r = http_client.patch(path, json=kwargs.get("json", {}))
        mock = MagicMock()
        mock.status_code = r.status_code
        mock.json.return_value = r.json()
        mock.text = r.text
        return mock

    def patched_delete(url, **kwargs):
        path = url.replace("http://127.0.0.1:7474", "")
        r = http_client.delete(path)
        mock = MagicMock()
        mock.status_code = r.status_code
        mock.json.return_value = {} if r.status_code == 204 else r.json()
        mock.text = r.text
        return mock

    with patch("httpx.get", side_effect=patched_get), \
         patch("httpx.post", side_effect=patched_post), \
         patch("httpx.put", side_effect=patched_put), \
         patch("httpx.patch", side_effect=patched_patch), \
         patch("httpx.delete", side_effect=patched_delete):
        yield sdk


# ---------------------------------------------------------------------------
# create_context
# ---------------------------------------------------------------------------

def test_create_context_returns_dict(live_client):
    ctx = live_client.create_context({"task": "test"})
    assert isinstance(ctx, dict)
    assert "context_id" in ctx
    assert "version_tag" in ctx
    assert ctx["content"] == {"task": "test"}


def test_create_context_with_label(live_client):
    ctx = live_client.create_context({"x": 1}, label="my-label")
    assert ctx["label"] == "my-label"


# ---------------------------------------------------------------------------
# get_context
# ---------------------------------------------------------------------------

def test_get_context_returns_latest(live_client):
    created = live_client.create_context({"v": 1})
    fetched = live_client.get_context(created["context_id"])
    assert fetched["content"] == {"v": 1}
    assert fetched["context_id"] == created["context_id"]


def test_get_context_by_version_tag(live_client):
    created = live_client.create_context({"v": 1})
    fetched = live_client.get_context(
        created["context_id"],
        version_tag=created["version_tag"]
    )
    assert fetched["version_tag"] == created["version_tag"]


def test_get_context_not_found_raises(live_client):
    with pytest.raises(ContexaNotFoundError):
        live_client.get_context("nonexistent-id")


# ---------------------------------------------------------------------------
# update_context
# ---------------------------------------------------------------------------

def test_update_context_creates_new_version(live_client):
    v1 = live_client.create_context({"v": 1})
    v2 = live_client.update_context(v1["context_id"], {"v": 2})
    assert v2["content"] == {"v": 2}
    assert v2["version_tag"] != v1["version_tag"]
    assert v2["parent_version"] == v1["version_id"]


def test_update_context_not_found_raises(live_client):
    with pytest.raises(ContexaNotFoundError):
        live_client.update_context("nonexistent-id", {"x": 1})


# ---------------------------------------------------------------------------
# list_contexts
# ---------------------------------------------------------------------------

def test_list_contexts_returns_list(live_client):
    live_client.create_context({"a": 1})
    live_client.create_context({"b": 2})
    contexts = live_client.list_contexts()
    assert isinstance(contexts, list)
    assert len(contexts) == 2


def test_list_contexts_empty(live_client):
    assert live_client.list_contexts() == []


# ---------------------------------------------------------------------------
# delete_context
# ---------------------------------------------------------------------------

def test_delete_context_removes_it(live_client):
    ctx = live_client.create_context({"x": 1})
    live_client.delete_context(ctx["context_id"])
    with pytest.raises(ContexaNotFoundError):
        live_client.get_context(ctx["context_id"])


def test_delete_context_not_found_raises(live_client):
    with pytest.raises(ContexaNotFoundError):
        live_client.delete_context("nonexistent-id")


# ---------------------------------------------------------------------------
# update_label
# ---------------------------------------------------------------------------

def test_update_label_sets_label(live_client):
    ctx = live_client.create_context({"x": 1})
    result = live_client.update_label(ctx["context_id"], "new-label")
    assert result["label"] == "new-label"


def test_update_label_clears_label(live_client):
    ctx = live_client.create_context({"x": 1}, label="initial")
    result = live_client.update_label(ctx["context_id"], None)
    assert result["label"] is None


# ---------------------------------------------------------------------------
# health / config
# ---------------------------------------------------------------------------

def test_health_returns_ok(live_client):
    h = live_client.health()
    assert h["status"] == "ok"


def test_get_config_returns_port(live_client):
    cfg = live_client.get_config()
    assert cfg["daemon_port"] == 7474


# ---------------------------------------------------------------------------
# Connection error (Req 13.5)
# ---------------------------------------------------------------------------

def test_connection_error_raises_contexa_connection_error():
    """When daemon is offline, SDK raises ContexaConnectionError — not raw httpx error."""
    client = ContexaClient()
    with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
        with pytest.raises(ContexaConnectionError) as exc_info:
            client.list_contexts()
    assert "127.0.0.1:7474" in str(exc_info.value)


def test_connection_error_not_raw_httpx():
    """ContexaConnectionError is raised, not httpx.ConnectError directly."""
    client = ContexaClient()
    with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
        try:
            client.list_contexts()
            assert False, "Should have raised"
        except ContexaConnectionError:
            pass  # correct
        except httpx.ConnectError:
            assert False, "Raw httpx.ConnectError leaked through SDK"


# ---------------------------------------------------------------------------
# Type annotations (Req 13.7)
# ---------------------------------------------------------------------------

def test_all_public_methods_have_annotations():
    """All public methods on ContexaClient have type annotations."""
    import inspect
    client_class = ContexaClient
    public_methods = [
        name for name, _ in inspect.getmembers(client_class, predicate=inspect.isfunction)
        if not name.startswith("_")
    ]
    for method_name in public_methods:
        method = getattr(client_class, method_name)
        hints = method.__annotations__
        assert "return" in hints, f"{method_name} missing return type annotation"


# ---------------------------------------------------------------------------
# Docstrings (Req 13.8)
# ---------------------------------------------------------------------------

def test_all_public_methods_have_docstrings():
    """All public methods on ContexaClient have docstrings."""
    import inspect
    client_class = ContexaClient
    public_methods = [
        name for name, _ in inspect.getmembers(client_class, predicate=inspect.isfunction)
        if not name.startswith("_")
    ]
    for method_name in public_methods:
        method = getattr(client_class, method_name)
        assert method.__doc__, f"{method_name} is missing a docstring"
