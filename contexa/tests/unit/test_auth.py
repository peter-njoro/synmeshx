"""
Unit tests for authentication and identity linking.
Requirements: 7.1–7.5
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from contexa.auth import (
    IdentityToken,
    AuthError,
    NotAuthenticatedError,
    TokenExpiredError,
    save_token,
    load_token,
    clear_token,
    get_identity_id,
    associate_identity,
    verify_device_identity,
)
from contexa.store.database import Base
from contexa.store.models import DeviceRecord


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def config_dir(tmp_path):
    return tmp_path / "config"


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


def make_token(expired: bool = False) -> IdentityToken:
    return IdentityToken(
        identity_id="google-sub-12345",
        email="user@example.com",
        access_token="access-token-abc",
        refresh_token="refresh-token-xyz",
        expires_at=time.time() + (-10 if expired else 3600),
    )


# ---------------------------------------------------------------------------
# Token storage
# ---------------------------------------------------------------------------

def test_save_and_load_token(config_dir):
    token = make_token()
    save_token(token, config_dir)
    loaded = load_token(config_dir)
    assert loaded.identity_id == token.identity_id
    assert loaded.email == token.email
    assert loaded.access_token == token.access_token


def test_token_file_has_mode_0600(config_dir):
    import stat
    token = make_token()
    save_token(token, config_dir)
    path = config_dir / "identity.json"
    file_mode = stat.S_IMODE(path.stat().st_mode)
    assert file_mode == 0o600


def test_load_token_missing_raises_not_authenticated(config_dir):
    with pytest.raises(NotAuthenticatedError):
        load_token(config_dir)


def test_clear_token_removes_file(config_dir):
    save_token(make_token(), config_dir)
    clear_token(config_dir)
    with pytest.raises(NotAuthenticatedError):
        load_token(config_dir)


# ---------------------------------------------------------------------------
# Token expiry
# ---------------------------------------------------------------------------

def test_is_expired_returns_false_for_valid_token():
    token = make_token(expired=False)
    assert not token.is_expired()


def test_is_expired_returns_true_for_expired_token():
    token = make_token(expired=True)
    assert token.is_expired()


def test_get_identity_id_raises_on_expired_token(config_dir):
    save_token(make_token(expired=True), config_dir)
    with pytest.raises(TokenExpiredError):
        get_identity_id(config_dir)


def test_get_identity_id_returns_sub_for_valid_token(config_dir):
    save_token(make_token(), config_dir)
    identity_id = get_identity_id(config_dir)
    assert identity_id == "google-sub-12345"


def test_get_identity_id_raises_when_not_authenticated(config_dir):
    with pytest.raises(NotAuthenticatedError):
        get_identity_id(config_dir)


# ---------------------------------------------------------------------------
# Identity association with device
# ---------------------------------------------------------------------------

def test_associate_identity_stores_in_db(session):
    device = DeviceRecord(device_id="dev-001", public_key=b"\x00" * 32)
    session.add(device)
    session.commit()

    associate_identity("dev-001", "google-sub-12345", session)

    updated = session.get(DeviceRecord, "dev-001")
    assert updated.identity_id == "google-sub-12345"


def test_associate_identity_missing_device_raises(session):
    with pytest.raises(AuthError):
        associate_identity("nonexistent-device", "google-sub-12345", session)


# ---------------------------------------------------------------------------
# Device identity verification
# ---------------------------------------------------------------------------

def test_verify_device_identity_returns_true_for_match(session):
    device = DeviceRecord(
        device_id="dev-001",
        public_key=b"\x00" * 32,
        identity_id="google-sub-12345",
    )
    session.add(device)
    session.commit()

    assert verify_device_identity("dev-001", "google-sub-12345", session)


def test_verify_device_identity_returns_false_for_mismatch(session):
    device = DeviceRecord(
        device_id="dev-001",
        public_key=b"\x00" * 32,
        identity_id="google-sub-12345",
    )
    session.add(device)
    session.commit()

    assert not verify_device_identity("dev-001", "different-identity", session)


def test_verify_device_identity_returns_false_for_unknown_device(session):
    assert not verify_device_identity("unknown-device", "google-sub-12345", session)


def test_verify_device_identity_returns_false_when_no_identity_set(session):
    device = DeviceRecord(device_id="dev-001", public_key=b"\x00" * 32)
    session.add(device)
    session.commit()

    assert not verify_device_identity("dev-001", "google-sub-12345", session)


# ---------------------------------------------------------------------------
# Token round-trip serialization
# ---------------------------------------------------------------------------

def test_token_round_trip_serialization():
    token = make_token()
    restored = IdentityToken.from_dict(token.to_dict())
    assert restored.identity_id == token.identity_id
    assert restored.email == token.email
    assert restored.expires_at == token.expires_at
    assert restored.provider == token.provider
