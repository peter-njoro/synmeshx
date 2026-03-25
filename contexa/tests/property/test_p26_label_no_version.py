# Feature: contexa-core, Property 26: Label Mutation Does Not Create Version
"""
For any Context with N versions, updating its label must result in the
Context still having exactly N versions, with the label updated on the
contexts row.
Validates: Requirements 2.10
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


labels = st.one_of(st.none(), st.text(min_size=1, max_size=50))


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    num_versions=st.integers(min_value=1, max_value=5),
    new_label=labels,
)
def test_label_update_does_not_create_version(num_versions, new_label):
    """Updating a label never increases the version count."""
    store = make_store()
    v = store.create({"step": 0}, owner_device="test-device")
    for i in range(1, num_versions):
        v = store.update(v.context_id, {"step": i})

    context_id = v.context_id
    versions_before = store.list_versions(context_id)
    assert len(versions_before) == num_versions

    store.update_label(context_id, new_label)

    versions_after = store.list_versions(context_id)
    assert len(versions_after) == num_versions

    fetched = store.get(context_id)
    assert fetched.label == new_label
