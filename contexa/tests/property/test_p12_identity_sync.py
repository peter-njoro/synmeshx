# Feature: contexa-core, Property 12: Same Identity Required for Sync
"""
For any two devices with different identity_id values, the Sync_Engine
must reject the sync attempt before exchanging any context data.
Here we test the verify_device_identity() gate directly.
Validates: Requirements 7.3
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from contexa.auth import verify_device_identity, associate_identity
from contexa.store.database import Base
from contexa.store.models import DeviceRecord


def make_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


identity_ids = st.text(min_size=5, max_size=50).filter(lambda s: s.strip() != "")


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(identity_a=identity_ids, identity_b=identity_ids)
def test_different_identities_are_rejected(identity_a, identity_b):
    """Two devices with different identity_ids must not be verified as matching."""
    assume(identity_a != identity_b)

    session = make_session()
    device = DeviceRecord(
        device_id="dev-001",
        public_key=b"\x00" * 32,
        identity_id=identity_a,
    )
    session.add(device)
    session.commit()

    # Device claims identity_b but has identity_a stored
    assert not verify_device_identity("dev-001", identity_b, session)


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(identity_id=identity_ids)
def test_same_identity_is_accepted(identity_id):
    """A device with a matching identity_id is verified successfully."""
    session = make_session()
    device = DeviceRecord(
        device_id="dev-001",
        public_key=b"\x00" * 32,
        identity_id=identity_id,
    )
    session.add(device)
    session.commit()

    assert verify_device_identity("dev-001", identity_id, session)
