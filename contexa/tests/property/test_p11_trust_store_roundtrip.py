# Feature: contexa-core, Property 11: Trust Store Round-Trip
"""
For any device added to the Trust_Store with a given Device_ID and public key,
querying the Trust_Store for that Device_ID must return the same public key
and mark the device as trusted.
Validates: Requirements 6.3
"""

from __future__ import annotations

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


labels = st.one_of(st.none(), st.text(min_size=1, max_size=30))


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(label=labels)
def test_trust_store_round_trip(tmp_path, label):
    """Adding a device and querying it returns the same public key and trusted=True."""
    store = make_trust_store(tmp_path)
    peer = generate_device_identity()

    entry = store.add_trusted(peer.device_id, peer.public_key_bytes(), label=label)

    assert entry.device_id == peer.device_id
    assert entry.public_key_bytes == peer.public_key_bytes()
    assert not entry.revoked
    assert entry.label == label
    assert store.is_trusted(peer.device_id)

    stored_key = store.get_public_key(peer.device_id)
    assert stored_key == peer.public_key_bytes()
