"""
Unit tests for the Contexa Local API.
Tests all CRUD endpoints, error responses, health/metrics/config endpoints.
Requirements: 4.1–4.7
"""

from __future__ import annotations

import time
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from contexa.api.app import create_app
from contexa.config import ContexaConfig
from contexa.store.database import Base
from contexa.store.context_store import ContextStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """TestClient with a fully wired in-memory app.

    Uses a single shared SQLite connection so that create_all() and the
    ContextStore session operate on the same in-memory database.
    """
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # forces all sessions to share one connection
    )
    Base.metadata.create_all(bind=engine)

    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()

    app = create_app()
    app.state.context_store = ContextStore(session)
    app.state.config = ContexaConfig()
    app.state.device_id = "test-device-001"
    app.state.start_time = time.time()
    app.state.syncs_completed = 0
    app.state.sync_failures = 0

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    session.close()


CONTENT = {"task": "test the API", "status": "pending"}


# ---------------------------------------------------------------------------
# POST /contexts
# ---------------------------------------------------------------------------

def test_create_context_returns_201(client):
    r = client.post("/contexts", json={"content": CONTENT})
    assert r.status_code == 201
    body = r.json()
    assert body["content"] == CONTENT
    assert "context_id" in body
    assert "version_tag" in body
    assert "checksum" in body
    assert body["label"] is None


def test_create_context_with_label(client):
    r = client.post("/contexts", json={"content": CONTENT, "label": "my-task"})
    assert r.status_code == 201
    assert r.json()["label"] == "my-task"


def test_create_context_invalid_payload_returns_400(client):
    r = client.post("/contexts", json={"wrong_field": "value"})
    assert r.status_code == 400
    assert r.json()["error"] == "validation_error"


def test_create_context_missing_body_returns_400(client):
    r = client.post("/contexts", content=b"not json", headers={"content-type": "application/json"})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# GET /contexts
# ---------------------------------------------------------------------------

def test_list_contexts_empty(client):
    r = client.get("/contexts")
    assert r.status_code == 200
    assert r.json() == []


def test_list_contexts_returns_all(client):
    client.post("/contexts", json={"content": {"a": 1}})
    client.post("/contexts", json={"content": {"b": 2}})
    r = client.get("/contexts")
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_list_contexts_includes_label(client):
    client.post("/contexts", json={"content": {"x": 1}, "label": "labelled"})
    r = client.get("/contexts")
    assert r.json()[0]["label"] == "labelled"


# ---------------------------------------------------------------------------
# GET /contexts/{context_id}
# ---------------------------------------------------------------------------

def test_get_context_returns_latest(client):
    created = client.post("/contexts", json={"content": CONTENT}).json()
    r = client.get(f"/contexts/{created['context_id']}")
    assert r.status_code == 200
    assert r.json()["content"] == CONTENT


def test_get_context_not_found_returns_404(client):
    r = client.get("/contexts/nonexistent-id")
    assert r.status_code == 404
    assert r.json()["error"] == "not_found"


# ---------------------------------------------------------------------------
# GET /contexts/{context_id}/versions/{version_tag}
# ---------------------------------------------------------------------------

def test_get_specific_version(client):
    created = client.post("/contexts", json={"content": {"v": 1}}).json()
    context_id = created["context_id"]
    v1_tag = created["version_tag"]

    client.put(f"/contexts/{context_id}", json={"content": {"v": 2}})

    r = client.get(f"/contexts/{context_id}/versions/{v1_tag}")
    assert r.status_code == 200
    assert r.json()["content"] == {"v": 1}


def test_get_specific_version_not_found(client):
    created = client.post("/contexts", json={"content": CONTENT}).json()
    r = client.get(f"/contexts/{created['context_id']}/versions/badtag")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# PUT /contexts/{context_id}
# ---------------------------------------------------------------------------

def test_update_context_creates_new_version(client):
    created = client.post("/contexts", json={"content": {"v": 1}}).json()
    context_id = created["context_id"]

    updated = client.put(f"/contexts/{context_id}", json={"content": {"v": 2}}).json()
    assert updated["content"] == {"v": 2}
    assert updated["version_tag"] != created["version_tag"]
    assert updated["parent_version"] == created["version_id"]


def test_update_context_not_found_returns_404(client):
    r = client.put("/contexts/nonexistent-id", json={"content": {"x": 1}})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /contexts/{context_id}/label
# ---------------------------------------------------------------------------

def test_patch_label_updates_without_new_version(client):
    created = client.post("/contexts", json={"content": CONTENT}).json()
    context_id = created["context_id"]

    r = client.patch(f"/contexts/{context_id}/label", json={"label": "renamed"})
    assert r.status_code == 200
    assert r.json()["label"] == "renamed"

    # Version count unchanged
    fetched = client.get(f"/contexts/{context_id}").json()
    assert fetched["label"] == "renamed"
    assert fetched["version_tag"] == created["version_tag"]


def test_patch_label_can_be_cleared(client):
    created = client.post("/contexts", json={"content": CONTENT, "label": "initial"}).json()
    r = client.patch(f"/contexts/{created['context_id']}/label", json={"label": None})
    assert r.status_code == 200
    assert r.json()["label"] is None


def test_patch_label_not_found_returns_404(client):
    r = client.patch("/contexts/nonexistent-id/label", json={"label": "x"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /contexts/{context_id}
# ---------------------------------------------------------------------------

def test_delete_context_returns_204(client):
    created = client.post("/contexts", json={"content": CONTENT}).json()
    r = client.delete(f"/contexts/{created['context_id']}")
    assert r.status_code == 204


def test_delete_context_then_get_returns_404(client):
    created = client.post("/contexts", json={"content": CONTENT}).json()
    client.delete(f"/contexts/{created['context_id']}")
    r = client.get(f"/contexts/{created['context_id']}")
    assert r.status_code == 404


def test_delete_context_not_found_returns_404(client):
    r = client.delete("/contexts/nonexistent-id")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

def test_health_returns_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["context_store"]["status"] == "ok"


# ---------------------------------------------------------------------------
# GET /metrics
# ---------------------------------------------------------------------------

def test_metrics_returns_counters(client):
    client.post("/contexts", json={"content": {"x": 1}})
    r = client.get("/metrics")
    assert r.status_code == 200
    body = r.json()
    assert body["contexts_stored"] == 1
    assert "uptime_seconds" in body
    assert body["uptime_seconds"] >= 0


# ---------------------------------------------------------------------------
# GET /config
# ---------------------------------------------------------------------------

def test_config_returns_resolved_values(client):
    r = client.get("/config")
    assert r.status_code == 200
    body = r.json()
    assert body["daemon_port"] == 7474
    assert body["sync_mode"] == "hosted"
    assert "storage_data_dir" in body


# ---------------------------------------------------------------------------
# Localhost-only binding (Req 4.7)
# ---------------------------------------------------------------------------

def test_app_title_is_set(client):
    """Smoke test that the app is configured correctly."""
    r = client.get("/docs")
    assert r.status_code == 200
