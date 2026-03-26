"""
Unit tests for the Sync Engine and protocol.
Requirements: 8.1–8.7
"""

from __future__ import annotations

import time
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from contexa.store.database import Base
from contexa.store.context_store import ContextStore
from contexa.store.trust_store import TrustStore
from contexa.store.models import SyncLogRecord
from contexa.sync.engine import SyncEngine, SyncResult
from contexa.sync.protocol import (
    detect_conflict,
    is_ancestor,
    serialize,
    deserialize,
    HelloMessage,
    KnownVersionsMessage,
    PushMessage,
    PushEntry,
    AckMessage,
    MSG_HELLO,
    MSG_KNOWN_VERSIONS,
    MSG_PUSH,
    MSG_ACK,
)
from contexa.sync.crypto import generate_device_identity


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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
def identity(tmp_path):
    return generate_device_identity()


@pytest.fixture
def peer_identity():
    return generate_device_identity()


@pytest.fixture
def trust_store(session, tmp_path):
    store = TrustStore(session, data_dir=tmp_path)
    store.register_self()
    return store


@pytest.fixture
def context_store(session):
    return ContextStore(session)


@pytest.fixture
def engine(session, context_store, trust_store, identity):
    return SyncEngine(
        session=session,
        context_store=context_store,
        trust_store=trust_store,
        identity=identity,
        max_retries=3,
        backoff_base=2.0,
    )


# ---------------------------------------------------------------------------
# Protocol — serialization
# ---------------------------------------------------------------------------

def test_hello_message_round_trip():
    msg = HelloMessage(device_id="dev-001", identity_id="id-001", signature="sig", challenge="chal")
    restored = deserialize(serialize(msg))
    assert isinstance(restored, HelloMessage)
    assert restored.device_id == "dev-001"
    assert restored.identity_id == "id-001"


def test_known_versions_round_trip():
    msg = KnownVersionsMessage(versions={"ctx-1": "v1", "ctx-2": "v2"})
    restored = deserialize(serialize(msg))
    assert isinstance(restored, KnownVersionsMessage)
    assert restored.versions == {"ctx-1": "v1", "ctx-2": "v2"}


def test_push_message_round_trip():
    entry = PushEntry(
        version_id="ver-001", context_id="ctx-001", version_tag="abc12345",
        parent_version=None, content_encrypted="deadbeef", checksum="a" * 64,
        created_at="2024-01-01T00:00:00", nonce="00" * 12,
    )
    msg = PushMessage(entries=[entry])
    restored = deserialize(serialize(msg))
    assert isinstance(restored, PushMessage)
    assert len(restored.entries) == 1
    assert restored.entries[0].version_id == "ver-001"


def test_ack_message_round_trip():
    msg = AckMessage(accepted=["v1", "v2"], conflicts=["v3"], rejected=[])
    restored = deserialize(serialize(msg))
    assert isinstance(restored, AckMessage)
    assert restored.accepted == ["v1", "v2"]
    assert restored.conflicts == ["v3"]


def test_deserialize_unknown_type_raises():
    import json
    with pytest.raises(ValueError):
        deserialize(json.dumps({"type": "UNKNOWN"}).encode())


# ---------------------------------------------------------------------------
# Protocol — ancestor chain
# ---------------------------------------------------------------------------

def test_is_ancestor_direct_parent():
    version_map = {"v2": "v1", "v1": None}
    assert is_ancestor("v1", "v2", version_map)


def test_is_ancestor_grandparent():
    version_map = {"v3": "v2", "v2": "v1", "v1": None}
    assert is_ancestor("v1", "v3", version_map)


def test_is_ancestor_same_version():
    version_map = {"v1": None}
    # A version IS considered an ancestor of itself (trivial case — no conflict)
    assert is_ancestor("v1", "v1", version_map)


def test_is_ancestor_unrelated():
    version_map = {"v2": "v1", "v3": "v1", "v1": None}
    assert not is_ancestor("v2", "v3", version_map)
    assert not is_ancestor("v3", "v2", version_map)


def test_detect_conflict_fast_forward():
    # v2 is a descendant of v1 — no conflict
    version_map = {"v2": "v1", "v1": None}
    assert not detect_conflict("v1", "v2", version_map)


def test_detect_conflict_diverged():
    # v2 and v3 both descend from v1 independently — conflict
    version_map = {"v2": "v1", "v3": "v1", "v1": None}
    assert detect_conflict("v2", "v3", version_map)


def test_detect_conflict_local_newer():
    # local v3 is ahead of remote v2 — no conflict (local is newer)
    version_map = {"v3": "v2", "v2": "v1", "v1": None}
    assert not detect_conflict("v3", "v2", version_map)


# ---------------------------------------------------------------------------
# Sync Engine — trust enforcement
# ---------------------------------------------------------------------------

def test_sync_rejected_for_untrusted_device(engine, peer_identity, session):
    """Sync with an untrusted device returns empty result."""
    result = engine.sync_with_peer(
        peer_device_id=peer_identity.device_id,
        peer_contexts={},
        peer_public_key_bytes=peer_identity.public_key_bytes(),
        peer_identity_id="some-identity",
    )
    assert result.accepted == []
    assert result.conflicts == []


def test_sync_rejected_for_identity_mismatch(engine, trust_store, peer_identity, session):
    """Sync with a trusted device but wrong identity is rejected."""
    from contexa.store.models import DeviceRecord
    # Add device to DB with identity "identity-A"
    device = DeviceRecord(
        device_id=peer_identity.device_id,
        public_key=peer_identity.public_key_bytes(),
        identity_id="identity-A",
    )
    session.add(device)
    session.commit()
    trust_store.add_trusted(peer_identity.device_id, peer_identity.public_key_bytes())

    result = engine.sync_with_peer(
        peer_device_id=peer_identity.device_id,
        peer_contexts={},
        peer_public_key_bytes=peer_identity.public_key_bytes(),
        peer_identity_id="identity-B",  # wrong identity
    )
    assert result.accepted == []


