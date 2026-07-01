"""
Integration tests for the relay WebSocket endpoint (relay/main.py).

These exercise the `/ws` glue and `/health` through FastAPI's in-process
`TestClient` — no real network. The auth path runs against *real* Ed25519
signatures built with `cryptography`, so a valid handshake proves real
verification rather than a stubbed check.

The unit pieces (auth.py, session.py, router.py) are covered separately in
test_relay.py; this file is about the endpoint wiring.

NOTE on `target_not_connected`: the router checks `same_group()` *before*
looking up the target session, and `same_group()` is False whenever either
device is absent. So a message to an unknown/disconnected device surfaces as
`namespace_violation`, never `target_not_connected` — the latter is currently
unreachable through the endpoint. The tests below assert the behavior the code
actually produces.
"""

from __future__ import annotations

import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from relay import main
from relay.main import app


@pytest.fixture(autouse=True)
def clean_registry():
    """The relay's session registry is a module global; reset it per test."""
    main.registry._sessions.clear()
    yield
    main.registry._sessions.clear()


@pytest.fixture
def client():
    return TestClient(app)


# Device / handshake helpers

def mint_device(device_id: str):
    """Generate an Ed25519 device. Returns (info dict, sign closure)."""
    private_key = Ed25519PrivateKey.generate()
    public_key_hex = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()

    def sign(challenge_hex: str) -> str:
        return private_key.sign(bytes.fromhex(challenge_hex)).hex()

    return {"device_id": device_id, "public_key_hex": public_key_hex}, sign


def handshake(ws, device, trust_group_id: str, sign, *, corrupt=False):
    """Run challenge -> auth on an open TestClient websocket, return the reply.

    If `corrupt` is True, send a garbage signature instead of a real one.
    """
    challenge_msg = ws.receive_json()
    assert challenge_msg["type"] == "challenge"

    signature_hex = sign(challenge_msg["challenge"])
    if corrupt:
        signature_hex = "00" * 64  # valid length, wrong signature

    ws.send_text(json.dumps({
        "type": "auth",
        "device_id": device["device_id"],
        "trust_group_id": trust_group_id,
        "public_key_hex": device["public_key_hex"],
        "signature_hex": signature_hex,
    }))
    return ws.receive_json()


# /health

def test_health_reports_ok_and_zero(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "connected": 0}


# Full handshake

def test_full_handshake_registers_device(client):
    device, sign = mint_device("dev-A")
    with client.websocket_connect("/ws") as ws:
        reply = handshake(ws, device, "group-1", sign)
        assert reply == {"type": "auth_ok"}
        # Device is now in the registry and /health reflects it.
        assert client.get("/health").json()["connected"] == 1


def test_bad_signature_is_rejected_and_not_registered(client):
    device, sign = mint_device("dev-A")
    with client.websocket_connect("/ws") as ws:
        reply = handshake(ws, device, "group-1", sign, corrupt=True)
        assert reply == {"type": "auth_failed", "reason": "invalid_signature"}
    # Never registered.
    assert client.get("/health").json()["connected"] == 0


def test_non_auth_first_frame_is_rejected(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()  # challenge
        ws.send_text(json.dumps({"type": "not_auth"}))
        reply = ws.receive_json()
        assert reply == {"type": "auth_failed", "reason": "expected_auth"}
    assert client.get("/health").json()["connected"] == 0


# Routing

def test_same_group_delivery(client):
    dev_a, sign_a = mint_device("dev-A")
    dev_b, sign_b = mint_device("dev-B")

    with client.websocket_connect("/ws") as ws_a, \
         client.websocket_connect("/ws") as ws_b:
        assert handshake(ws_a, dev_a, "group-1", sign_a)["type"] == "auth_ok"
        assert handshake(ws_b, dev_b, "group-1", sign_b)["type"] == "auth_ok"
        assert client.get("/health").json()["connected"] == 2

        ws_a.send_bytes(json.dumps({
            "target_device_id": "dev-B",
            "payload": "cafe",
        }).encode())

        forwarded = ws_b.receive_json()
        assert forwarded == {"from_device_id": "dev-A", "payload": "cafe"}


def test_cross_group_is_blocked(client):
    dev_a, sign_a = mint_device("dev-A")
    dev_b, sign_b = mint_device("dev-B")

    with client.websocket_connect("/ws") as ws_a, \
         client.websocket_connect("/ws") as ws_b:
        handshake(ws_a, dev_a, "group-1", sign_a)
        handshake(ws_b, dev_b, "group-2", sign_b)  # different trust group

        ws_a.send_bytes(json.dumps({
            "target_device_id": "dev-B",
            "payload": "cafe",
        }).encode())

        # A gets the violation error; B receives nothing.
        err = ws_a.receive_json()
        assert err == {"type": "error", "reason": "namespace_violation"}


def test_message_to_unknown_target(client):
    """Unknown target surfaces as namespace_violation (see module docstring)."""
    dev_a, sign_a = mint_device("dev-A")
    with client.websocket_connect("/ws") as ws_a:
        handshake(ws_a, dev_a, "group-1", sign_a)
        ws_a.send_bytes(json.dumps({
            "target_device_id": "ghost",
            "payload": "cafe",
        }).encode())
        err = ws_a.receive_json()
        assert err == {"type": "error", "reason": "namespace_violation"}


# Malformed frames keep the connection open

def test_invalid_json_frame(client):
    dev_a, sign_a = mint_device("dev-A")
    with client.websocket_connect("/ws") as ws_a:
        handshake(ws_a, dev_a, "group-1", sign_a)

        ws_a.send_bytes(b"this is not json")
        assert ws_a.receive_json() == {"type": "error", "reason": "invalid_json"}

        # Connection still usable afterwards.
        ws_a.send_bytes(b"still not json")
        assert ws_a.receive_json() == {"type": "error", "reason": "invalid_json"}


def test_missing_fields_frame(client):
    dev_a, sign_a = mint_device("dev-A")
    with client.websocket_connect("/ws") as ws_a:
        handshake(ws_a, dev_a, "group-1", sign_a)

        # Valid JSON but no target_device_id/payload.
        ws_a.send_bytes(json.dumps({"payload": "cafe"}).encode())
        assert ws_a.receive_json() == {"type": "error", "reason": "missing_fields"}


# Disconnect bookkeeping

def test_disconnect_unregisters(client):
    dev_a, sign_a = mint_device("dev-A")
    with client.websocket_connect("/ws") as ws_a:
        handshake(ws_a, dev_a, "group-1", sign_a)
        assert client.get("/health").json()["connected"] == 1

    # After the context exits, the device is gone.
    assert client.get("/health").json()["connected"] == 0

    # Routing to the now-disconnected device fails (namespace_violation,
    # since same_group() is False for an absent target).
    dev_b, sign_b = mint_device("dev-B")
    with client.websocket_connect("/ws") as ws_b:
        handshake(ws_b, dev_b, "group-1", sign_b)
        ws_b.send_bytes(json.dumps({
            "target_device_id": "dev-A",
            "payload": "cafe",
        }).encode())
        assert ws_b.receive_json() == {"type": "error", "reason": "namespace_violation"}
