# Feature: contexa-core, Property 19: Semantic Search Ordered by Cosine Similarity
"""
For any query string and any set of stored embeddings, the results returned
by the semantic search must be ordered by descending cosine similarity score,
and no result with a lower score may appear before a result with a higher score.
Validates: Requirements 10.3
"""

from __future__ import annotations

import uuid
import numpy as np
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import MagicMock

from contexa.store.database import Base
from contexa.store.embedding_store import EmbeddingStore
from contexa.store.models import ContextRecord


def make_store_with_contexts(n_contexts: int, dim: int = 8):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()

    store = EmbeddingStore(session, model_name="all-MiniLM-L6-v2")
    mock = MagicMock()

    call_count = [0]
    def encode(text, convert_to_numpy=True):
        seed = hash(text) % (2**31)
        rng = np.random.default_rng(seed)
        v = rng.random(dim).astype("float32")
        return v / np.linalg.norm(v)
    mock.encode.side_effect = encode
    store._model = mock

    for i in range(n_contexts):
        ctx_id = str(uuid.uuid4())
        session.add(ContextRecord(context_id=ctx_id, owner_device="dev"))
        session.commit()
        store.generate_and_store(ctx_id, f"v{i}", {"index": i, "text": f"context {i}"})

    return store


@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    n_contexts=st.integers(min_value=2, max_value=10),
    top_n=st.integers(min_value=1, max_value=5),
)
def test_search_results_ordered_by_descending_score(n_contexts, top_n):
    """Search results are always ordered by descending cosine similarity."""
    store = make_store_with_contexts(n_contexts)
    results = store.search("test query", top_n=top_n)

    if len(results) < 2:
        return  # nothing to compare

    scores = [r[2] for r in results]
    for i in range(1, len(scores)):
        assert scores[i] <= scores[i - 1], (
            f"Score at position {i} ({scores[i]}) is greater than "
            f"position {i-1} ({scores[i-1]}) — not sorted"
        )
