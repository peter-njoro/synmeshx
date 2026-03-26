"""
Ephemeral session registry for the relay server.

Tracks which devices are currently connected and their WebSocket connections.
State is in-memory only — lost on restart. No persistence.

Devices are grouped by trust_group_id (their shared identity_id) to enforce
namespace isolation: messages can only be routed within the same trust group.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DeviceSession:
    """An active device connection."""
    device_id: str
    trust_group_id: str      # identity_id — groups devices belonging to same user
    public_key_hex: str
    websocket: Any           # WebSocket connection object


class SessionRegistry:
    """In-memory registry of active device sessions."""

    def __init__(self) -> None:
        # device_id → DeviceSession
        self._sessions: dict[str, DeviceSession] = {}

    def register(
        self,
        device_id: str,
        trust_group_id: str,
        public_key_hex: str,
        websocket: Any,
    ) -> DeviceSession:
        """Register a new device session."""
        session = DeviceSession(
            device_id=device_id,
            trust_group_id=trust_group_id,
            public_key_hex=public_key_hex,
            websocket=websocket,
        )
        self._sessions[device_id] = session
        return session

    def unregister(self, device_id: str) -> None:
        """Remove a device session on disconnect."""
        self._sessions.pop(device_id, None)

    def get_session(self, device_id: str) -> DeviceSession | None:
        """Return the session for a device, or None if not connected."""
        return self._sessions.get(device_id)

    def get_group(self, trust_group_id: str) -> list[DeviceSession]:
        """Return all sessions belonging to a trust group."""
        return [
            s for s in self._sessions.values()
            if s.trust_group_id == trust_group_id
        ]

    def is_connected(self, device_id: str) -> bool:
        """Return True if the device has an active session."""
        return device_id in self._sessions

    def same_group(self, device_id_a: str, device_id_b: str) -> bool:
        """Return True if both devices are in the same trust group."""
        session_a = self._sessions.get(device_id_a)
        session_b = self._sessions.get(device_id_b)
        if session_a is None or session_b is None:
            return False
        return session_a.trust_group_id == session_b.trust_group_id

    @property
    def connected_count(self) -> int:
        return len(self._sessions)
