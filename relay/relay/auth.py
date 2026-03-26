"""
Relay authentication: Ed25519 signature verification.

The relay uses device-centric auth — no OAuth, no user accounts.
Each device signs a challenge with its Ed25519 private key.
The relay verifies the signature using the device's public key.

Auth flow:
  1. Device connects via WebSocket
  2. Relay sends a random challenge (32 bytes, hex-encoded)
  3. Device signs the challenge and sends back:
     {device_id, public_key_hex, signature_hex}
  4. Relay verifies signature — rejects if invalid
"""

from __future__ import annotations

import os
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature


def generate_challenge() -> bytes:
    """Generate a cryptographically random 32-byte challenge."""
    return os.urandom(32)


def verify_challenge_response(
    challenge: bytes,
    device_id: str,
    public_key_hex: str,
    signature_hex: str,
) -> bool:
    """Verify a device's signed challenge response.

    Args:
        challenge: The original challenge bytes sent to the device.
        device_id: The device_id the device claims.
        public_key_hex: Hex-encoded 32-byte Ed25519 public key.
        signature_hex: Hex-encoded 64-byte Ed25519 signature.

    Returns:
        True if the signature is valid, False otherwise.
    """
    try:
        public_key_bytes = bytes.fromhex(public_key_hex)
        signature = bytes.fromhex(signature_hex)

        if len(public_key_bytes) != 32:
            return False
        if len(signature) != 64:
            return False

        public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        public_key.verify(signature, challenge)
        return True
    except (InvalidSignature, ValueError, Exception):
        return False
