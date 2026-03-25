# Feature: contexa-core, Property 3: Version Monotonicity
"""
For any sequence of writes to the same Context_ID, each write must produce
a new Version_Tag that did not previously exist, and all prior versions must
remain retrievable and unchanged.
Validates: Requirements 2.4
"""

from __future__ import annotations

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from contexa.store.database import Base
from contexa.store.context_store import ContextStore


def make_store():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    return ContextStore(session)


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(num_updates=st.integers(min_value=1, max_value=10))
def test_each_write_produces_unique_version_tag(num_updates):
    """N writes to the same context produce N distinct version tags."""
    store = make_store()
    v = store.create({"step": 0}, owner_device="test-device")
    tags = {v.version_tag}

    for i in range(1, num_updates + 1):
        v = store.update(v.context_id, {"step": i})
        assert v.version_tag not in tags, f"Duplicate version_tag after {i} updates"
        tags.add(v.version_tag)

    assert len(tags) == num_updates + 1


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(num_updates=st.integers(min_value=1, max_value=8))
def test_prior_versions_remain_unchanged(num_updates):
    """All prior versions remain retrievable and their content is unchanged."""
    store = make_store()
    snapshots = []

    v = store.create({"step": 0}, owner_device="test-device")
    snapshots.append((v.version_tag, {"step": 0}))

    for i in range(1, num_updates + 1):
        v = store.update(v.context_id, {"step": i})
        snapshots.append((v.version_tag, {"step": i}))

    context_id = v.context_id
    for tag, expected_content in snapshots:
        fetched = store.get(context_id, version_tag=tag)
        assert fetched.content == expected_content
