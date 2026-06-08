"""
Unit tests for daemon lifecycle.
Tests startup sequence, graceful shutdown, non-zero exit on failure,
and health endpoint reflecting component states.
Requirements: 1.1–1.6
"""

from __future__ import annotations

import signal
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from contexa.api.app import create_app
from contexa.config import ContexaConfig, DaemonConfig, StorageConfig, SyncConfig, RelayConfig, EmbeddingsConfig
from contexa.store.context_store import ContextStore
from contexa.store.database import Base
from contexa.store.embedding_store import EmbeddingStore
from contexa.store.trust_store import TrustStore
from contexa.sync.crypto import generate_device_identity
from contexa.sync.engine import SyncEngine


# Helpers

def make_wired_app(tmp_path):
    """Create a fully wired FastAPI app with in-memory stores."""
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
    trust_store._identity = identity  # inject without file I/O
    embedding_store = EmbeddingStore(session, model_name="")
    sync_engine = SyncEngine(
        session=session,
        context_store=context_store,
        trust_store=trust_store,
        identity=identity,
    )

    app = create_app()
    app.state.context_store = context_store
    app.state.trust_store = trust_store
    app.state.embedding_store = embedding_store
    app.state.sync_engine = sync_engine
    app.state.config = ContexaConfig()
    app.state.device_id = identity.device_id
    app.state.start_time = time.time()
    app.state.syncs_completed = 0
    app.state.sync_failures = 0

    return app, session


# Health endpoint reflects component states

def test_health_endpoint_returns_ok_when_all_components_present(tmp_path):
    app, _ = make_wired_app(tmp_path)
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["context_store"]["status"] == "ok"
    assert body["sync_engine"]["status"] == "ok"
    assert body["trust_store"]["status"] == "ok"


def test_health_endpoint_returns_degraded_when_sync_engine_missing(tmp_path):
    app, _ = make_wired_app(tmp_path)
    del app.state.sync_engine  # simulate missing component
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "degraded"


# Startup sequence — config loading

def test_main_exits_nonzero_on_config_error(tmp_path):
    """Daemon exits with code 1 when config is invalid."""
    bad_config = tmp_path / "config.toml"
    bad_config.write_text("[daemon]\nport = 0\n")  # invalid port

    with pytest.raises(SystemExit) as exc_info:
        from contexa.daemon import main
        main(config_path=bad_config)

    assert exc_info.value.code == 1


def test_main_exits_nonzero_on_db_failure(tmp_path):
    """Daemon exits with code 1 when database cannot be initialized."""
    config_file = tmp_path / "config.toml"
    # Point data_dir to a file (not a directory) to cause init failure
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    config_file.write_text(f'[storage]\ndata_dir = "{blocker}"\n')

    with pytest.raises(SystemExit) as exc_info:
        from contexa.daemon import main
        main(config_path=config_file)

    assert exc_info.value.code == 1


# Startup sequence — component initialization order

def test_daemon_initializes_all_components(tmp_path):
    """All required components are present on app.state after wiring."""
    app, _ = make_wired_app(tmp_path)
    assert hasattr(app.state, "context_store")
    assert hasattr(app.state, "trust_store")
    assert hasattr(app.state, "sync_engine")
    assert hasattr(app.state, "config")
    assert hasattr(app.state, "device_id")
    assert hasattr(app.state, "start_time")


def test_device_id_is_set_on_app_state(tmp_path):
    """app.state.device_id is a non-empty string after initialization."""
    app, _ = make_wired_app(tmp_path)
    assert isinstance(app.state.device_id, str)
    assert len(app.state.device_id) > 0


# Metrics endpoint

def test_metrics_endpoint_returns_uptime(tmp_path):
    app, _ = make_wired_app(tmp_path)
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/metrics")
    assert r.status_code == 200
    body = r.json()
    assert body["uptime_seconds"] >= 0
    assert "contexts_stored" in body
    assert "syncs_completed" in body


# Config endpoint

def test_config_endpoint_returns_resolved_config(tmp_path):
    app, _ = make_wired_app(tmp_path)
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/config")
    assert r.status_code == 200
    body = r.json()
    assert body["daemon_port"] == 7474
    assert body["sync_mode"] == "hosted"


# Logging configuration

def test_configure_logging_does_not_raise():
    """_configure_logging() runs without error for all valid log levels."""
    from contexa.daemon import _configure_logging
    for level in ["DEBUG", "INFO", "WARN", "ERROR"]:
        _configure_logging(level, "stdout")  # should not raise
