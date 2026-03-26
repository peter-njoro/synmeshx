"""
Message routing for the relay server.

The router receives an encrypted message addressed to a target device_id,
verifies sender and target are in the same trust group (namespace isolation),
and forwards the raw encrypted bytes to the target's WebSocket.

The relay never decrypts payloads — it only routes bytes.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from relay.session import SessionRegistry

logger = logging.getLogger(__name__)


class MessageRouter:
    """Routes encrypted messages between devices in the same trust group."""

    def __init__(self, registry: SessionRegistry) -> None:
        self._registry = registry

    async def route(
        self,
        sender_device_id: str,
        message_bytes: bytes,
    ) -> tuple[bool, str]:
        """Route a message from sender to its target device.

        The message_bytes must be a JSON envelope:
          {
            "target_device_id": "<uuid>",
            "payload": "<hex-encoded encrypted bytes>"
          }

        Args:
            sender_device_id: The authenticated sender's device_id.
            message_bytes: Raw bytes received from the sender's WebSocket.

        Returns:
            (success: bool, reason: str)
        """
        try:
            envelope = json.loads(message_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False, "invalid_json"

        target_device_id = envelope.get("target_device_id")
        payload = envelope.get("payload")

        if not target_device_id or not payload:
            return False, "missing_fields"

        # Namespace isolation: sender and target must be in the same trust group
        if not self._registry.same_group(sender_device_id, target_device_id):
            logger.warning(
                "Namespace violation: %s → %s (different trust groups)",
                sender_device_id, target_device_id,
            )
            return False, "namespace_violation"

        target_session = self._registry.get_session(target_device_id)
        if target_session is None:
            return False, "target_not_connected"

        # Forward the raw payload bytes — relay never decrypts
        forward_envelope = json.dumps({
            "from_device_id": sender_device_id,
            "payload": payload,
        })

        try:
            await target_session.websocket.send_text(forward_envelope)
            logger.debug("Routed message %s → %s", sender_device_id, target_device_id)
            return True, "ok"
        except Exception as e:
            logger.error("Failed to forward message to %s: %s", target_device_id, e)
            return False, "send_failed"
