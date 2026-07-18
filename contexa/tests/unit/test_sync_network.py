"""
Unit tests for the encryption-aware sync primitives on SyncEngine:
build_push() and apply_push(). These drive the engine directly (no relay),
covering the paths the happy-path e2e test doesn't reach: conflicts, an
untrusted sender, and tampered ciphertext.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from contexa.store.database import Base
from contexa.store.context_store import ContextStore
from contexa.store.trust_store import TrustStore
from contexa.store.models import DeviceRecord
from contexa.sync.crypto import generate_device_identity, generate_x25519_keypair
from contexa.sync.engine import SyncEngine, SyncMode

SHARED_IDENTITY = "shared-user-identity"


class Peer:
    """A device with its own store/engine, aware of one peer."""

    def __init__(self, identity, peer_identity, *, trust_peer=True):
        db = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=db)
        self.session = sessionmaker(bind=db)()
        for ident in (identity, peer_identity):
            self.session.add(DeviceRecord(
                device_id=ident.device_id,
                public_key=ident.public_key_bytes(),
                identity_id=SHARED_IDENTITY,
            ))
        self.session.commit()

        self.identity = identity
        self.store = ContextStore(self.session)
        self.trust = TrustStore(self.session, data_dir=None)
        if trust_peer:
            self.trust.add_trusted(peer_identity.device_id, peer_identity.public_key_bytes())
        self.engine = SyncEngine(
            session=self.session,
            context_store=self.store,
            trust_store=self.trust,
            identity=identity,
            sync_mode=SyncMode.SELF_HOSTED,
        )


def _session_keys():
    """Return (a_priv, a_pub, b_priv, b_pub) ephemeral X25519 pairs."""
    a_priv, a_pub = generate_x25519_keypair()
    b_priv, b_pub = generate_x25519_keypair()
    return a_priv, a_pub, b_priv, b_pub


def test_build_push_only_includes_missing_and_behind():
    id_a, id_b = generate_device_identity(), generate_device_identity()
    a = Peer(id_a, id_b)
    _, _, _, b_pub = _session_keys()
    a_priv, _ = generate_x25519_keypair()

    v1 = a.store.create({"x": 1}, owner_device=id_a.device_id)
    v2 = a.store.create({"y": 2}, owner_device=id_a.device_id)

    # Peer already has v1 at its current tag → only v2 should be pushed.
    push = a.engine.build_push({v1.context_id: v1.version_tag}, b_pub, a_priv)
    pushed_contexts = {e.context_id for e in push.entries}
    assert pushed_contexts == {v2.context_id}

    # Peer has nothing → both pushed.
    push_all = a.engine.build_push({}, b_pub, a_priv)
    assert {e.context_id for e in push_all.entries} == {v1.context_id, v2.context_id}


def test_apply_push_accepts_new_context_encrypted():
    id_a, id_b = generate_device_identity(), generate_device_identity()
    a, b = Peer(id_a, id_b), Peer(id_b, id_a)
    a_priv, a_pub, b_priv, b_pub = _session_keys()

    content = {"note": "secret", "n": 7}
    created = a.store.create(content, owner_device=id_a.device_id)

    push = a.engine.build_push({}, b_pub, a_priv)
    ack = b.engine.apply_push(push, a_pub, b_priv, id_a.device_id, SHARED_IDENTITY)

    assert created.version_id in ack.accepted
    assert ack.conflicts == [] and ack.rejected == []
    got = b.store.get(created.context_id)
    assert got.content == content and got.checksum == created.checksum


def test_apply_push_detects_conflict():
    id_a, id_b = generate_device_identity(), generate_device_identity()
    a, b = Peer(id_a, id_b), Peer(id_b, id_a)
    a_priv, a_pub, b_priv, b_pub = _session_keys()

    # Both start from the same base version...
    base = a.store.create({"v": 0}, owner_device=id_a.device_id)
    b.store.apply_remote_version(
        version_id=base.version_id, context_id=base.context_id,
        version_tag=base.version_tag, parent_version=None,
        content={"v": 0}, checksum=base.checksum,
        created_at=base.created_at, owner_device=id_a.device_id,
    )
    # ...then each edits independently → divergent history.
    a.store.update(base.context_id, {"v": "a-edit"})
    b.store.update(base.context_id, {"v": "b-edit"})

    push = a.engine.build_push({}, b_pub, a_priv)
    ack = b.engine.apply_push(push, a_pub, b_priv, id_a.device_id, SHARED_IDENTITY)

    a_head = a.store.get(base.context_id)
    assert a_head.version_id in ack.conflicts
    # B keeps its own edit — the conflicting remote version is not applied.
    assert b.store.get(base.context_id).content == {"v": "b-edit"}


def test_apply_push_rejects_untrusted_sender():
    id_a, id_b = generate_device_identity(), generate_device_identity()
    a = Peer(id_a, id_b)
    b = Peer(id_b, id_a, trust_peer=False)  # B does NOT trust A
    a_priv, a_pub, b_priv, b_pub = _session_keys()

    created = a.store.create({"note": "x"}, owner_device=id_a.device_id)
    push = a.engine.build_push({}, b_pub, a_priv)
    ack = b.engine.apply_push(push, a_pub, b_priv, id_a.device_id, SHARED_IDENTITY)

    assert ack.accepted == []
    assert created.version_id in ack.rejected


def test_apply_push_rejects_tampered_ciphertext():
    id_a, id_b = generate_device_identity(), generate_device_identity()
    a, b = Peer(id_a, id_b), Peer(id_b, id_a)
    a_priv, a_pub, b_priv, b_pub = _session_keys()

    created = a.store.create({"note": "x"}, owner_device=id_a.device_id)
    push = a.engine.build_push({}, b_pub, a_priv)

    # Flip a byte in the ciphertext — GCM auth must fail on decrypt.
    entry = push.entries[0]
    ct = bytearray.fromhex(entry.content_encrypted)
    ct[0] ^= 0xFF
    entry.content_encrypted = ct.hex()

    ack = b.engine.apply_push(push, a_pub, b_priv, id_a.device_id, SHARED_IDENTITY)
    assert created.version_id in ack.rejected
    assert ack.accepted == []
