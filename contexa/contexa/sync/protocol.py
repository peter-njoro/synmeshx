"""
Sync protocol message types and ancestor-chain conflict detection.

The sync protocol follows a push/pull cycle:
  1. HELLO     — initiator identifies itself with a signed challenge
  2. KNOWN_VERSIONS — responder sends its latest version_tag per context_id
  3. PUSH      — initiator sends contexts the responder is missing/behind on
  4. ACK       — responder confirms accepted versions and reports conflicts

Conflict detection uses parent-chain ancestry:
  - If B's version IS an ancestor of A's version → fast-forward (accept A)
  - If neither is an ancestor of the other → CONFLICT (keep both)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any


# Message types

MSG_HELLO = "HELLO"
MSG_KNOWN_VERSIONS = "KNOWN_VERSIONS"
MSG_PUSH = "PUSH"
MSG_ACK = "ACK"


@dataclass
class HelloMessage:
    """Sent by the initiating device to identify itself."""
    type: str = MSG_HELLO
    device_id: str = ""
    identity_id: str = ""
    signature: str = ""      # hex-encoded Ed25519 signature of challenge
    challenge: str = ""      # hex-encoded random bytes that were signed


@dataclass
class KnownVersionsMessage:
    """Sent by the responder: maps context_id → latest version_tag it has."""
    type: str = MSG_KNOWN_VERSIONS
    versions: dict[str, str] = field(default_factory=dict)
    # versions = {"<context_id>": "<version_tag>", ...}


@dataclass
class PushEntry:
    """A single context version being pushed."""
    version_id: str
    context_id: str
    version_tag: str
    parent_version: str | None
    content_encrypted: str   # hex-encoded AES-256-GCM ciphertext
    checksum: str
    created_at: str          # ISO-8601
    label: str | None = None
    nonce: str = ""          # hex-encoded 12-byte nonce


@dataclass
class PushMessage:
    """Sent by the initiator: list of context versions to replicate."""
    type: str = MSG_PUSH
    entries: list[PushEntry] = field(default_factory=list)


@dataclass
class AckMessage:
    """Sent by the responder after processing a PUSH."""
    type: str = MSG_ACK
    accepted: list[str] = field(default_factory=list)    # version_ids accepted
    conflicts: list[str] = field(default_factory=list)   # version_ids in conflict
    rejected: list[str] = field(default_factory=list)    # version_ids rejected (auth/integrity)


# Serialization

def serialize(msg: Any) -> bytes:
    """Serialize a protocol message to JSON bytes."""
    return json.dumps(asdict(msg)).encode()


def deserialize(data: bytes) -> Any:
    """Deserialize JSON bytes into the appropriate message dataclass."""
    obj = json.loads(data)
    msg_type = obj.get("type")
    if msg_type == MSG_HELLO:
        return HelloMessage(**obj)
    if msg_type == MSG_KNOWN_VERSIONS:
        return KnownVersionsMessage(**obj)
    if msg_type == MSG_PUSH:
        entries = [PushEntry(**e) for e in obj.get("entries", [])]
        return PushMessage(type=msg_type, entries=entries)
    if msg_type == MSG_ACK:
        return AckMessage(**obj)
    raise ValueError(f"Unknown message type: {msg_type}")


# Ancestor-chain conflict detection

def is_ancestor(
    candidate_version_id: str,
    descendant_version_id: str,
    version_map: dict[str, str | None],
) -> bool:
    """Check if candidate_version_id is an ancestor of descendant_version_id.

    Walks the parent chain of descendant_version_id upward until either:
      - candidate_version_id is found (True — it IS an ancestor)
      - the chain ends at None (False — not an ancestor)

    Args:
        candidate_version_id: The version_id to search for as an ancestor.
        descendant_version_id: The version_id to start walking from.
        version_map: Maps version_id → parent_version_id (None for root).

    Returns:
        True if candidate is an ancestor of descendant, False otherwise.
    """
    current = descendant_version_id
    visited = set()

    while current is not None:
        if current in visited:
            break  # cycle guard
        visited.add(current)

        if current == candidate_version_id:
            return True

        current = version_map.get(current)

    return False


def detect_conflict(
    local_version_id: str,
    remote_version_id: str,
    version_map: dict[str, str | None],
) -> bool:
    """Return True if local and remote versions are in conflict.

    A conflict exists when neither version is an ancestor of the other —
    meaning both devices independently modified the same context.

    Args:
        local_version_id: The version_id this device has.
        remote_version_id: The version_id the peer is pushing.
        version_map: Maps version_id → parent_version_id for all known versions.

    Returns:
        True if conflict, False if one is a fast-forward of the other.
    """
    # If remote is a descendant of local → fast-forward, accept remote
    if is_ancestor(local_version_id, remote_version_id, version_map):
        return False

    # If local is a descendant of remote → local is newer, no update needed
    if is_ancestor(remote_version_id, local_version_id, version_map):
        return False

    # Neither is an ancestor of the other → conflict
    return True
