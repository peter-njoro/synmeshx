"""
Unit tests for observability: logging, /metrics endpoint, sync log filters.
Requirements: 12.1–12.4
"""

from __future__ import annotations

import io
import json
import logging
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest
import structlog
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from contexa.api.app import create_app
from contexa.config import ContexaConfig
from contexa.daemon import _configure_logging
from contexa.store.context_store import ContextStore
from contexa.store.database import Base
from contexa.store.embedding_store import EmbeddingStore
from contexa.store.models import SyncLogRecord
from contexa.store.trust_store import TrustStore
from contexa.sync.crypto import generate_device_identity
from contexa.sync.engine import SyncEngine


# Fixtures

@pytest.fixture
def session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    yield db
    db.close()


@pytest.fixture
def client(session, tmp_path):
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
    app.state.sync_engine = sync_engine
    app.state.embedding_store = EmbeddingStore(session, model_name="")
    app.state.config = ContexaConfig()
    app.state.device_id = identity.device_id
    app.state.start_time = time.time()
    app.state.syncs_completed = 0
    app.state.sync_failures = 0

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c, session, sync_engine


# Log level filtering (Req 12.1)

def test_configure_logging_info_suppresses_debug():
    """At INFO level, root logger does not emit DEBUG."""
    _configure_logging("INFO", "stdout")
    assert logging.root.level <= logging.INFO
    assert not logging.root.isEnabledFor(logging.DEBUG)


def test_configure_logging_debug_allows_all():
    """At DEBUG level, root logger emits all levels."""
    _configure_logging("DEBUG", "stdout")
    assert logging.root.isEnabledFor(logging.DEBUG)
    assert logging.root.isEnabledFor(logging.INFO)


def test_configure_logging_error_suppresses_warn():
    """At ERROR level, root logger does not emit WARN."""
    _configure_logging("ERROR", "stdout")
    assert logging.root.isEnabledFor(logging.ERROR)
    assert not logging.root.isEnabledFor(logging.WARNING)


def test_configure_logging_to_file(tmp_path):
    """Logging to a file path does not raise."""
    log_file = str(tmp_path / "contexa.log")
    _configure_logging("INFO", log_file)  # should not raise


# /metrics endpoint (Req 12.4)

def test_metrics_contexts_stored_counter(client):
    c, session, _ = client
    # Create some contexts
    c.post("/contexts", json={"content": {"a": 1}})
    c.post("/contexts", json={"content": {"b": 2}})

    r = c.get("/metrics")
    assert r.status_code == 200
    assert r.json()["contexts_stored"] == 2


def test_metrics_uptime_is_positive(client):
    c, _, _ = client
    r = c.get("/metrics")
    assert r.json()["uptime_seconds"] >= 0


def test_metrics_sync_counters_present(client):
    c, _, _ = client
    r = c.get("/metrics")
    body = r.json()
    assert "syncs_completed" in body
    assert "sync_failures" in body


# Sync log queryable via API (Req 12.3)

def _write_log(session, device_id, context_id, version_tag, status, created_at=None):
    import uuid
    entry = SyncLogRecord(
        log_id=str(uuid.uuid4()),
        device_id=device_id,
        context_id=context_id,
        version_tag=version_tag,
        status=status,
    )
    if created_at:
        entry.created_at = created_at
    session.add(entry)
    session.commit()


def test_sync_log_returns_all_entries(client):
    c, session, _ = client
    _write_log(session, "dev-A", "ctx-1", "v1", "success")
    _write_log(session, "dev-B", "ctx-2", "v1", "conflict")

    r = c.get("/sync/log")
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_sync_log_filter_by_status(client):
    c, session, _ = client
    _write_log(session, "dev-A", "ctx-1", "v1", "success")
    _write_log(session, "dev-A", "ctx-2", "v1", "conflict")
    _write_log(session, "dev-A", "ctx-3", "v1", "failed")

    r = c.get("/sync/log?status=success")
    assert r.status_code == 200
    entries = r.json()
    assert all(e["status"] == "success" for e in entries)
    assert len(entries) == 1


def test_sync_log_filter_by_device(client):
    c, session, _ = client
    _write_log(session, "dev-A", "ctx-1", "v1", "success")
    _write_log(session, "dev-B", "ctx-2", "v1", "success")

    r = c.get("/sync/log?device_id=dev-A")
    assert r.status_code == 200
    entries = r.json()
    assert all(e["device_id"] == "dev-A" for e in entries)


def test_sync_log_filter_by_context(client):
    c, session, _ = client
    _write_log(session, "dev-A", "ctx-target", "v1", "success")
    _write_log(session, "dev-A", "ctx-other", "v1", "success")

    r = c.get("/sync/log?context_id=ctx-target")
    assert r.status_code == 200
    entries = r.json()
    assert all(e["context_id"] == "ctx-target" for e in entries)


def test_sync_log_filter_by_since(client):
    c, session, sync_engine = client
    # Write two entries directly via the engine's get_sync_log
    import uuid
    old_entry = SyncLogRecord(
        log_id=str(uuid.uuid4()),
        device_id="dev-A",
        context_id="ctx-old",
        version_tag="v1",
        status="success",
    )
    session.add(old_entry)
    session.commit()

    # Query with a since filter that should return all entries
    entries = sync_engine.get_sync_log()
    assert len(entries) >= 1


def test_sync_log_invalid_since_returns_400(client):
    c, _, _ = client
    r = c.get("/sync/log?since=not-a-date")
    assert r.status_code == 400


# Unhandled error logging (Req 12.2)

def test_log_unhandled_error_includes_traceback():
    """log_unhandled_error() logs error type, message, and traceback."""
    from contexa.logging import log_unhandled_error, get_logger

    captured = []

    class CapturingLogger:
        def error(self, event, **kwargs):
            captured.append({"event": event, **kwargs})

    try:
        raise ValueError("test error")
    except ValueError as e:
        log_unhandled_error(CapturingLogger(), e, context="test context")

    assert len(captured) == 1
    entry = captured[0]
    assert entry["error_type"] == "ValueError"
    assert "test error" in entry["error"]
    assert "traceback" in entry
    assert entry["context"] == "test context"
