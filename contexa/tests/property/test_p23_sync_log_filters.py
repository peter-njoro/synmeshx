# Feature: contexa-core, Property 23: Sync Log Filter Correctness
"""
For any combination of filter parameters applied to the Sync_Log query,
every returned entry must satisfy all specified filter conditions, and no
entry satisfying all conditions may be omitted.
Validates: Requirements 12.3
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from contexa.store.database import Base
from contexa.store.models import SyncLogRecord
from contexa.store.context_store import ContextStore
from contexa.store.trust_store import TrustStore
from contexa.sync.crypto import generate_device_identity
from contexa.sync.engine import SyncEngine


STATUSES = ["success", "conflict", "failed", "pending"]
device_ids = st.text(min_size=3, max_size=10, alphabet="abcdefghijklmnop0123456789-")
context_ids = st.text(min_size=3, max_size=10, alphabet="abcdefghijklmnop0123456789-")
version_tags = st.text(min_size=3, max_size=8, alphabet="abcdefghijklmnop0123456789")
statuses = st.sampled_from(STATUSES)


def make_engine_with_logs(entries: list[dict]):
    """Create a SyncEngine with pre-populated sync log entries."""
    db_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=db_engine)
    session = sessionmaker(bind=db_engine)()

    import tempfile, pathlib
    tmp = pathlib.Path(tempfile.mkdtemp())
    identity = generate_device_identity()
    context_store = ContextStore(session)
    trust_store = TrustStore(session, data_dir=tmp)
    trust_store._identity = identity
    engine = SyncEngine(
        session=session,
        context_store=context_store,
        trust_store=trust_store,
        identity=identity,
    )

    for e in entries:
        record = SyncLogRecord(
            log_id=str(uuid.uuid4()),
            device_id=e["device_id"],
            context_id=e["context_id"],
            version_tag=e["version_tag"],
            status=e["status"],
        )
        session.add(record)
    session.commit()

    return engine


@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    entries=st.lists(
        st.fixed_dictionaries({
            "device_id": device_ids,
            "context_id": context_ids,
            "version_tag": version_tags,
            "status": statuses,
        }),
        min_size=1,
        max_size=10,
    ),
    filter_status=st.one_of(st.none(), statuses),
    filter_device=st.one_of(st.none(), device_ids),
)
def test_sync_log_filter_returns_only_matching_entries(entries, filter_status, filter_device):
    """Every returned entry satisfies all filter conditions."""
    engine = make_engine_with_logs(entries)

    results = engine.get_sync_log(
        status=filter_status,
        device_id=filter_device,
    )

    for entry in results:
        if filter_status is not None:
            assert entry.status == filter_status, (
                f"Entry status {entry.status!r} does not match filter {filter_status!r}"
            )
        if filter_device is not None:
            assert entry.device_id == filter_device, (
                f"Entry device_id {entry.device_id!r} does not match filter {filter_device!r}"
            )


@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    entries=st.lists(
        st.fixed_dictionaries({
            "device_id": device_ids,
            "context_id": context_ids,
            "version_tag": version_tags,
            "status": statuses,
        }),
        min_size=1,
        max_size=10,
    ),
    filter_status=statuses,
)
def test_sync_log_filter_omits_no_matching_entries(entries, filter_status):
    """No entry satisfying the filter condition is omitted from results."""
    engine = make_engine_with_logs(entries)

    all_results = engine.get_sync_log()
    filtered_results = engine.get_sync_log(status=filter_status)

    expected_ids = {e.log_id for e in all_results if e.status == filter_status}
    returned_ids = {e.log_id for e in filtered_results}

    assert expected_ids == returned_ids, (
        f"Filter omitted entries: missing={expected_ids - returned_ids}"
    )
