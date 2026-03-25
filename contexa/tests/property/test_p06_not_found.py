# Feature: contexa-core, Property 6: Not-Found for Missing Resources
"""
For any UUID that has not been stored as a Context_ID, the Context_Store
must return NotFoundError rather than returning null data or raising an
unhandled exception.
Validates: Requirements 2.7, 4.5
"""

from __future__ import annotations

import uuid
import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from contexa.store.database import Base
from contexa.store.context_store import ContextStore, NotFoundError


def make_store():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    return ContextStore(session)


random_uuids = st.uuids().map(str)


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(missing_id=random_uuids)
def test_get_missing_raises_not_found(missing_id):
    """get() on a non-existent context_id raises NotFoundError."""
    store = make_store()
    with pytest.raises(NotFoundError) as exc:
        store.get(missing_id)
    assert exc.value.context_id == missing_id


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(missing_id=random_uuids)
def test_delete_missing_raises_not_found(missing_id):
    """delete() on a non-existent context_id raises NotFoundError."""
    store = make_store()
    with pytest.raises(NotFoundError):
        store.delete(missing_id)


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(missing_id=random_uuids)
def test_update_missing_raises_not_found(missing_id):
    """update() on a non-existent context_id raises NotFoundError."""
    store = make_store()
    with pytest.raises(NotFoundError):
        store.update(missing_id, {"x": 1})
