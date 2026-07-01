"""
Unit tests for the relay client (contexa/sync/relay_client.py).

These tests drive the async client against a *fake* WebSocket — an async
object with a scripted inbound queue and a captured `sent` list. No real
socket is ever opened; `websockets.connect` is patched to return the fake.

Covered: the auth handshake (challenge -> signed auth -> auth_ok), signature
validity, auth failure, transport failure, send()/receive() framing, the
async context-manager, and the before-connect guards.
"""

from __future__ import annotations

import json
from collections import deque

import pytest
from websockets.exceptions import WebSocketException

from contexa.sync import relay_client
from contexa.sync.crypto import verify
from contexa.sync.relay_client import RelayClient, RelayConnectionError


# Fake WebSocket

class FakeWebSocket:
    """A stand-in for a `websockets` client connection.

    - `recv()` pops the next frame from a preloaded inbound queue.
    - `send()` appends the outbound frame to `sent`.
    - `close()` flips `closed`.
    - async-iterating the object yields inbound frames until the queue is
      empty (mirrors the server closing the stream), which is how
      `RelayClient.receive()` consumes messages.
    """

    def __init__(self, inbound=None):
        self.inbound = deque(inbound or [])
        self.sent = []
        self.closed = False

    async def recv(self):
        if not self.inbound:
            raise WebSocketException("recv on empty/closed fake socket")
        return self.inbound.popleft()

    async def send(self, data):
        self.sent.append(data)

    async def close(self):
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.inbound:
            raise StopAsyncIteration
        return self.inbound.popleft()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()


def patch_connect(monkeypatch, result):
    """Patch `websockets.connect` used by relay_client.

    If `result` is an exception instance/class it is raised (to simulate a
    transport failure); otherwise it is returned as the connection object.
    """

    async def fake_connect(url):
        if isinstance(result, BaseException) or (
            isinstance(result, type) and issubclass(result, BaseException)
        ):
            raise result
        return result

    monkeypatch.setattr(relay_client.websockets, "connect", fake_connect)


def challenge_frame(challenge_hex: str) -> str:
    return json.dumps({"type": "challenge", "challenge": challenge_hex})


CHALLENGE_HEX = "ab" * 32  # 32 deterministic challenge bytes


# connect() — happy path

@pytest.mark.asyncio
async def test_connect_happy_path(monkeypatch, identity):
    ws = FakeWebSocket(inbound=[
        challenge_frame(CHALLENGE_HEX),
        json.dumps({"type": "auth_ok"}),
    ])
    patch_connect(monkeypatch, ws)

    client = RelayClient("ws://relay.test/ws", identity, "group-A")
    await client.connect()

    # Connection is live.
    assert client._ws is ws

    # Exactly one auth envelope was sent, carrying the expected fields.
    assert len(ws.sent) == 1
    auth = json.loads(ws.sent[0])
    assert auth["type"] == "auth"
    assert auth["device_id"] == identity.device_id
    assert auth["trust_group_id"] == "group-A"
    assert auth["public_key_hex"] == identity.public_key_bytes().hex()
    assert "signature_hex" in auth


@pytest.mark.asyncio
async def test_connect_signature_is_valid(monkeypatch, identity):
    """The signature the client sends really verifies against its public key."""
    ws = FakeWebSocket(inbound=[
        challenge_frame(CHALLENGE_HEX),
        json.dumps({"type": "auth_ok"}),
    ])
    patch_connect(monkeypatch, ws)

    client = RelayClient("ws://relay.test/ws", identity, "group-A")
    await client.connect()

    auth = json.loads(ws.sent[0])
    signature = bytes.fromhex(auth["signature_hex"])
    challenge = bytes.fromhex(CHALLENGE_HEX)

    # Real Ed25519 verification, not a "field is present" check.
    assert verify(identity.public_key, challenge, signature) is True
    # And it must NOT verify against a different message.
    assert verify(identity.public_key, b"not-the-challenge", signature) is False


# connect() — failure paths

