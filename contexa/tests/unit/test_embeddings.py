"""
Unit tests for EmbeddingStore and semantic search endpoint.
Uses mocked sentence-transformers to avoid requiring the large dependency.
Requirements: 10.1–10.5
"""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from contexa.api.app import create_app
from contexa.config import ContexaConfig
from contexa.store.context_store import ContextStore
from contexa.store.database import Base
from contexa.store.embedding_store import EmbeddingStore, EmbeddingDisabledError
from contexa.store.models import EmbeddingRecord


# Fixtures

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


def make_mock_model(dim: int = 8):
    """Return a mock SentenceTransformer that produces deterministic vectors."""
    mock = MagicMock()
    def encode(text, convert_to_numpy=True):
        # Produce a deterministic vector based on text hash
        seed = hash(text) % (2**31)
        rng = np.random.default_rng(seed)
        v = rng.random(dim).astype("float32")
        return v / np.linalg.norm(v)
    mock.encode.side_effect = encode
    return mock


@pytest.fixture
def embedding_store(session):
    store = EmbeddingStore(session, model_name="all-MiniLM-L6-v2")
    store._model = make_mock_model()
    return store


@pytest.fixture
def disabled_store(session):
    return EmbeddingStore(session, model_name="")


# EmbeddingStore — disabled

def test_disabled_store_raises_on_generate(disabled_store):
    with pytest.raises(EmbeddingDisabledError):
        disabled_store.generate_and_store("ctx-1", "v1", {"x": 1})


def test_disabled_store_raises_on_search(disabled_store):
    with pytest.raises(EmbeddingDisabledError):
        disabled_store.search("query")


def test_disabled_store_enabled_is_false(disabled_store):
    assert not disabled_store.enabled


def test_enabled_store_enabled_is_true(embedding_store):
    assert embedding_store.enabled


# EmbeddingStore — generate and store

def test_generate_stores_embedding(embedding_store, session):
    embedding_store.generate_and_store("ctx-1", "v1", {"task": "write tests"})
    record = session.query(EmbeddingRecord).filter_by(
        context_id="ctx-1", version_tag="v1"
    ).first()
    assert record is not None
    assert record.model_name == "all-MiniLM-L6-v2"
    assert len(record.vector) > 0


def test_generate_stores_normalized_vector(embedding_store, session):
    embedding_store.generate_and_store("ctx-1", "v1", {"x": 1})
    record = session.query(EmbeddingRecord).filter_by(context_id="ctx-1").first()
    vector = np.frombuffer(record.vector, dtype="float32")
    norm = np.linalg.norm(vector)
    assert abs(norm - 1.0) < 1e-5, f"Vector not normalized: norm={norm}"


def test_generate_on_update_creates_new_record(embedding_store, session):
    embedding_store.generate_and_store("ctx-1", "v1", {"step": 1})
    embedding_store.generate_and_store("ctx-1", "v2", {"step": 2})
    records = session.query(EmbeddingRecord).filter_by(context_id="ctx-1").all()
    assert len(records) == 2


# EmbeddingStore — search

def test_search_returns_results_ordered_by_score(embedding_store, session):
    embedding_store.generate_and_store("ctx-1", "v1", {"topic": "machine learning"})
    embedding_store.generate_and_store("ctx-2", "v1", {"topic": "cooking recipes"})
    embedding_store.generate_and_store("ctx-3", "v1", {"topic": "neural networks"})

    results = embedding_store.search("deep learning", top_n=3)
    assert len(results) <= 3
    # Scores should be in descending order
    scores = [r[2] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_search_respects_top_n(embedding_store, session):
    for i in range(5):
        embedding_store.generate_and_store(f"ctx-{i}", "v1", {"index": i})

    results = embedding_store.search("query", top_n=2)
    assert len(results) <= 2


def test_search_empty_store_returns_empty(embedding_store):
    results = embedding_store.search("anything")
    assert results == []


def test_search_returns_context_id_and_version_tag(embedding_store, session):
    embedding_store.generate_and_store("ctx-abc", "tag-xyz", {"data": "test"})
    results = embedding_store.search("test")
    assert len(results) == 1
    context_id, version_tag, score = results[0]
    assert context_id == "ctx-abc"
    assert version_tag == "tag-xyz"
    assert isinstance(score, float)


# API — /contexts/search endpoint

def make_client_with_embeddings(embedding_store=None):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()

    app = create_app()
    app.state.context_store = ContextStore(session)
    app.state.config = ContexaConfig()
    app.state.device_id = "test-device"
    app.state.start_time = time.time()
    if embedding_store:
        app.state.embedding_store = embedding_store
        # Share the same session
        embedding_store._session = session

    return TestClient(app, raise_server_exceptions=False), session


def test_search_endpoint_returns_503_when_disabled():
    client, _ = make_client_with_embeddings()  # no embedding_store on state
    r = client.get("/contexts/search?q=test")
    assert r.status_code == 503
    assert r.json()["error"] == "embedding_disabled"


def test_search_endpoint_returns_results_when_enabled(session):
    store = EmbeddingStore(session, model_name="all-MiniLM-L6-v2")
    store._model = make_mock_model()

    client, session = make_client_with_embeddings(store)

    # Create a context and its embedding
    ctx_store = ContextStore(session)
    v = ctx_store.create({"topic": "machine learning"}, owner_device="dev")
    store.generate_and_store(v.context_id, v.version_tag, v.content)

    r = client.get("/contexts/search?q=neural+networks&top_n=5")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
