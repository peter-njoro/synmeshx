"""
Message routing logic for the Contexa relay server.
Receives encrypted messages addressed to a target device_id, verifies
namespace isolation (same trust group), and forwards raw bytes to the
target WebSocket without decrypting the payload.
"""
