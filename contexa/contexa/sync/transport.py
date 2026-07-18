"""
RelaySyncTransport — runs the four-message sync protocol over a RelayClient.

This is the wire that connects the two islands: the SyncEngine (which knows how
to diff, encrypt, and apply contexts) and the RelayClient (which knows how to
move bytes between devices). The engine never touches the network; the relay
client never touches contexts. This module drives one against the other.

Protocol (initiator A ↔ responder B, all frames relayed as opaque bytes):

    A → B: HELLO           (identity + A's ephemeral X25519 public key)
    B → A: KNOWN_VERSIONS  (B's context→version map + B's ephemeral X25519 key)
    A → B: PUSH            (contexts B is missing, AES-256-GCM encrypted)
    B → A: ACK             (accepted / conflict / rejected version_ids)

A single transport plays both roles at once over one relay connection: a
background receive loop dispatches inbound frames by type — HELLO/PUSH drive the
responder side, KNOWN_VERSIONS/ACK feed a pending initiator exchange.
"""

from __future__ import annotations

import asyncio
import logging
import os

from contexa.sync.crypto import (
    generate_x25519_keypair,
    sign,
    x25519_public_key_bytes,
    x25519_public_key_from_bytes,
)
from contexa.sync.engine import SyncEngine, SyncResult
from contexa.sync.protocol import (
    MSG_ACK,
    MSG_HELLO,
    MSG_KNOWN_VERSIONS,
    MSG_PUSH,
    HelloMessage,
    KnownVersionsMessage,
    deserialize,
    serialize,
)
from contexa.sync.relay_client import RelayClient, RelayConnectionError

logger = logging.getLogger(__name__)


class SyncProtocolError(Exception):
    """Raised when a peer sends an unexpected or malformed protocol message."""


