"""
Unit tests for the relay server.
Tests auth, routing, namespace isolation, and session management.
Requirements: 9.9–9.14
"""

from __future__ import annotations

import json
import os
import pytest

from relay.auth import generate_challenge, verify_challenge_response
from relay.session import SessionRegistry
from relay.router import MessageRouter

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


# Helpers

def make_device():
    """Generate a test device with Ed25519 key pair."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    from cryptography.hazmat.primitives import serialization
    pub_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return private_key, pub_bytes


def sign_challenge(private_key, challenge: bytes) -> str:
    return private_key.sign(challenge).hex()


# Auth — challenge/response

def test_generate_challenge_is_32_bytes():
    challenge = generate_challenge()
    assert len(challenge) == 32


def test_generate_challenge_is_random():
    c1 = generate_challenge()
    c2 = generate_challenge()
    assert c1 != c2


def test_valid_signature_is_accepted():
    private_key, pub_bytes = make_device()
    challenge = generate_challenge()
    signature_hex = sign_challenge(private_key, challenge)

    assert verify_challenge_response(
        challenge=challenge,
        device_id="dev-001",
        public_key_hex=pub_bytes.hex(),
        signature_hex=signature_hex,
    )


def test_invalid_signature_is_rejected():
    private_key, pub_bytes = make_device()
    challenge = generate_challenge()
    wrong_sig = os.urandom(64).hex()  # random bytes, not a valid signature

    assert not verify_challenge_response(
        challenge=challenge,
        device_id="dev-001",
        public_key_hex=pub_bytes.hex(),
        signature_hex=wrong_sig,
    )


def test_wrong_key_is_rejected():
    private_key_a, pub_bytes_a = make_device()
    private_key_b, pub_bytes_b = make_device()
    challenge = generate_challenge()

    # Sign with key A but verify with key B
    signature_hex = sign_challenge(private_key_a, challenge)

    assert not verify_challenge_response(
        challenge=challenge,
        device_id="dev-001",
        public_key_hex=pub_bytes_b.hex(),  # wrong key
        signature_hex=signature_hex,
    )


def test_tampered_challenge_is_rejected():
    private_key, pub_bytes = make_device()
    challenge = generate_challenge()
    signature_hex = sign_challenge(private_key, challenge)

    tampered = bytes([b ^ 0xFF for b in challenge])  # flip all bits

    assert not verify_challenge_response(
        challenge=tampered,
        device_id="dev-001",
        public_key_hex=pub_bytes.hex(),
        signature_hex=signature_hex,
    )


def test_short_public_key_is_rejected():
    challenge = generate_challenge()
    assert not verify_challenge_response(
        challenge=challenge,
        device_id="dev-001",
        public_key_hex="deadbeef",  # too short
        signature_hex="00" * 64,
    )


# Session registry

class MockWebSocket:
    def __init__(self):
        self.sent = []

    async def send_text(self, text):
        self.sent.append(text)


def test_register_and_get_session():
    registry = SessionRegistry()
    ws = MockWebSocket()
    registry.register("dev-001", "group-A", "pubkey-hex", ws)

    session = registry.get_session("dev-001")
    assert session is not None
    assert session.device_id == "dev-001"
    assert session.trust_group_id == "group-A"


def test_unregister_removes_session():
    registry = SessionRegistry()
    ws = MockWebSocket()
    registry.register("dev-001", "group-A", "pubkey-hex", ws)
    registry.unregister("dev-001")
    assert registry.get_session("dev-001") is None


def test_is_connected():
    registry = SessionRegistry()
    ws = MockWebSocket()
    assert not registry.is_connected("dev-001")
    registry.register("dev-001", "group-A", "pubkey-hex", ws)
    assert registry.is_connected("dev-001")


def test_same_group_true():
    registry = SessionRegistry()
    registry.register("dev-001", "group-A", "key1", MockWebSocket())
    registry.register("dev-002", "group-A", "key2", MockWebSocket())
    assert registry.same_group("dev-001", "dev-002")


def test_same_group_false_different_groups():
    registry = SessionRegistry()
    registry.register("dev-001", "group-A", "key1", MockWebSocket())
    registry.register("dev-002", "group-B", "key2", MockWebSocket())
    assert not registry.same_group("dev-001", "dev-002")


def test_same_group_false_one_not_connected():
    registry = SessionRegistry()
    registry.register("dev-001", "group-A", "key1", MockWebSocket())
    assert not registry.same_group("dev-001", "dev-999")


def test_get_group_returns_all_in_group():
    registry = SessionRegistry()
    registry.register("dev-001", "group-A", "key1", MockWebSocket())
    registry.register("dev-002", "group-A", "key2", MockWebSocket())
    registry.register("dev-003", "group-B", "key3", MockWebSocket())

    group_a = registry.get_group("group-A")
    assert len(group_a) == 2
    assert all(s.trust_group_id == "group-A" for s in group_a)


# Router — namespace isolation

@pytest.mark.asyncio
async def test_router_delivers_to_same_group():
    registry = SessionRegistry()
    ws_a = MockWebSocket()
    ws_b = MockWebSocket()
    registry.register("dev-001", "group-A", "key1", ws_a)
    registry.register("dev-002", "group-A", "key2", ws_b)

    router = MessageRouter(registry)
    message = json.dumps({
        "target_device_id": "dev-002",
        "payload": "deadbeef",
    }).encode()

    success, reason = await router.route("dev-001", message)
    assert success
    assert reason == "ok"
    assert len(ws_b.sent) == 1
    forwarded = json.loads(ws_b.sent[0])
    assert forwarded["from_device_id"] == "dev-001"
    assert forwarded["payload"] == "deadbeef"


@pytest.mark.asyncio
async def test_router_blocks_cross_group_message():
    """Messages between devices in different trust groups are blocked."""
    registry = SessionRegistry()
    ws_a = MockWebSocket()
    ws_b = MockWebSocket()
    registry.register("dev-001", "group-A", "key1", ws_a)
    registry.register("dev-002", "group-B", "key2", ws_b)

    router = MessageRouter(registry)
    message = json.dumps({
        "target_device_id": "dev-002",
        "payload": "deadbeef",
    }).encode()

    success, reason = await router.route("dev-001", message)
    assert not success
    assert reason == "namespace_violation"
    assert len(ws_b.sent) == 0  # target received nothing


@pytest.mark.asyncio
async def test_router_rejects_target_not_connected():
    registry = SessionRegistry()
    ws_a = MockWebSocket()
    registry.register("dev-001", "group-A", "key1", ws_a)

    router = MessageRouter(registry)
    message = json.dumps({
        "target_device_id": "dev-999",  # not connected
        "payload": "deadbeef",
    }).encode()

    success, reason = await router.route("dev-001", message)
    assert not success
    # An unconnected device can't be in the same group, so namespace_violation is correct
    assert reason in ("namespace_violation", "target_not_connected")


@pytest.mark.asyncio
async def test_router_rejects_invalid_json():
    registry = SessionRegistry()
    ws_a = MockWebSocket()
    registry.register("dev-001", "group-A", "key1", ws_a)

    router = MessageRouter(registry)
    success, reason = await router.route("dev-001", b"not json")
    assert not success
    assert reason == "invalid_json"
