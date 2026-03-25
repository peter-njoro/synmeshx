# Feature: contexa-core, Property 2: Checksum Integrity
"""
For any context content written to the Context_Store, the stored SHA-256
checksum must equal sha256(json.dumps(content, sort_keys=True)).
If the stored content is modified after writing, reading must return a
ChecksumError rather than silently returning corrupted data.
Validates: Requirements 2.2, 2.3
"""

from __future__ import annotations

import hashlib
import json
import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from contexa.store.database import Base
from contexa.store.context_store import ContextStore, ChecksumError
from contexa.store.models import ContextVersionRecord


json_dicts = st.dictionaries(
    st.text(min_size=1, max_size=20),
    st.one_of(st.integers(), st.text(max_size=30), st.booleans()),
    max_size=8,
)


def make_store():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    return ContextStore(session), session


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(content=json_dicts)
def test_stored_checksum_matches_content(content):
    """Checksum stored equals sha256(json.dumps(content, sort_keys=True))."""
    store, _ = make_store()
    v = store.create(content, owner_device="test-device")
    expected = hashlib.sha256(
        json.dumps(content, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    assert v.checksum == expected


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(content=json_dicts)
def test_tampered_content_raises_checksum_error(content):
    """Modifying stored content after write causes ChecksumError on read."""
    store, session = make_store()
    v = store.create(content, owner_device="test-device")

    # Tamper directly in the DB
    record = session.query(ContextVersionRecord).filter_by(
        version_id=v.version_id
    ).first()
    record.content = json.dumps({"__tampered__": True})
    session.commit()

    with pytest.raises(ChecksumError):
        store.get(v.context_id)
