"""
End-to-end sync integration test — "the bar" from docs/TESTING.md.

Spins up ONE real relay server (uvicorn, in a background thread on an ephemeral
port) and TWO in-process devices, each with its own store, engine, and relay
transport. A context created on device A must appear on device B — having
travelled fully encrypted through the relay — with identical content and
checksum. A follow-up update must fast-forward onto B.

This exercises the whole Phase 1 stack together: protocol key exchange, real
X25519 + AES-256-GCM encryption in the engine, the RelaySyncTransport wire, the
RelayClient, and the relay's routing — no mocks, no plaintext shortcut.
"""

from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path
from tempfile import mkdtemp

import httpx
import pytest
import uvicorn
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# The relay is a sibling package with its own venv; make it importable here.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_RELAY_DIR = _REPO_ROOT / "relay"
if str(_RELAY_DIR) not in sys.path:
    sys.path.insert(0, str(_RELAY_DIR))

from contexa.store.database import Base
from contexa.store.context_store import ContextStore
from contexa.store.trust_store import TrustStore
from contexa.store.models import DeviceRecord
from contexa.sync.crypto import generate_device_identity
from contexa.sync.engine import SyncEngine, SyncMode
from contexa.sync.transport import RelaySyncTransport


SHARED_IDENTITY = "shared-user-identity"


# Relay server (real, in a background thread)

def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def relay_url():
    """Run the real relay server on an ephemeral port for the test's duration."""
    from relay.main import app as relay_app
    from relay import main as relay_main

    relay_main.registry._sessions.clear()

    port = _free_port()
    config = uvicorn.Config(relay_app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    # Signal handlers can only be installed in the main thread.
    server.install_signal_handlers = lambda: None

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for the server to accept connections.
    deadline = time.time() + 10.0
    while time.time() < deadline:
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=0.5)
            if r.status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.05)
    else:
        server.should_exit = True
        thread.join(timeout=5)
        pytest.fail("Relay server did not start in time")

    yield f"ws://127.0.0.1:{port}/ws"

    server.should_exit = True
    thread.join(timeout=5)
    relay_main.registry._sessions.clear()


# Device setup

class Device:
    def __init__(self, identity, peer_identity):
        engine_db = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine_db)
        self.session = sessionmaker(bind=engine_db)()

        # Both devices are known to this DB and share one identity_id, so the
        # engine's trust + identity checks pass.
        for ident in (identity, peer_identity):
            self.session.add(DeviceRecord(
                device_id=ident.device_id,
                public_key=ident.public_key_bytes(),
                identity_id=SHARED_IDENTITY,
            ))
        self.session.commit()

        self.identity = identity
        self.store = ContextStore(self.session)
        self.trust = TrustStore(self.session, data_dir=Path(mkdtemp()))
        self.trust.add_trusted(peer_identity.device_id, peer_identity.public_key_bytes())
        self.engine = SyncEngine(
            session=self.session,
            context_store=self.store,
            trust_store=self.trust,
            identity=identity,
            sync_mode=SyncMode.SELF_HOSTED,
        )

    def transport(self, relay_url: str) -> RelaySyncTransport:
        return RelaySyncTransport(
            self.engine,
            relay_url,
            self.identity,
            trust_group_id=SHARED_IDENTITY,
            identity_id=SHARED_IDENTITY,
            response_timeout=10.0,
        )


@pytest.mark.asyncio
async def test_context_syncs_end_to_end_encrypted(relay_url):
    """A context created on A appears, decrypted and intact, on B."""
    id_a = generate_device_identity()
    id_b = generate_device_identity()
    dev_a = Device(id_a, id_b)
    dev_b = Device(id_b, id_a)

    content = {"note": "hello from A", "count": 42}

    async with dev_a.transport(relay_url) as ta, dev_b.transport(relay_url) as tb:
        # Create a context on A, then push it to B.
        created = dev_a.store.create(content, owner_device=id_a.device_id)
        result = await ta.initiate_sync(id_b.device_id)

        assert created.version_id in result.accepted
        assert result.conflicts == []
        assert result.failed == []

        # B now holds the context — decrypted and byte-for-byte intact.
        replicated = dev_b.store.get(created.context_id)
        assert replicated.content == content
        assert replicated.checksum == created.checksum
        assert replicated.version_id == created.version_id

        # An update on A must fast-forward onto B on the next cycle.
        updated_content = {"note": "hello from A", "count": 43}
        updated = dev_a.store.update(created.context_id, updated_content)
        result2 = await ta.initiate_sync(id_b.device_id)

        assert updated.version_id in result2.accepted
        replicated2 = dev_b.store.get(created.context_id)
        assert replicated2.content == updated_content
        assert replicated2.version_id == updated.version_id


@pytest.mark.asyncio
async def test_relay_only_sees_ciphertext(relay_url):
    """Whatever crosses the relay is not the plaintext content."""
    id_a = generate_device_identity()
    id_b = generate_device_identity()
    dev_a = Device(id_a, id_b)
    dev_b = Device(id_b, id_a)

    secret = "TOP-SECRET-MARKER-9f3a"
    content = {"secret": secret}

    captured: list[str] = []

    async with dev_a.transport(relay_url) as ta, dev_b.transport(relay_url) as tb:
        # Capture every payload A hands to the relay — these are exactly the
        # bytes the relay sees and forwards to B.
        original_send = ta._client.send

        async def spy_send(target_device_id, payload_hex):
            captured.append(payload_hex)
            await original_send(target_device_id, payload_hex)

        ta._client.send = spy_send

        created = dev_a.store.create(content, owner_device=id_a.device_id)
        await ta.initiate_sync(id_b.device_id)

        # B decrypted it correctly...
        assert dev_b.store.get(created.context_id).content == content
        # ...but the secret never appeared in the bytes crossing the relay.
        assert captured, "expected A to have sent frames through the relay"
        joined = "".join(captured)
        assert secret not in joined
        assert secret.encode().hex() not in joined
