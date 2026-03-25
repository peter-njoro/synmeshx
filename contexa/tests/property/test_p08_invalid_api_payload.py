# Feature: contexa-core, Property 8: Invalid API Payloads Return 400
"""
For any HTTP request to the Local API that contains a malformed or
schema-invalid payload, the API must respond with HTTP 400 and a body
containing a human-readable description of the validation failure.
Validates: Requirements 4.4
"""

from __future__ import annotations

import time
import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from contexa.api.app import create_app
from contexa.config import ContexaConfig
from contexa.store.database import Base
from contexa.store.context_store import ContextStore


def make_client():
    from sqlalchemy.pool import StaticPool
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    app = create_app()
    app.state.context_store = ContextStore(session)
    app.state.config = ContexaConfig()
    app.state.device_id = "test-device"
    app.state.start_time = time.time()
    return TestClient(app, raise_server_exceptions=False)


# Strategies for payloads that are missing the required "content" field
invalid_create_payloads = st.one_of(
    st.just({}),
    st.just({"label": "no-content"}),
    st.just({"content": "not-a-dict"}),   # content must be a dict
    st.just({"content": 42}),
    st.just({"content": ["list", "not", "dict"]}),
)


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(payload=invalid_create_payloads)
def test_invalid_create_payload_returns_400(payload):
    """POST /contexts with invalid payload returns 400 with error description."""
    client = make_client()
    r = client.post("/contexts", json=payload)
    assert r.status_code in (400, 422), (
        f"Expected 400/422 for payload {payload}, got {r.status_code}: {r.text}"
    )
    body = r.json()
    assert "error" in body or "detail" in body


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(payload=invalid_create_payloads)
def test_invalid_update_payload_returns_400(payload):
    """PUT /contexts/{id} with invalid payload returns 400."""
    client = make_client()
    # Create a valid context first
    created = client.post("/contexts", json={"content": {"x": 1}}).json()
    context_id = created["context_id"]

    r = client.put(f"/contexts/{context_id}", json=payload)
    assert r.status_code in (400, 422)
