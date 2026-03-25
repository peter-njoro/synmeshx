# Feature: contexa-core, Property 4: Latest Version Default
"""
For any Context_ID with multiple stored versions, reading without specifying
a Version_Tag must return the version created most recently.
Validates: Requirements 2.5
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
def test_get_without_tag_returns_latest(num_updates):
    """get() with no version_tag always returns the most recently written version."""
    store = make_store()
    v = store.create({"step": 0}, owner_device="test-device")
    latest_id = v.version_id

    for i in range(1, num_updates + 1):
        v = store.update(v.context_id, {"step": i})
        latest_id = v.version_id

    fetched = store.get(v.context_id)
    assert fetched.version_id == latest_id
    assert fetched.content == {"step": num_updates}
