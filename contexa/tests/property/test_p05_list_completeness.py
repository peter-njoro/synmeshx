# Feature: contexa-core, Property 5: List Completeness
"""
For any set of contexts written to the Context_Store, listing all contexts
must return exactly that set — no entries omitted, no phantom entries.
Validates: Requirements 2.6
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
@given(num_contexts=st.integers(min_value=0, max_value=20))
def test_list_returns_exactly_created_contexts(num_contexts):
    """list_all() returns exactly the contexts that were created."""
    store = make_store()
    created_ids = set()

    for i in range(num_contexts):
        v = store.create({"index": i}, owner_device="test-device")
        created_ids.add(v.context_id)

    summaries = store.list_all()
    listed_ids = {s.context_id for s in summaries}

    assert listed_ids == created_ids


@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(num_contexts=st.integers(min_value=1, max_value=10))
def test_list_checksums_match_latest_version(num_contexts):
    """Each summary's checksum matches the latest version's checksum."""
    store = make_store()
    latest = {}

    for i in range(num_contexts):
        v = store.create({"index": i}, owner_device="test-device")
        latest[v.context_id] = v.checksum
        # Do an update so there are multiple versions
        v2 = store.update(v.context_id, {"index": i, "updated": True})
        latest[v.context_id] = v2.checksum

    for summary in store.list_all():
        assert summary.checksum == latest[summary.context_id]
