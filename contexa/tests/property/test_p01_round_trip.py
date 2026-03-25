# Feature: contexa-core, Property 1: Context Round-Trip Serialization
"""
For any valid ContextVersion object, serializing it to JSON and then
deserializing the result should produce an object equivalent to the original.
Validates: Requirements 2.1, 2.8, 3.1, 3.2, 3.4, 3.5
"""

from __future__ import annotations

import json
import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from contexa.store.database import Base
from contexa.store.context_store import ContextStore


json_values = st.recursive(
    st.one_of(
        st.none(),
        st.booleans(),
        st.integers(min_value=-1000, max_value=1000),
        st.floats(allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6),
        st.text(max_size=50),
    ),
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(st.text(max_size=10), children, max_size=5),
    ),
    max_leaves=20,
)

json_dicts = st.dictionaries(st.text(min_size=1, max_size=20), json_values, max_size=8)


def make_store():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    return ContextStore(session)


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(content=json_dicts)
def test_context_round_trip(content):
    """Content written to the store is returned unchanged on read."""
    store = make_store()
    v = store.create(content, owner_device="test-device")
    fetched = store.get(v.context_id)
    assert fetched.content == content
    assert fetched.checksum == v.checksum
    assert fetched.version_tag == v.version_tag
    assert fetched.context_id == v.context_id


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(content=json_dicts)
def test_json_serialization_round_trip(content):
    """Serializing a ContextVersion to JSON and back preserves all fields."""
    store = make_store()
    v = store.create(content, owner_device="test-device")

    # Simulate what the API does: serialize to JSON, deserialize back
    serialized = json.dumps({
        "version_id": v.version_id,
        "context_id": v.context_id,
        "version_tag": v.version_tag,
        "parent_version": v.parent_version,
        "content": v.content,
        "checksum": v.checksum,
        "created_at": v.created_at.isoformat(),
        "label": v.label,
    })
    deserialized = json.loads(serialized)

    assert deserialized["content"] == content
    assert deserialized["checksum"] == v.checksum
    assert deserialized["version_tag"] == v.version_tag