@pytest.mark.asyncio
async def test_connect_auth_failed_propagates_reason(monkeypatch, identity):
    ws = FakeWebSocket(inbound=[
        challenge_frame(CHALLENGE_HEX),
        json.dumps({"type": "auth_failed", "reason": "invalid_signature"}),
    ])
    patch_connect(monkeypatch, ws)

    client = RelayClient("ws://relay.test/ws", identity, "group-A")
    with pytest.raises(RelayConnectionError) as excinfo:
        await client.connect()
    assert "invalid_signature" in str(excinfo.value)


@pytest.mark.asyncio
async def test_connect_transport_error_is_wrapped(monkeypatch, identity):
    patch_connect(monkeypatch, OSError("connection refused"))

    client = RelayClient("ws://relay.test/ws", identity, "group-A")
    with pytest.raises(RelayConnectionError) as excinfo:
        await client.connect()
    assert "Cannot connect to relay" in str(excinfo.value)


@pytest.mark.asyncio
async def test_connect_wrong_first_frame_is_rejected(monkeypatch, identity):
    ws = FakeWebSocket(inbound=[json.dumps({"type": "auth_ok"})])  # no challenge
    patch_connect(monkeypatch, ws)

    client = RelayClient("ws://relay.test/ws", identity, "group-A")
    with pytest.raises(RelayConnectionError):
        await client.connect()


# send()

@pytest.mark.asyncio
async def test_send_emits_single_envelope(monkeypatch, identity):
    ws = FakeWebSocket(inbound=[
        challenge_frame(CHALLENGE_HEX),
        json.dumps({"type": "auth_ok"}),
    ])
    patch_connect(monkeypatch, ws)

    client = RelayClient("ws://relay.test/ws", identity, "group-A")
    await client.connect()
    ws.sent.clear()  # drop the auth frame; we only care about the data frame

    await client.send("target-dev-123", "deadbeef")

    assert len(ws.sent) == 1
    envelope = json.loads(ws.sent[0])
    assert envelope == {"target_device_id": "target-dev-123", "payload": "deadbeef"}


@pytest.mark.asyncio
async def test_send_before_connect_raises(identity):
    client = RelayClient("ws://relay.test/ws", identity, "group-A")
    with pytest.raises(RelayConnectionError):
        await client.send("target-dev-123", "deadbeef")


# receive()

@pytest.mark.asyncio
async def test_receive_yields_frames_in_order(monkeypatch, identity):
    ws = FakeWebSocket(inbound=[
        challenge_frame(CHALLENGE_HEX),
        json.dumps({"type": "auth_ok"}),
    ])
    patch_connect(monkeypatch, ws)

    client = RelayClient("ws://relay.test/ws", identity, "group-A")
    await client.connect()

    # Preload two inbound data frames; iteration stops when the queue drains.
    ws.inbound.append(json.dumps({"from_device_id": "dev-A", "payload": "aa"}))
    ws.inbound.append(json.dumps({"from_device_id": "dev-B", "payload": "bb"}))

    received = [msg async for msg in client.receive()]

    assert received == [
        {"from_device_id": "dev-A", "payload": "aa"},
        {"from_device_id": "dev-B", "payload": "bb"},
    ]


@pytest.mark.asyncio
async def test_receive_before_connect_raises(identity):
    client = RelayClient("ws://relay.test/ws", identity, "group-A")
    with pytest.raises(RelayConnectionError):
        async for _ in client.receive():
            pass


# async context manager

@pytest.mark.asyncio
async def test_context_manager_connects_and_closes(monkeypatch, identity):
    ws = FakeWebSocket(inbound=[
        challenge_frame(CHALLENGE_HEX),
        json.dumps({"type": "auth_ok"}),
    ])
    patch_connect(monkeypatch, ws)

    async with RelayClient("ws://relay.test/ws", identity, "group-A") as client:
        assert client._ws is ws  # connected on enter

    assert ws.closed is True      # closed on exit
    assert client._ws is None


@pytest.mark.asyncio
async def test_context_manager_closes_on_error(monkeypatch, identity):
    ws = FakeWebSocket(inbound=[
        challenge_frame(CHALLENGE_HEX),
        json.dumps({"type": "auth_ok"}),
    ])
    patch_connect(monkeypatch, ws)

    with pytest.raises(RuntimeError):
        async with RelayClient("ws://relay.test/ws", identity, "group-A"):
            raise RuntimeError("boom")

    # Disconnect ran despite the exception in the body.
    assert ws.closed is True
