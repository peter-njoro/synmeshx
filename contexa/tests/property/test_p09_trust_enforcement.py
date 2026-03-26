# Feature: contexa-core, Property 9: Trust Enforcement
"""
For any Device_ID not present in the Trust_Store (including revoked devices),
the Sync_Engine must reject all sync requests from that device.
Here we test the Trust_Store's is_trusted() gate directly.
Validates: Requirements 6.4, 6.5
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from contexa.store.database import Base
from contexa.store.trust_store import TrustStore
from contexa.sync.crypto import generate_device_identity


def make_trust_store(tmp_path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    return TrustStore(session, data_dir=tmp_path)


random_uuids = st.uuids().map(str)


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(device_id=random_uuids)
def test_unknown_device_is_not_trusted(tmp_path, device_id):
    """Any device_id not explicitly added is rejected by is_trusted()."""
    store = make_trust_store(tmp_path)
    assert not store.is_trusted(device_id)


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(device_id=random_uuids)
def test_revoked_device_is_not_trusted(tmp_path, device_id):
    """A device that was trusted and then revoked is rejected by is_trusted()."""
    store = make_trust_store(tmp_path)
    peer = generate_device_identity()
    store.add_trusted(peer.device_id, peer.public_key_bytes())
    store.remove_trusted(peer.device_id)
    assert not store.is_trusted(peer.device_id)
