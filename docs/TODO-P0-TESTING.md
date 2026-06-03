# TODO — P0 Testing

Actionable checklist for the two highest-priority test gaps from
[TESTING.md](./TESTING.md): the relay client and the relay WebSocket endpoint.
Both sit on the networking + crypto boundary and currently have **zero**
coverage. This is the bar for "sync is tested end-to-end" before any release
that touches sync.

Status: **not started**. Owner: _unassigned_.

---

## Task 1 — `sync/relay_client.py`

**New file:** `contexa/tests/unit/test_relay_client.py`

**Approach:** Drive the async client with a **fake WebSocket** — an async object
with scripted `recv()`/`send()` backed by a queue. No real socket is opened.
Patch `websockets.connect` to return the fake. Reuse the `identity` fixture from
`tests/unit/conftest.py` for the device key pair.

### Setup to write first
- [ ] A `FakeWebSocket` helper: async `recv()` pops from a preloaded inbound
      queue; `send()` appends to a `sent` list; `close()` flips a closed flag;
      supports async context-manager use.
- [ ] A fixture/patch that makes `websockets.connect(url)` return the fake.

### Cases
- [ ] **connect() happy path** — fake sends a `challenge` frame → client signs it
      with its Ed25519 key → sends an auth envelope with `device_id`,
      `trust_group_id`, `public_key_hex`, `signature_hex` → fake replies
      `auth_ok` → `connect()` returns without error and `_ws` is set.
- [ ] **signature is valid** — take the `signature_hex` the client sent and
      verify it against the device public key with `crypto.verify` (verify, don't
      just assert non-empty).
- [ ] **auth_failed** — fake replies `{type: auth_failed, reason: ...}` →
      `connect()` raises `RelayConnectionError` (assert the reason propagates).
- [ ] **transport error on connect** — `websockets.connect` raises / closes
      mid-handshake → wrapped in `RelayConnectionError`, not a raw exception.
- [ ] **send()** — `send(target_device_id, payload_hex)` appends exactly one JSON
      frame with `{target_device_id, payload}` to the fake's `sent` list.
- [ ] **receive()** — preload two inbound frames → async-iterating `receive()`
      yields `{from_device_id, payload}` for each, in order, then stops cleanly
      when the socket closes.
- [ ] **async context manager** — `async with RelayClient(...)` connects on enter
      and disconnects (closes the socket) on exit, even if the body raises.
- [ ] **send/receive before connect** — calling `send()`/`receive()` while
      disconnected raises `RelayConnectionError` (no `None` deref).

---

## Task 2 — relay WebSocket endpoint (`relay/relay/main.py`)

**New file:** `relay/tests/test_ws_endpoint.py`

**Approach:** FastAPI `TestClient`'s `websocket_connect` context manager. The
unit-level pieces (`auth.py`, `session.py`, `router.py`) are already covered —
this tests the `/ws` glue and `/health`. Build real Ed25519 signatures with
`cryptography` so the auth path exercises real verification.

### Setup to write first
- [ ] Helper to mint a device: generate an Ed25519 key pair, return
      `device_id`, `public_key_hex`, and a `sign(challenge_hex) -> signature_hex`
      closure.
- [ ] Helper to run the handshake on a `TestClient` websocket: read the
      `challenge` frame, send a valid (or deliberately invalid) auth envelope,
      return the server's reply.

### Cases
- [ ] **full handshake** — connect → receive `challenge` → send valid signed
      auth → receive `auth_ok`; the device is now in the session registry and
      `/health` `connected` count reflects it.
- [ ] **bad signature** — send auth with a garbage `signature_hex` → server
      replies `auth_failed`, closes the connection, and the device is **not**
      registered.
- [ ] **same-group delivery** — connect two devices sharing a `trust_group_id`;
      device A sends `{target_device_id: B, payload}` → B receives
      `{from_device_id: A, payload}`.
- [ ] **cross-group blocked** — two devices in different trust groups → A's
      message to B yields `error: namespace_violation`; B receives nothing.
- [ ] **target not connected** — message to an unknown/disconnected device →
      `error: target_not_connected`.
- [ ] **malformed frame** — send non-JSON / missing fields after auth →
      `error: invalid_json` / `missing_fields`; the connection stays open.
- [ ] **disconnect unregisters** — after a client disconnects, `/health`
      `connected` count drops and routing to it returns `target_not_connected`.
- [ ] **GET /health** — returns `{status: "ok", connected: <n>}` with the right
      count before/after connections.

---

## Definition of done
- [ ] Both files pass `pytest` offline (no real network, no downloads).
- [ ] No real WebSocket/socket is opened in Task 1; Task 2 uses only the
      in-process `TestClient`.
- [ ] Every server error reason (`auth_failed`, `namespace_violation`,
      `target_not_connected`, `invalid_json`, `missing_fields`) is asserted by
      at least one test.
- [ ] At least one test verifies a real signature / decrypts real ciphertext
      rather than asserting a value is merely present.
- [ ] `contexa` suite: `pytest tests/ -v` green. Relay suite:
      `cd relay && pytest tests/ -v` green.
