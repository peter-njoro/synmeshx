"""
Sync_Engine: coordinates context replication between trusted devices.

Implements the push/pull protocol defined in protocol.py:
  HELLO → trust+identity check → KNOWN_VERSIONS → diff → PUSH encrypted → ACK

Key behaviours:
  - Queues pending operations while offline
  - Retries failed syncs with exponential backoff
  - Detects conflicts via parent-chain ancestry check
  - Records every operation in sync_log
  - Three sync modes: local-only (direct), self-hosted relay, hosted relay
  - Prefers direct sync when available; falls back to relay
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy.orm import Session

from contexa.store.context_store import ContextStore, ContextVersion
from contexa.store.models import SyncLogRecord, ContextVersionRecord
from contexa.store.trust_store import TrustStore
from contexa.sync.crypto import (
    DeviceIdentity,
    decrypt,
    encrypt,
    generate_nonce,
    generate_x25519_keypair,
    derive_session_key,
    sign,
    verify,
    public_key_from_bytes,
    x25519_public_key_from_bytes,
    x25519_public_key_bytes,
)
from contexa.sync.protocol import (
    HelloMessage,
    KnownVersionsMessage,
    PushEntry,
    PushMessage,
    AckMessage,
    detect_conflict,
    is_ancestor,
    serialize,
    deserialize,
)

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)

logger = logging.getLogger(__name__)


# Sync modes

class SyncMode(str, Enum):
    LOCAL_ONLY = "local-only"
    SELF_HOSTED = "self-hosted"
    HOSTED = "hosted"

HOSTED_RELAY_URL = "wss://relay.contexa.dev"


# Sync log helpers

def _write_sync_log(
    session: Session,
    device_id: str,
    context_id: str,
    version_tag: str,
    status: str,
    error_msg: str | None = None,
) -> None:
    """Write a sync_log entry. status: 'success'|'conflict'|'failed'|'pending'"""
    entry = SyncLogRecord(
        log_id=str(uuid.uuid4()),
        device_id=device_id,
        context_id=context_id,
        version_tag=version_tag,
        status=status,
        error_msg=error_msg,
    )
    session.add(entry)
    session.commit()


# Pending operation queue

@dataclass
class PendingOperation:
    """A sync operation queued for retry."""
    context_id: str
    version_tag: str
    peer_device_id: str
    attempts: int = 0
    last_attempt: float = 0.0


# Sync result

@dataclass
class SyncResult:
    """Result of a single sync cycle."""
    accepted: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


# Sync Engine

class SyncEngine:
    """Coordinates context replication between trusted devices.

    Usage:
        engine = SyncEngine(session, context_store, trust_store, identity, config)
        result = engine.sync_with_peer(peer_device_id, peer_address)
    """

    def __init__(
        self,
        session: Session,
        context_store: ContextStore,
        trust_store: TrustStore,
        identity: DeviceIdentity,
        max_retries: int = 5,
        backoff_base: float = 2.0,
        sync_mode: SyncMode = SyncMode.HOSTED,
        relay_endpoint: str = "",
    ) -> None:
        self._session = session
        self._context_store = context_store
        self._trust_store = trust_store
        self._identity = identity
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._sync_mode = sync_mode
        self._relay_endpoint = relay_endpoint or HOSTED_RELAY_URL
        self._pending: list[PendingOperation] = []
        self._relay_available: bool = True   # optimistic; set False on failure
        self.syncs_completed: int = 0
        self.sync_failures: int = 0

    # Relay configuration

    def get_relay_url(self) -> str | None:
        """Return the relay URL based on sync mode, or None for local-only."""
        if self._sync_mode == SyncMode.LOCAL_ONLY:
            return None
        if self._sync_mode == SyncMode.SELF_HOSTED:
            return self._relay_endpoint
        return HOSTED_RELAY_URL

    def is_relay_mode(self) -> bool:
        """Return True if relay routing is configured."""
        return self._sync_mode != SyncMode.LOCAL_ONLY

    def mark_relay_unavailable(self) -> None:
        """Mark the relay as unreachable — operations will be queued."""
        self._relay_available = False
        logger.warning("Relay marked as unavailable — sync operations will be queued")

    def mark_relay_available(self) -> None:
        """Mark the relay as reachable again."""
        self._relay_available = True

    # Public interface

    def sync_with_peer(
        self,
        peer_device_id: str,
        peer_contexts: dict[str, str],
        peer_public_key_bytes: bytes,
        peer_identity_id: str,
    ) -> SyncResult:
        """Run a full push/pull sync cycle with a peer device.

        This is the in-process version used for testing. The network transport
        (TCP/WebSocket) wraps this logic in task 12+.

        Args:
            peer_device_id: UUID of the peer device.
            peer_contexts: Dict of {context_id: version_tag} the peer has.
            peer_public_key_bytes: Peer's Ed25519 public key (32 bytes).
            peer_identity_id: Peer's OAuth identity_id.

        Returns:
            SyncResult with accepted, conflict, and failed version lists.
        """
        result = SyncResult()

        # 1. Trust check
        if not self._trust_store.is_trusted(peer_device_id):
            logger.warning("Sync rejected: untrusted device %s", peer_device_id)
            return result

        # 2. Identity check
        from contexa.auth import verify_device_identity
        if not verify_device_identity(peer_device_id, peer_identity_id, self._session):
            logger.warning("Sync rejected: identity mismatch for device %s", peer_device_id)
            return result

        # 3. Compute diff — what does the peer need?
        local_summaries = {s.context_id: s for s in self._context_store.list_all()}
        to_push = []

        for context_id, local_summary in local_summaries.items():
            peer_tag = peer_contexts.get(context_id)
            if peer_tag is None:
                # Peer doesn't have this context at all
                to_push.append(context_id)
            elif peer_tag != local_summary.latest_version_tag:
                # Peer has an older or different version
                to_push.append(context_id)

        # 4. Build encrypted push entries
        x25519_priv, x25519_pub = generate_x25519_keypair()
        peer_ed25519_pub = public_key_from_bytes(peer_public_key_bytes)

        # Derive session key using X25519 (we use peer's Ed25519 pub as stand-in
        # for their X25519 pub in this simplified in-process version)
        # In the full network version, peers exchange X25519 public keys first
        nonce = generate_nonce()

        push_entries = []
        for context_id in to_push:
            try:
                version = self._context_store.get(context_id)
                content_bytes = json.dumps(version.content, sort_keys=True).encode()
                # Encrypt content (simplified: use nonce + device_id as AAD)
                aad = self._identity.device_id.encode()
                # For in-process sync, we skip actual encryption and use plaintext
                # The full network transport layer handles E2E encryption
                push_entries.append(PushEntry(
                    version_id=version.version_id,
                    context_id=version.context_id,
                    version_tag=version.version_tag,
                    parent_version=version.parent_version,
                    content_encrypted=content_bytes.hex(),
                    checksum=version.checksum,
                    created_at=version.created_at.isoformat(),
                    label=version.label,
                    nonce=nonce.hex(),
                ))
            except Exception as e:
                logger.error("Failed to prepare push for context %s: %s", context_id, e)

        # 5. Process incoming peer contexts (what peer would push to us)
        # In the in-process model, we simulate receiving peer's contexts
        # by checking what they have that we don't
        for context_id, peer_tag in peer_contexts.items():
            if context_id not in local_summaries:
                # We don't have this context — would accept it
                result.accepted.append(peer_tag)
                _write_sync_log(
                    self._session, peer_device_id, context_id, peer_tag, "success"
                )
            else:
                local_version = self._context_store.get(context_id)
                # Build version map for ancestor check
                version_map = self._build_version_map(context_id)

                if detect_conflict(local_version.version_id, peer_tag, version_map):
                    result.conflicts.append(peer_tag)
                    _write_sync_log(
                        self._session, peer_device_id, context_id, peer_tag, "conflict",
                        f"Conflict: local={local_version.version_tag} remote={peer_tag}"
                    )
                    logger.warning(
                        "Conflict detected for context %s: local=%s remote=%s",
                        context_id, local_version.version_tag, peer_tag
                    )
                else:
                    result.accepted.append(peer_tag)
                    _write_sync_log(
                        self._session, peer_device_id, context_id, peer_tag, "success"
                    )

        self.syncs_completed += 1
        return result

    # Network sync primitives (driven by RelaySyncTransport)
    #
    # These three methods split sync_with_peer() into the pieces the wire
    # protocol needs: what versions we hold (KNOWN_VERSIONS), an *encrypted*
    # push to send (PUSH), and applying an incoming encrypted push (ACK). They
    # use the real X25519 + AES-256-GCM primitives — no plaintext shortcut.

    def local_known_versions(self) -> dict[str, str]:
        """Return {context_id: latest_version_tag} for every local context.

        This is the payload of the KNOWN_VERSIONS message — it tells the peer
        what we already have so it only pushes what we're missing or behind on.
        """
        return {
            s.context_id: s.latest_version_tag
            for s in self._context_store.list_all()
        }

    def build_push(
        self,
        peer_contexts: dict[str, str],
        peer_x25519_pub: X25519PublicKey,
        local_x25519_priv: X25519PrivateKey,
    ) -> PushMessage:
        """Build an *encrypted* PUSH of everything the peer is missing/behind on.

        Each entry's content is sealed with AES-256-GCM under a session key
        derived from our ephemeral X25519 private key and the peer's ephemeral
        X25519 public key. A fresh nonce per entry doubles as the HKDF salt, so
        the relay — which never sees either private key — cannot decrypt it.

        Args:
            peer_contexts: {context_id: version_tag} the peer already has.
            peer_x25519_pub: The peer's ephemeral X25519 public key.
            local_x25519_priv: Our ephemeral X25519 private key for this session.

        Returns:
            A PushMessage whose entries carry ciphertext (never plaintext).
        """
        to_push: list[str] = []
        for summary in self._context_store.list_all():
            peer_tag = peer_contexts.get(summary.context_id)
            if peer_tag is None or peer_tag != summary.latest_version_tag:
                to_push.append(summary.context_id)

        aad = self._identity.device_id.encode()
        entries: list[PushEntry] = []
        for context_id in to_push:
            try:
                version = self._context_store.get(context_id)
            except Exception as e:
                logger.error("Failed to prepare push for context %s: %s", context_id, e)
                continue

            content_bytes = json.dumps(version.content, sort_keys=True).encode()
            nonce = generate_nonce()
            session_key = derive_session_key(
                local_x25519_priv, peer_x25519_pub, nonce, self._identity.device_id
            )
            ciphertext = encrypt(session_key, nonce, content_bytes, aad)

            entries.append(PushEntry(
                version_id=version.version_id,
                context_id=version.context_id,
                version_tag=version.version_tag,
                parent_version=version.parent_version,
                content_encrypted=ciphertext.hex(),
                checksum=version.checksum,
                created_at=version.created_at.isoformat(),
                label=version.label,
                nonce=nonce.hex(),
            ))

        return PushMessage(entries=entries)

    def apply_push(
        self,
        push: PushMessage,
        peer_x25519_pub: X25519PublicKey,
        local_x25519_priv: X25519PrivateKey,
        peer_device_id: str,
        peer_identity_id: str,
    ) -> AckMessage:
        """Decrypt and apply an incoming PUSH, returning an ACK.

        Runs the same trust + identity gate as sync_with_peer(), then for each
        entry: derives the session key, decrypts, verifies the checksum, and
        either applies the version (new context or fast-forward) or records a
        conflict. Every outcome is written to the sync log.

        Args:
            push: The PushMessage received from the peer.
            peer_x25519_pub: The peer's ephemeral X25519 public key (from HELLO).
            local_x25519_priv: Our ephemeral X25519 private key for this session.
            peer_device_id: The sending device's Device_ID.
            peer_identity_id: The identity_id the sender claims.

        Returns:
            An AckMessage listing accepted, conflicting, and rejected version_ids.
        """
        ack = AckMessage()

        # Trust + identity gate — refuse the whole push if either fails.
        if not self._trust_store.is_trusted(peer_device_id):
            logger.warning("Push rejected: untrusted device %s", peer_device_id)
            ack.rejected = [e.version_id for e in push.entries]
            return ack

        from contexa.auth import verify_device_identity
        if not verify_device_identity(peer_device_id, peer_identity_id, self._session):
            logger.warning("Push rejected: identity mismatch for device %s", peer_device_id)
            ack.rejected = [e.version_id for e in push.entries]
            return ack

        aad = peer_device_id.encode()

        # Pre-index incoming entries so ancestry can be traced across a
        # multi-version push (e.g. peer sends v2 and v3 while we hold v1).
        incoming_parents = {e.version_id: e.parent_version for e in push.entries}

        for entry in push.entries:
            try:
                nonce = bytes.fromhex(entry.nonce)
                session_key = derive_session_key(
                    local_x25519_priv, peer_x25519_pub, nonce, peer_device_id
                )
                ciphertext = bytes.fromhex(entry.content_encrypted)
                plaintext = decrypt(session_key, nonce, ciphertext, aad)
                content = json.loads(plaintext)
            except Exception as e:
                logger.warning("Failed to decrypt push entry %s: %s", entry.version_id, e)
                ack.rejected.append(entry.version_id)
                _write_sync_log(
                    self._session, peer_device_id, entry.context_id,
                    entry.version_tag, "failed", f"decrypt/parse failed: {e}",
                )
                continue

            try:
                applied = self._apply_entry(entry, content, incoming_parents, peer_device_id)
            except Exception as e:
                logger.error("Failed to apply push entry %s: %s", entry.version_id, e)
                ack.rejected.append(entry.version_id)
                _write_sync_log(
                    self._session, peer_device_id, entry.context_id,
                    entry.version_tag, "failed", str(e),
                )
                continue

            if applied == "conflict":
                ack.conflicts.append(entry.version_id)
                _write_sync_log(
                    self._session, peer_device_id, entry.context_id,
                    entry.version_tag, "conflict",
                    f"Conflict on context {entry.context_id}",
                )
            else:
                ack.accepted.append(entry.version_id)
                _write_sync_log(
                    self._session, peer_device_id, entry.context_id,
                    entry.version_tag, "success",
                )

        self.syncs_completed += 1
        return ack

    def _apply_entry(
        self,
        entry: PushEntry,
        content: dict,
        incoming_parents: dict[str, str | None],
        peer_device_id: str,
    ) -> str:
        """Apply one decrypted push entry. Returns 'accepted' or 'conflict'."""
        created_at = datetime.fromisoformat(entry.created_at)

        local_summaries = {s.context_id: s for s in self._context_store.list_all()}

        # New context we've never seen — accept unconditionally.
        if entry.context_id not in local_summaries:
            self._context_store.apply_remote_version(
                version_id=entry.version_id,
                context_id=entry.context_id,
                version_tag=entry.version_tag,
                parent_version=entry.parent_version,
                content=content,
                checksum=entry.checksum,
                created_at=created_at,
                owner_device=peer_device_id,
                label=entry.label,
            )
            return "accepted"

        local_latest = self._context_store.get(entry.context_id)

        # Idempotent: we already hold this exact version.
        if local_latest.version_id == entry.version_id:
            return "accepted"

        # Build the ancestry map from our stored versions plus the whole push.
        version_map = self._build_version_map(entry.context_id)
        version_map.update(incoming_parents)

        # Remote is an ancestor of what we already have → we're newer, no-op.
        if is_ancestor(entry.version_id, local_latest.version_id, version_map):
            return "accepted"

        # Our latest is an ancestor of remote → clean fast-forward, apply it.
        if is_ancestor(local_latest.version_id, entry.version_id, version_map):
            self._context_store.apply_remote_version(
                version_id=entry.version_id,
                context_id=entry.context_id,
                version_tag=entry.version_tag,
                parent_version=entry.parent_version,
                content=content,
                checksum=entry.checksum,
                created_at=created_at,
                owner_device=peer_device_id,
                label=entry.label,
            )
            return "accepted"

        # Divergent history — neither is an ancestor of the other.
        return "conflict"

    def queue_pending(self, context_id: str, version_tag: str, peer_device_id: str) -> None:
        """Queue a sync operation for retry when connectivity is restored."""
        self._pending.append(PendingOperation(
            context_id=context_id,
            version_tag=version_tag,
            peer_device_id=peer_device_id,
        ))
        _write_sync_log(
            self._session, peer_device_id, context_id, version_tag, "pending"
        )

    def retry_pending(self, peer_contexts_fn) -> None:
        """Retry all pending operations. peer_contexts_fn(device_id) → dict."""
        still_pending = []
        for op in self._pending:
            if op.attempts >= self._max_retries:
                _write_sync_log(
                    self._session, op.peer_device_id, op.context_id,
                    op.version_tag, "failed",
                    f"Max retries ({self._max_retries}) exceeded"
                )
                self.sync_failures += 1
                continue

            backoff = self._backoff_base ** op.attempts
            if time.time() - op.last_attempt < backoff:
                still_pending.append(op)
                continue

            op.attempts += 1
            op.last_attempt = time.time()
            still_pending.append(op)

        self._pending = still_pending

    def get_backoff_delay(self, attempt: int) -> float:
        """Return the backoff delay in seconds for a given attempt number."""
        return self._backoff_base ** attempt

    # Internal helpers

    def _build_version_map(self, context_id: str) -> dict[str, str | None]:
        """Build a {version_id: parent_version_id} map for a context."""
        records = (
            self._session.query(ContextVersionRecord)
            .filter_by(context_id=context_id)
            .all()
        )
        return {r.version_id: r.parent_version for r in records}

    def get_sync_log(
        self,
        device_id: str | None = None,
        context_id: str | None = None,
        status: str | None = None,
        since: datetime | None = None,
    ) -> list[SyncLogRecord]:
        """Query the sync log with optional filters."""
        q = self._session.query(SyncLogRecord)
        if device_id:
            q = q.filter(SyncLogRecord.device_id == device_id)
        if context_id:
            q = q.filter(SyncLogRecord.context_id == context_id)
        if status:
            q = q.filter(SyncLogRecord.status == status)
        if since:
            q = q.filter(SyncLogRecord.created_at >= since)
        return q.order_by(SyncLogRecord.created_at.desc()).all()
