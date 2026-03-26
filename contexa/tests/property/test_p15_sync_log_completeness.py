# Feature: contexa-core, Property 15: Sync Log Completeness
"""
For any sync operation (successful, failed, or conflict), the resulting
Sync_Log entry must contain all five required fields: Device_ID, Context_ID,
Version_Tag, status, and timestamp.
Validates: Requirements 8.6
"""

from __future__ import annotations

import pathlib
import tempfile
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from contexa.store.database import Base
from contexa.store.context_store import ContextStore
from contexa.store.trust_store import TrustStore
from contexa.store.models import DeviceRecord, SyncLogRecord
from contexa.sync.engine import SyncEngine
from contexa.sync.crypto import generate_device_identity


def make_engine_with_peer():
    db_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=db_engine)
    session = sessionmaker(bind=db_engine)()

    identity_a = generate_device_identity()
    peer = generate_device_identity()
    shared_id = "shared-identity"

    for ident in [identity_a, peer]:
        session.add(DeviceRecord(
            device_id=ident.device_id,
            public_key=ident.public_key_bytes(),
            identity_id=shared_id,
        ))
    session.commit()

    tmp = pathlib.Path(tempfile.mkdtemp())
    trust = TrustStore(session, data_dir=tmp)
    trust.register_self()
    trust.add_trusted(peer.device_id, peer.public_key_bytes())

    context_store = ContextStore(session)
    engine = SyncEngine(
        session=session,
        context_store=context_store,
        trust_store=trust,
        identity=identity_a,
    )
    return engine, session, peer, shared_id


@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(num_contexts=st.integers(min_value=1, max_value=5))
def test_sync_log_entries_have_all_required_fields(num_contexts):
    """Every sync log entry has device_id, context_id, version_tag, status, created_at."""
    engine, session, peer, shared_id = make_engine_with_peer()

    peer_contexts = {f"ctx-{i}": f"v{i}" for i in range(num_contexts)}

    engine.sync_with_peer(
        peer_device_id=peer.device_id,
        peer_contexts=peer_contexts,
        peer_public_key_bytes=peer.public_key_bytes(),
        peer_identity_id=shared_id,
    )

    entries = session.query(SyncLogRecord).all()
    assert len(entries) >= num_contexts

    for entry in entries:
        assert entry.device_id, "device_id must not be empty"
        assert entry.context_id, "context_id must not be empty"
        assert entry.version_tag, "version_tag must not be empty"
        assert entry.status in ("success", "conflict", "failed", "pending")
        assert entry.created_at is not None
