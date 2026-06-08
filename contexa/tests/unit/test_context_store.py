"""
Unit tests for ContextStore.
Covers CRUD lifecycle, versioning, checksum integrity, label updates,
not-found errors, and version history retrieval.
Requirements: 2.1–2.8, 3.1–3.5
"""

from __future__ import annotations

import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from contexa.store.database import Base
from contexa.store.context_store import (
    ContextStore,
    ContextSummary,
    ContextVersion,
    ChecksumError,
    NotFoundError,
)


# Fixtures

@pytest.fixture
def session():
    """In-memory SQLite session for each test."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    yield db
    db.close()


@pytest.fixture
def store(session):
    return ContextStore(session)


DEVICE = "device-001"
CONTENT = {"task": "write tests", "status": "in_progress"}


# Create

def test_create_returns_context_version(store):
    v = store.create(CONTENT, owner_device=DEVICE)
    assert isinstance(v, ContextVersion)
    assert v.content == CONTENT
    assert len(v.checksum) == 64  # SHA-256 hex
    assert v.parent_version is None
    assert v.label is None


def test_create_with_label(store):
    v = store.create(CONTENT, owner_device=DEVICE, label="my-task")
    assert v.label == "my-task"


def test_create_computes_correct_checksum(store):
    import hashlib
    v = store.create(CONTENT, owner_device=DEVICE)
    expected = hashlib.sha256(
        json.dumps(CONTENT, sort_keys=True).encode()
    ).hexdigest()
    assert v.checksum == expected


# Get (latest)

def test_get_returns_latest_version(store):
    v1 = store.create(CONTENT, owner_device=DEVICE)
    v2 = store.update(v1.context_id, {"status": "done"})
    fetched = store.get(v1.context_id)
    assert fetched.version_id == v2.version_id
    assert fetched.content == {"status": "done"}


def test_get_by_version_tag(store):
    v1 = store.create(CONTENT, owner_device=DEVICE)
    store.update(v1.context_id, {"status": "done"})
    fetched = store.get(v1.context_id, version_tag=v1.version_tag)
    assert fetched.version_id == v1.version_id
    assert fetched.content == CONTENT


def test_get_missing_context_raises_not_found(store):
    with pytest.raises(NotFoundError) as exc:
        store.get("nonexistent-id")
    assert exc.value.context_id == "nonexistent-id"


def test_get_missing_version_tag_raises_not_found(store):
    v = store.create(CONTENT, owner_device=DEVICE)
    with pytest.raises(NotFoundError) as exc:
        store.get(v.context_id, version_tag="badtag")
    assert exc.value.version_tag == "badtag"


# Update (new version)

def test_update_creates_new_version(store):
    v1 = store.create(CONTENT, owner_device=DEVICE)
    v2 = store.update(v1.context_id, {"status": "done"})
    assert v2.version_id != v1.version_id
    assert v2.version_tag != v1.version_tag
    assert v2.parent_version == v1.version_id


def test_update_preserves_old_version(store):
    v1 = store.create(CONTENT, owner_device=DEVICE)
    store.update(v1.context_id, {"status": "done"})
    old = store.get(v1.context_id, version_tag=v1.version_tag)
    assert old.content == CONTENT


def test_update_missing_context_raises_not_found(store):
    with pytest.raises(NotFoundError):
        store.update("nonexistent-id", {"x": 1})


# Version history

def test_list_versions_returns_all_in_order(store):
    v1 = store.create(CONTENT, owner_device=DEVICE)
    v2 = store.update(v1.context_id, {"step": 2})
    v3 = store.update(v1.context_id, {"step": 3})
    versions = store.list_versions(v1.context_id)
    assert len(versions) == 3
    assert [v.version_id for v in versions] == [v1.version_id, v2.version_id, v3.version_id]


def test_list_versions_missing_context_raises_not_found(store):
    with pytest.raises(NotFoundError):
        store.list_versions("nonexistent-id")


# List all

def test_list_all_returns_all_contexts(store):
    store.create({"a": 1}, owner_device=DEVICE)
    store.create({"b": 2}, owner_device=DEVICE)
    store.create({"c": 3}, owner_device=DEVICE)
    summaries = store.list_all()
    assert len(summaries) == 3
    assert all(isinstance(s, ContextSummary) for s in summaries)


def test_list_all_empty(store):
    assert store.list_all() == []


def test_list_all_includes_label(store):
    store.create({"x": 1}, owner_device=DEVICE, label="labelled")
    store.create({"y": 2}, owner_device=DEVICE)
    summaries = store.list_all()
    labels = {s.label for s in summaries}
    assert "labelled" in labels
    assert None in labels


# Delete

def test_delete_removes_context(store):
    v = store.create(CONTENT, owner_device=DEVICE)
    store.delete(v.context_id)
    with pytest.raises(NotFoundError):
        store.get(v.context_id)


def test_delete_missing_context_raises_not_found(store):
    with pytest.raises(NotFoundError):
        store.delete("nonexistent-id")


def test_delete_removes_from_list(store):
    v = store.create(CONTENT, owner_device=DEVICE)
    store.delete(v.context_id)
    assert store.list_all() == []


# Label update (no new version)

def test_update_label_does_not_create_version(store):
    v = store.create(CONTENT, owner_device=DEVICE)
    store.update_label(v.context_id, "new-label")
    versions = store.list_versions(v.context_id)
    assert len(versions) == 1  # still only one version


def test_update_label_persists(store):
    v = store.create(CONTENT, owner_device=DEVICE)
    store.update_label(v.context_id, "renamed")
    fetched = store.get(v.context_id)
    assert fetched.label == "renamed"


def test_update_label_can_be_cleared(store):
    v = store.create(CONTENT, owner_device=DEVICE, label="initial")
    store.update_label(v.context_id, None)
    fetched = store.get(v.context_id)
    assert fetched.label is None


def test_update_label_missing_context_raises_not_found(store):
    with pytest.raises(NotFoundError):
        store.update_label("nonexistent-id", "label")


# Checksum integrity

def test_checksum_tamper_detected(store, session):
    from contexa.store.models import ContextVersionRecord
    v = store.create(CONTENT, owner_device=DEVICE)

    # Tamper with the stored content directly in the DB
    record = session.query(ContextVersionRecord).filter_by(
        version_id=v.version_id
    ).first()
    record.content = '{"tampered": true}'
    session.commit()

    with pytest.raises(ChecksumError) as exc:
        store.get(v.context_id)
    assert exc.value.context_id == v.context_id


# Serialisation round-trip (Req 3.5)

def test_content_round_trip(store):
    """Arbitrary JSON content survives a write → read cycle unchanged."""
    content = {
        "nested": {"list": [1, 2, 3], "flag": True},
        "unicode": "héllo wörld",
        "number": 3.14,
    }
    v = store.create(content, owner_device=DEVICE)
    fetched = store.get(v.context_id)
    assert fetched.content == content
