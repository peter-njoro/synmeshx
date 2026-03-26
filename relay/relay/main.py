"""
Contexa Relay Server — stateless WebSocket message broker.

The relay authenticates devices via Ed25519 signed challenges,
then routes encrypted messages between devices in the same trust group.
It never decrypts payloads and maintains no long-term state.

WebSocket protocol:
  1. Client connects to /ws
  2. Server sends: {"type": "challenge", "challenge": "<hex>"}
  3. Client sends: {
       "type": "auth",
       "device_id": "<uuid>",
       "trust_group_id": "<identity_id>",
       "public_key_hex": "<hex>",
       "signature_hex": "<hex>"
     }
  4. Server sends: {"type": "auth_ok"} or {"type": "auth_failed", "reason": "..."}
  5. Client sends messages: {
       "target_device_id": "<uuid>",
       "payload": "<hex-encoded encrypted bytes>"
     }
  6. Server routes to target or sends: {"type": "error", "reason": "..."}

HTTP endpoints:
  GET /health  — returns {"status": "ok", "connected": <count>}
"""

from __future__ import annotations

import json
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from relay.auth import generate_challenge, verify_challenge_response
from relay.router import MessageRouter
from relay.session import SessionRegistry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Contexa Relay",
    description="Stateless WebSocket message broker for Contexa device sync",
    version="0.1.0",
)

# Global session registry and router (in-memory, reset on restart)
registry = SessionRegistry()
router = MessageRouter(registry)


@app.get("/health")
async def health():
    """Return relay health status."""
    return {"status": "ok", "connected": registry.connected_count}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for device connections."""
    await websocket.accept()

    # Step 1: Send challenge
    challenge = generate_challenge()
    await websocket.send_text(json.dumps({
        "type": "challenge",
        "challenge": challenge.hex(),
    }))

    # Step 2: Receive auth response
    try:
        auth_data = json.loads(await websocket.receive_text())
    except (WebSocketDisconnect, json.JSONDecodeError):
        await websocket.close(code=1008)
        return

    if auth_data.get("type") != "auth":
        await websocket.send_text(json.dumps({"type": "auth_failed", "reason": "expected_auth"}))
        await websocket.close(code=1008)
        return

    device_id = auth_data.get("device_id", "")
    trust_group_id = auth_data.get("trust_group_id", "")
    public_key_hex = auth_data.get("public_key_hex", "")
    signature_hex = auth_data.get("signature_hex", "")

    # Step 3: Verify signature
    if not verify_challenge_response(challenge, device_id, public_key_hex, signature_hex):
        await websocket.send_text(json.dumps({"type": "auth_failed", "reason": "invalid_signature"}))
        await websocket.close(code=1008)
        logger.warning("Auth failed for device %s", device_id)
        return

    # Step 4: Register session
    registry.register(device_id, trust_group_id, public_key_hex, websocket)
    await websocket.send_text(json.dumps({"type": "auth_ok"}))
    logger.info("Device %s connected (group: %s)", device_id, trust_group_id)

    # Step 5: Message loop
    try:
        while True:
            raw = await websocket.receive_bytes()
            success, reason = await router.route(device_id, raw)
            if not success:
                await websocket.send_text(json.dumps({"type": "error", "reason": reason}))
    except WebSocketDisconnect:
        pass
    finally:
        registry.unregister(device_id)
        logger.info("Device %s disconnected", device_id)
