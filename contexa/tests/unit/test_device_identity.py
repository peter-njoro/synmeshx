"""
Unit tests for device identity (crypto.py) and TrustStore.
Requirements: 6.1–6.6
"""

from __future__ import annotations

import stat
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from contexa.store.database import Base
from contexa.store.trust_store import (
    TrustStore,
    DeviceAlreadyTrustedError,
    DeviceNotFoundError,
)
from contexa.sync.crypto import (
    generate_device_identity,
    save_device_identity,
    load_device_identity,
    load_or_generate_identity,
    sign,
    verify,
    generate_x25519_keypair,
    derive_session_key,
    encrypt,
    decrypt,
    generate_nonce,
    public_key_from_bytes,
)


# Fixtures

@pytest.fixture
def tmp_data_dir(tmp_path):
    return tmp_path / "contexa"


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
def trust_store(session, tmp_data_dir):
    return TrustStore(session, data_dir=tmp_data_dir)


# Key generation

def test_generate_device_identity_produces_unique_ids():
    id1 = generate_device_identity()
    id2 = generate_device_identity()
    assert id1.device_id != id2.device_id


def test_generate_device_identity_has_valid_key_pair():
    identity = generate_device_identity()
    # Sign and verify a test message
    msg = b"test message"
    sig = sign(identity.private_key, msg)
    assert verify(identity.public_key, msg, sig)


def test_public_key_bytes_is_32_bytes():
    identity = generate_device_identity()
    assert len(identity.public_key_bytes()) == 32


# Key persistence

def test_save_and_load_identity(tmp_data_dir):
    identity = generate_device_identity()
    save_device_identity(identity, tmp_data_dir)

    loaded = load_device_identity(tmp_data_dir)
    assert loaded.device_id == identity.device_id
    assert loaded.public_key_bytes() == identity.public_key_bytes()


def test_key_file_has_mode_0600(tmp_data_dir):
    identity = generate_device_identity()
    save_device_identity(identity, tmp_data_dir)

    key_file = tmp_data_dir / "device_key.pem"
    file_mode = stat.S_IMODE(key_file.stat().st_mode)
    assert file_mode == 0o600, f"Expected 0600, got {oct(file_mode)}"


def test_load_or_generate_creates_on_first_run(tmp_data_dir):
    identity = load_or_generate_identity(tmp_data_dir)
    assert identity.device_id
    assert (tmp_data_dir / "device_id").exists()
    assert (tmp_data_dir / "device_key.pem").exists()


def test_load_or_generate_is_idempotent(tmp_data_dir):
    id1 = load_or_generate_identity(tmp_data_dir)
    id2 = load_or_generate_identity(tmp_data_dir)
    assert id1.device_id == id2.device_id
    assert id1.public_key_bytes() == id2.public_key_bytes()


# Ed25519 sign / verify

def test_sign_verify_roundtrip():
    identity = generate_device_identity()
    msg = b"hello contexa"
    sig = sign(identity.private_key, msg)
    assert verify(identity.public_key, msg, sig)


def test_verify_wrong_message_fails():
    identity = generate_device_identity()
    sig = sign(identity.private_key, b"original")
    assert not verify(identity.public_key, b"tampered", sig)


def test_verify_wrong_key_fails():
    id1 = generate_device_identity()
    id2 = generate_device_identity()
    sig = sign(id1.private_key, b"message")
    assert not verify(id2.public_key, b"message", sig)


# X25519 + AES-256-GCM

def test_encrypt_decrypt_roundtrip():
    priv_a, pub_a = generate_x25519_keypair()
    priv_b, pub_b = generate_x25519_keypair()
    nonce = generate_nonce()

    key_a = derive_session_key(priv_a, pub_b, nonce, "device-a")
    key_b = derive_session_key(priv_b, pub_a, nonce, "device-a")

    # Both sides derive the same key
    assert key_a == key_b

    plaintext = b"secret context data"
    aad = b"device-a"
    ciphertext = encrypt(key_a, nonce, plaintext, aad)
    recovered = decrypt(key_b, nonce, ciphertext, aad)
    assert recovered == plaintext


