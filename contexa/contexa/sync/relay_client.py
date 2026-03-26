"""
Relay client for the Contexa sync engine.

Handles WebSocket connection to the relay server, authentication,
and sending/receiving encrypted sync messages.

The relay client is used by the SyncEngine when sync_mode is
'self-hosted' or 'hosted'. For 'local-only', it is not used.
"""

from __future__ import annotations

import json
import logging
from typing import AsyncIterator

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from contexa.sync.crypto import DeviceIdentity, sign

logger = logging.getLogger(__name__)


class RelayConnectionError(Exception):
    """Raised when the relay is unreachable or auth fails."""
    pass


class RelayClient:
    """WebSocket client for the Contexa relay server.

    Usage:
        async with RelayClient(url, identity, trust_group_id) as client:
            await client.send(target_device_id, encrypted_payload_hex)
            async for msg in client.receive():
                ...
    """

    def __init__(
        self,
        relay_url: str,
        identity: DeviceIdentity,
        trust_group_id: str,
    ) -> None:
        self._url = relay_url
        self._identity = identity
        self._trust_group_id = trust_group_id
        self._ws = None

    async def connect(self) -> None:
        """Connect to the relay and complete the auth challenge."""
        try:
            self._ws = await websockets.connect(self._url)
        except (OSError, WebSocketException) as e:
            raise RelayConnectionError(f"Cannot connect to relay {self._url}: {e}") from e

        # Receive challenge
        try:
            raw = await self._ws.recv()
            msg = json.loads(raw)
        except Exception as e:
            raise RelayConnectionError(f"Failed to receive challenge: {e}") from e

        if msg.get("type") != "challenge":
            raise RelayConnectionError(f"Expected challenge, got: {msg.get('type')}")

        challenge = bytes.fromhex(msg["challenge"])

        # Sign the challenge
        signature = sign(self._identity.private_key, challenge)

        # Send auth response
        auth_msg = json.dumps({
            "type": "auth",
            "device_id": self._identity.device_id,
            "trust_group_id": self._trust_group_id,
            "public_key_hex": self._identity.public_key_bytes().hex(),
            "signature_hex": signature.hex(),
        })
        await self._ws.send(auth_msg)

        # Receive auth result
        try:
            result = json.loads(await self._ws.recv())
        except Exception as e:
            raise RelayConnectionError(f"Failed to receive auth result: {e}") from e

        if result.get("type") != "auth_ok":
            reason = result.get("reason", "unknown")
            raise RelayConnectionError(f"Relay auth failed: {reason}")

        logger.info("Connected to relay %s as device %s", self._url, self._identity.device_id)

    async def disconnect(self) -> None:
        """Close the WebSocket connection."""
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def send(self, target_device_id: str, encrypted_payload_hex: str) -> None:
        """Send an encrypted payload to a target device via the relay.

        Args:
            target_device_id: UUID of the destination device.
            encrypted_payload_hex: Hex-encoded AES-256-GCM ciphertext.
        """
        if self._ws is None:
            raise RelayConnectionError("Not connected to relay")

        envelope = json.dumps({
            "target_device_id": target_device_id,
            "payload": encrypted_payload_hex,
        }).encode()

        try:
            await self._ws.send(envelope)
        except (ConnectionClosed, WebSocketException) as e:
            raise RelayConnectionError(f"Failed to send via relay: {e}") from e

    async def receive(self) -> AsyncIterator[dict]:
        """Async generator yielding incoming messages from the relay.

        Each yielded dict has:
          - from_device_id: str
          - payload: str (hex-encoded encrypted bytes)
        """
        if self._ws is None:
            raise RelayConnectionError("Not connected to relay")

        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                    if "from_device_id" in msg and "payload" in msg:
                        yield msg
                    elif msg.get("type") == "error":
                        logger.warning("Relay error: %s", msg.get("reason"))
                except json.JSONDecodeError:
                    logger.warning("Received non-JSON message from relay")
        except (ConnectionClosed, WebSocketException):
            pass

    async def __aenter__(self) -> "RelayClient":
        await self.connect()
        return self

    async def __aexit__(self, *args) -> None:
        await self.disconnect()
