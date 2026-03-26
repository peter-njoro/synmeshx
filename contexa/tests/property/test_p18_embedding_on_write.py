# Feature: contexa-core, Property 18: Embedding Generated on Context Write
"""
For any context created or updated while an embedding model is configured,
the Embedding_Store must contain an embedding for that context's
(context_id, version_tag) pair after the write completes.
Validates: Requirements 10.1
"""

from __future__ import annotations

import numpy as np
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import MagicMock

from contexa.store.database import Base
from contexa.store.embedding_store import EmbeddingStore
from contexa.store.models import EmbeddingRecord


def make_mock_store(session, dim=8):
    store = EmbeddingStore(session, model_name="all-MiniLM-L6-v2")
    mock = MagicMock()
    def encode(text, convert_to_numpy=True):
        seed = hash(text) % (2**31)
        rng = np.random.default_rng(seed)
        v = rng.random(dim).astype("float32")
        return v / np.linalg.norm(v)
    mock.encode.side_effect = encode
    store._model = mock
    return store


json_dicts = st.dictionaries(
    st.text(min_size=1, max_size=10),
    st.one_of(st.integers(min_value=-10, max_value=10), st.text(max_size=10)),
    min_size=1,
    max_size=4,
)

import uuid


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(content=json_dicts)
def test_embedding_stored_after_write(content):
    """After generate_and_store(), an embedding record exists for the version."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    store = make_mock_store(session)

    context_id = str(uuid.uuid4())
    version_tag = "abc12345"

    # Need a contexts row first (FK constraint)
    from contexa.store.models import ContextRecord
    session.add(ContextRecord(
        context_id=context_id,
        owner_device="test-device",
    ))
    session.commit()

    store.generate_and_store(context_id, version_tag, content)

    record = session.query(EmbeddingRecord).filter_by(
        context_id=context_id, version_tag=version_tag
    ).first()
    assert record is not None
    assert record.model_name == "all-MiniLM-L6-v2"
    assert len(record.vector) > 0