def test_decrypt_wrong_key_fails():
    from cryptography.exceptions import InvalidTag
    priv_a, pub_a = generate_x25519_keypair()
    priv_b, pub_b = generate_x25519_keypair()
    priv_c, pub_c = generate_x25519_keypair()
    nonce = generate_nonce()

    key_a = derive_session_key(priv_a, pub_b, nonce, "device-a")
    key_wrong = derive_session_key(priv_c, pub_b, nonce, "device-a")

    ciphertext = encrypt(key_a, nonce, b"secret", b"aad")
    with pytest.raises(Exception):  # InvalidTag
        decrypt(key_wrong, nonce, ciphertext, b"aad")


def test_nonce_is_12_bytes():
    assert len(generate_nonce()) == 12


# TrustStore — register_self

def test_register_self_creates_identity(trust_store, tmp_data_dir):
    identity = trust_store.register_self()
    assert identity.device_id
    assert (tmp_data_dir / "device_id").exists()


def test_register_self_is_idempotent(trust_store):
    id1 = trust_store.register_self()
    id2 = trust_store.register_self()
    assert id1.device_id == id2.device_id


# TrustStore — add / remove / list

def test_add_trusted_device(trust_store):
    peer = generate_device_identity()
    entry = trust_store.add_trusted(peer.device_id, peer.public_key_bytes(), label="laptop")
    assert entry.device_id == peer.device_id
    assert entry.label == "laptop"
    assert not entry.revoked


def test_is_trusted_returns_true_after_add(trust_store):
    peer = generate_device_identity()
    trust_store.add_trusted(peer.device_id, peer.public_key_bytes())
    assert trust_store.is_trusted(peer.device_id)


def test_is_trusted_returns_false_for_unknown(trust_store):
    assert not trust_store.is_trusted("unknown-device-id")


def test_remove_trusted_revokes_device(trust_store):
    peer = generate_device_identity()
    trust_store.add_trusted(peer.device_id, peer.public_key_bytes())
    trust_store.remove_trusted(peer.device_id)
    assert not trust_store.is_trusted(peer.device_id)


def test_remove_trusted_missing_raises_not_found(trust_store):
    with pytest.raises(DeviceNotFoundError):
        trust_store.remove_trusted("nonexistent-id")


def test_add_already_trusted_raises_error(trust_store):
    peer = generate_device_identity()
    trust_store.add_trusted(peer.device_id, peer.public_key_bytes())
    with pytest.raises(DeviceAlreadyTrustedError):
        trust_store.add_trusted(peer.device_id, peer.public_key_bytes())


def test_revoked_device_can_be_re_trusted(trust_store):
    peer = generate_device_identity()
    trust_store.add_trusted(peer.device_id, peer.public_key_bytes())
    trust_store.remove_trusted(peer.device_id)
    # Re-add after revocation should succeed
    entry = trust_store.add_trusted(peer.device_id, peer.public_key_bytes(), label="re-trusted")
    assert not entry.revoked
    assert trust_store.is_trusted(peer.device_id)


def test_list_trusted_excludes_revoked(trust_store):
    peer1 = generate_device_identity()
    peer2 = generate_device_identity()
    trust_store.add_trusted(peer1.device_id, peer1.public_key_bytes(), label="keep")
    trust_store.add_trusted(peer2.device_id, peer2.public_key_bytes(), label="revoke")
    trust_store.remove_trusted(peer2.device_id)

    trusted = trust_store.list_trusted()
    ids = [e.device_id for e in trusted]
    assert peer1.device_id in ids
    assert peer2.device_id not in ids


def test_get_public_key_returns_correct_bytes(trust_store):
    peer = generate_device_identity()
    trust_store.add_trusted(peer.device_id, peer.public_key_bytes())
    stored = trust_store.get_public_key(peer.device_id)
    assert stored == peer.public_key_bytes()