class RelaySyncTransport:
    """Drives the sync protocol over a relay connection.

    Usage:
        async with RelaySyncTransport(engine, url, identity, group, identity_id) as t:
            result = await t.initiate_sync(peer_device_id)
    """

    def __init__(
        self,
        engine: SyncEngine,
        relay_url: str,
        identity,
        trust_group_id: str,
        identity_id: str,
        *,
        response_timeout: float = 10.0,
        client: RelayClient | None = None,
    ) -> None:
        self._engine = engine
        self._identity = identity
        self._trust_group_id = trust_group_id
        self._identity_id = identity_id
        self._timeout = response_timeout
        self._client = client or RelayClient(relay_url, identity, trust_group_id)

        self._recv_task: asyncio.Task | None = None
        self._responder_tasks: set[asyncio.Task] = set()
        # Inbound frames are split by the role they belong to, keyed by peer.
        self._initiator_inbox: dict[str, asyncio.Queue] = {}
        self._responder_inbox: dict[str, asyncio.Queue] = {}
        self._started = False

    # Lifecycle

    async def start(self) -> None:
        """Connect to the relay and start dispatching inbound frames."""
        await self._client.connect()
        self._recv_task = asyncio.create_task(self._recv_loop())
        self._started = True

    async def stop(self) -> None:
        """Stop dispatching and disconnect from the relay."""
        if self._recv_task is not None:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
            self._recv_task = None

        for task in list(self._responder_tasks):
            task.cancel()
        self._responder_tasks.clear()

        await self._client.disconnect()
        self._started = False

    async def __aenter__(self) -> "RelaySyncTransport":
        await self.start()
        return self

    async def __aexit__(self, *args) -> None:
        await self.stop()

    # Initiator side

    async def initiate_sync(self, peer_device_id: str) -> SyncResult:
        """Run one full sync cycle against a peer, pushing what it's missing.

        Args:
            peer_device_id: Device_ID of the peer to sync with (must be
                connected to the relay and in the same trust group).

        Returns:
            SyncResult built from the peer's ACK.

        Raises:
            RelayConnectionError: If the transport was never started.
            SyncProtocolError: If the peer replies with the wrong message type.
            asyncio.TimeoutError: If the peer does not respond in time.
        """
        if not self._started:
            raise RelayConnectionError("Transport not started — call start() first")

        local_priv, local_pub = generate_x25519_keypair()

        # The relay already authenticated us, but we still sign a fresh
        # challenge so the peer can bind this exchange to our identity.
        challenge = os.urandom(32)
        signature = sign(self._identity.private_key, challenge)
        hello = HelloMessage(
            device_id=self._identity.device_id,
            identity_id=self._identity_id,
            signature=signature.hex(),
            challenge=challenge.hex(),
            x25519_public_key=x25519_public_key_bytes(local_pub).hex(),
        )

        inbox = self._inbox(self._initiator_inbox, peer_device_id)
        _drain(inbox)
        await self._send(peer_device_id, hello)

        known = await asyncio.wait_for(inbox.get(), self._timeout)
        if known.type != MSG_KNOWN_VERSIONS:
            raise SyncProtocolError(f"Expected KNOWN_VERSIONS, got {known.type}")

        peer_pub = x25519_public_key_from_bytes(
            bytes.fromhex(known.x25519_public_key)
        )
        push = self._engine.build_push(known.versions, peer_pub, local_priv)
        await self._send(peer_device_id, push)

        ack = await asyncio.wait_for(inbox.get(), self._timeout)
        if ack.type != MSG_ACK:
            raise SyncProtocolError(f"Expected ACK, got {ack.type}")

        return SyncResult(
            accepted=list(ack.accepted),
            conflicts=list(ack.conflicts),
            failed=list(ack.rejected),
        )

    # Responder side

    async def _handle_hello(self, peer_device_id: str, hello: HelloMessage) -> None:
        """Respond to an inbound HELLO: send KNOWN_VERSIONS, await PUSH, ACK."""
        try:
            local_priv, local_pub = generate_x25519_keypair()
            known = KnownVersionsMessage(
                versions=self._engine.local_known_versions(),
                x25519_public_key=x25519_public_key_bytes(local_pub).hex(),
            )
            await self._send(peer_device_id, known)

            inbox = self._inbox(self._responder_inbox, peer_device_id)
            push = await asyncio.wait_for(inbox.get(), self._timeout)
            if push.type != MSG_PUSH:
                raise SyncProtocolError(f"Expected PUSH, got {push.type}")

            peer_pub = x25519_public_key_from_bytes(
                bytes.fromhex(hello.x25519_public_key)
            )
            ack = self._engine.apply_push(
                push, peer_pub, local_priv, peer_device_id, hello.identity_id
            )
            await self._send(peer_device_id, ack)
        except asyncio.TimeoutError:
            logger.warning("Responder timed out waiting for PUSH from %s", peer_device_id)
        except Exception as e:  # noqa: BLE001 — a bad peer must not kill the loop
            logger.error("Responder error handling %s: %s", peer_device_id, e)

    # Internals

    async def _send(self, target_device_id: str, msg) -> None:
        await self._client.send(target_device_id, serialize(msg).hex())

    async def _recv_loop(self) -> None:
        """Dispatch inbound relay frames to the initiator or responder side."""
        try:
            async for envelope in self._client.receive():
                from_dev = envelope.get("from_device_id")
                payload = envelope.get("payload")
                if not from_dev or not payload:
                    continue
                try:
                    msg = deserialize(bytes.fromhex(payload))
                except Exception as e:  # noqa: BLE001
                    logger.warning("Dropping undecodable frame from %s: %s", from_dev, e)
                    continue

                mtype = getattr(msg, "type", None)
                if mtype == MSG_HELLO:
                    task = asyncio.create_task(self._handle_hello(from_dev, msg))
                    self._responder_tasks.add(task)
                    task.add_done_callback(self._responder_tasks.discard)
                elif mtype == MSG_PUSH:
                    self._inbox(self._responder_inbox, from_dev).put_nowait(msg)
                elif mtype in (MSG_KNOWN_VERSIONS, MSG_ACK):
                    self._inbox(self._initiator_inbox, from_dev).put_nowait(msg)
                else:
                    logger.warning("Unexpected message %s from %s", mtype, from_dev)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.error("Relay receive loop stopped: %s", e)

    @staticmethod
    def _inbox(mapping: dict[str, asyncio.Queue], device_id: str) -> asyncio.Queue:
        queue = mapping.get(device_id)
        if queue is None:
            queue = asyncio.Queue()
            mapping[device_id] = queue
        return queue


def _drain(queue: asyncio.Queue) -> None:
    """Discard any stale frames left from a previous exchange."""
    while not queue.empty():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            break