# ---------------------------------------------------------------------------
# Sync Engine — replication
# ---------------------------------------------------------------------------

def _setup_peer(session, trust_store, peer_identity, identity_id="shared-identity"):
    """Register peer device with matching identity."""
    from contexa.store.models import DeviceRecord
    device = DeviceRecord(
        device_id=peer_identity.device_id,
        public_key=peer_identity.public_key_bytes(),
        identity_id=identity_id,
    )
    session.add(device)
    session.commit()
    trust_store.add_trusted(peer_identity.device_id, peer_identity.public_key_bytes())


def test_sync_accepts_new_context_from_peer(engine, trust_store, peer_identity, session):
    """Peer has a context we don't — it gets accepted."""
    _setup_peer(session, trust_store, peer_identity)

    result = engine.sync_with_peer(
        peer_device_id=peer_identity.device_id,
        peer_contexts={"ctx-new": "abc12345"},
        peer_public_key_bytes=peer_identity.public_key_bytes(),
        peer_identity_id="shared-identity",
    )
    assert "abc12345" in result.accepted


def test_sync_detects_conflict(engine, trust_store, peer_identity, context_store, session):
    """Diverging versions of the same context produce a conflict."""
    _setup_peer(session, trust_store, peer_identity)

    # Create a local context
    v = context_store.create({"step": 1}, owner_device="local-device")
    # Update it locally (v2 descends from v1)
    v2 = context_store.update(v.context_id, {"step": 2})

    # Peer has a different version of the same context (also from v1, but different)
    # Simulate by providing a version_tag that's not in our ancestor chain
    result = engine.sync_with_peer(
        peer_device_id=peer_identity.device_id,
        peer_contexts={v.context_id: "peer-diverged-tag"},
        peer_public_key_bytes=peer_identity.public_key_bytes(),
        peer_identity_id="shared-identity",
    )
    # "peer-diverged-tag" is not in our version map, so detect_conflict returns True
    assert "peer-diverged-tag" in result.conflicts


def test_sync_log_written_for_each_operation(engine, trust_store, peer_identity, session):
    """Every sync operation writes a sync_log entry."""
    _setup_peer(session, trust_store, peer_identity)

    engine.sync_with_peer(
        peer_device_id=peer_identity.device_id,
        peer_contexts={"ctx-1": "v1", "ctx-2": "v2"},
        peer_public_key_bytes=peer_identity.public_key_bytes(),
        peer_identity_id="shared-identity",
    )

    entries = session.query(SyncLogRecord).all()
    assert len(entries) >= 2
    for entry in entries:
        assert entry.device_id == peer_identity.device_id
        assert entry.status in ("success", "conflict", "failed", "pending")
        assert entry.context_id
        assert entry.version_tag
        assert entry.created_at


# ---------------------------------------------------------------------------
# Sync Engine — offline queue and backoff
# ---------------------------------------------------------------------------

def test_queue_pending_writes_log(engine, session):
    """Queuing a pending operation writes a 'pending' sync_log entry."""
    engine.queue_pending("ctx-001", "v1", "peer-device-001")
    entries = session.query(SyncLogRecord).filter_by(status="pending").all()
    assert len(entries) == 1
    assert entries[0].context_id == "ctx-001"


def test_backoff_delay_increases_exponentially(engine):
    """Backoff delay doubles with each attempt."""
    assert engine.get_backoff_delay(0) == 1.0   # 2^0
    assert engine.get_backoff_delay(1) == 2.0   # 2^1
    assert engine.get_backoff_delay(2) == 4.0   # 2^2
    assert engine.get_backoff_delay(3) == 8.0   # 2^3


def test_syncs_completed_counter_increments(engine, trust_store, peer_identity, session):
    """syncs_completed increments after each successful sync cycle."""
    _setup_peer(session, trust_store, peer_identity)
    assert engine.syncs_completed == 0

    engine.sync_with_peer(
        peer_device_id=peer_identity.device_id,
        peer_contexts={},
        peer_public_key_bytes=peer_identity.public_key_bytes(),
        peer_identity_id="shared-identity",
    )
    assert engine.syncs_completed == 1


# ---------------------------------------------------------------------------
# Sync log filtering
# ---------------------------------------------------------------------------

def test_sync_log_filter_by_status(engine, trust_store, peer_identity, session):
    """get_sync_log() filters by status correctly."""
    _setup_peer(session, trust_store, peer_identity)

    engine.sync_with_peer(
        peer_device_id=peer_identity.device_id,
        peer_contexts={"ctx-1": "v1"},
        peer_public_key_bytes=peer_identity.public_key_bytes(),
        peer_identity_id="shared-identity",
    )

    success_entries = engine.get_sync_log(status="success")
    assert all(e.status == "success" for e in success_entries)


def test_sync_log_filter_by_device(engine, trust_store, peer_identity, session):
    """get_sync_log() filters by device_id correctly."""
    _setup_peer(session, trust_store, peer_identity)

    engine.sync_with_peer(
        peer_device_id=peer_identity.device_id,
        peer_contexts={"ctx-1": "v1"},
        peer_public_key_bytes=peer_identity.public_key_bytes(),
        peer_identity_id="shared-identity",
    )

    entries = engine.get_sync_log(device_id=peer_identity.device_id)
    assert all(e.device_id == peer_identity.device_id for e in entries)

    entries_other = engine.get_sync_log(device_id="other-device")
    assert entries_other == []
