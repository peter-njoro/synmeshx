# Feature: contexa-core, Property 24: SDK Round-Trip
"""
For any valid Context object created via ContexaClient.create_context(),
calling ContexaClient.get_context() with the returned context_id must
return an equivalent Context object with the same content and checksum.
Validates: Requirements 13.2, 13.9
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from contexa.api.app import create_app
from contexa.config import ContexaConfig
from contexa.sdk import ContexaClient
from contexa.store.context_store import ContextStore
from contexa.store.database import Base
from contexa.store.embedding_store import EmbeddingStore
from contexa.store.trust_store import TrustStore
from contexa.sync.crypto import generate_device_identity
from contexa.sync.engine import SyncEngine


json_dicts = st.dictionaries(
    st.text(min_size=1, max_size=10),
    st.one_of(st.integers(min_value=-100, max_value=100), st.text(max_size=20)),
    min_size=1,
    max_size=5,
)


def make_sdk():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()

    import tempfile, pathlib
    tmp = pathlib.Path(tempfile.mkdtemp())
    identity = generate_device_identity()
    context_store = ContextStore(session)
    trust_store = TrustStore(session, data_dir=tmp)
    trust_store._identity = identity
    sync_engine = SyncEngine(
        session=session, context_store=context_store,
        trust_store=trust_store, identity=identity,
    )

    app = create_app()
    app.state.context_store = context_store
    app.state.trust_store = trust_store
    app.state.embedding_store = EmbeddingStore(session, model_name="")
    app.state.sync_engine = sync_engine
    app.state.config = ContexaConfig()
    app.state.device_id = identity.device_id
    app.state.start_time = time.time()
    app.state.syncs_completed = 0
    app.state.sync_failures = 0

    http_client = TestClient(app, raise_server_exceptions=False)
    sdk = ContexaClient()

    def patched_get(url, **kwargs):
        path = url.replace("http://127.0.0.1:7474", "")
        r = http_client.get(path)
        m = MagicMock()
        m.status_code = r.status_code
        m.json.return_value = r.json()
        m.text = r.text
        return m

    def patched_post(url, **kwargs):
        path = url.replace("http://127.0.0.1:7474", "")
        r = http_client.post(path, json=kwargs.get("json", {}))
        m = MagicMock()
        m.status_code = r.status_code
        m.json.return_value = r.json()
        m.text = r.text
        return m

    return sdk, patched_get, patched_post


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(content=json_dicts)
def test_sdk_create_get_round_trip(content):
    """create_context() then get_context() returns equivalent content and checksum."""
    sdk, patched_get, patched_post = make_sdk()

    with patch("httpx.get", side_effect=patched_get), \
         patch("httpx.post", side_effect=patched_post):

        created = sdk.create_context(content)
        fetched = sdk.get_context(created["context_id"])

        assert fetched["content"] == content
        assert fetched["checksum"] == created["checksum"]
        assert fetched["context_id"] == created["context_id"]
        assert fetched["version_tag"] == created["version_tag"]
