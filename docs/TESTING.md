# Contexa — Unit Test Plan

This is a plan for the project's test suite: how tests are structured today,
what is already covered, where the gaps are, and a prioritized plan for filling
them. See [DESIGN.md](./DESIGN.md) for the system being tested.

> **Starting point:** Contexa already ships a substantial suite — **~195 unit
> tests** across 12 files, **~41 Hypothesis property tests** across 26 files,
> and **18 relay tests**. This plan builds on that rather than starting from
> scratch. Treat the "gaps" sections as the actual work to do.

---

## 1. Tooling & conventions

| Tool | Use |
|------|-----|
| `pytest` (≥8) | Test runner. `testpaths = ["tests"]`. |
| `pytest-asyncio` | Async tests. Configured `asyncio_mode = "auto"` — `async def` tests run without an explicit marker. |
| `hypothesis` (≥6) | Property-based tests under `tests/property/`. |
| `httpx` / FastAPI `TestClient` | Exercise the local API in-process. |
| `typer.testing.CliRunner` | Drive CLI commands. |
| `unittest.mock` | `patch` / `MagicMock` for HTTP, file I/O, and the embeddings model. |

**Conventions to keep:**

- **In-memory SQLite per test**: `create_engine("sqlite:///:memory:",
  connect_args={"check_same_thread": False}, poolclass=StaticPool)`. Fast,
  isolated, no temp files for DB.
- **`tmp_path`** for anything that must touch the filesystem (device keys,
  config files, identity tokens).
- **Mock the embedding model** — never download `sentence-transformers` weights
  in a test. Use a `MagicMock` that returns deterministic vectors seeded from a
  hash of the input.
- **Function-scoped fixtures** for isolation. Property tests that take
  function-scoped fixtures must set
  `suppress_health_check=[HealthCheck.function_scoped_fixture]`.
- Keep unit tests **offline and deterministic** — no real network, no real
  clock dependence, no real relay.

### Running

```bash
cd contexa
uv sync

pytest tests/ -v                              # everything
pytest tests/unit/ -v                         # unit only
pytest tests/property/ -v --hypothesis-seed=0 # property, reproducible
pytest tests/unit/test_sync_engine.py -v      # one file

cd ../relay && uv sync && pytest tests/ -v    # relay suite
```

Once coverage gaps are addressed, add `pytest-cov` and gate CI on a coverage
floor (see §6).

---

## 2. Current coverage map

| Module | Unit tests | Property tests | State |
|--------|-----------|----------------|-------|
| `store/context_store.py` | `test_context_store.py` (24) | p01–p08, p26 | **Strong** |
| `store/trust_store.py` | via `test_device_identity.py` | p09, p11 | **Strong** |
| `store/embedding_store.py` | `test_embeddings.py` (13, mocked) | p18, p19 | **Good** |
| `store/models.py` / `database.py` | indirect | indirect | Adequate |
| `sync/crypto.py` | `test_device_identity.py` (24) | p10, p17 | **Strong** |
| `sync/engine.py` | `test_sync_engine.py` (22) | p12–p16, p23 | **Strong** |
| `sync/protocol.py` | `test_sync_engine.py` | p01, p14 | **Good** |
| `sync/relay_client.py` | — | — | **GAP — none** |
| `api/app.py` + `api/routes/*` | `test_local_api.py` (23) | p06, p08 | **Strong** |
| `cli/main.py` + `cli/commands/*` | `test_cli.py` (18) | — | **Good** (via runner) |
| `cli/client.py` | indirect | — | Thin |
| `sdk/client.py` + `exceptions.py` | `test_sdk.py` (19) | p24, p25 | **Strong** |
| `config.py` | `test_config.py` (8) | p20, p21 | **Strong** |
| `auth.py` | `test_auth.py` (16) | p12 | **Strong** |
| `logging.py` | via `test_observability.py` | p22 | Thin (no direct test) |
| `daemon.py` | `test_daemon_lifecycle.py` (9) | — | **Good** |
| **relay** `auth/session/router` | `relay/test_relay.py` (18) | — | **Good** (units) |
| **relay** `main.py` (WS handshake) | — | — | **GAP — none** |

---

## 3. Prioritized gaps

### P0 — `sync/relay_client.py` (zero coverage, networking + crypto)

The async relay client is untested and sits on the security boundary. Add
`tests/unit/test_relay_client.py` driven by a **fake WebSocket** (an async
object with scripted `recv()` / `send()` and a queue), so no real socket is
opened. Cases:

- `connect()` happy path: receives challenge → signs with the device's Ed25519
  key → sends a well-formed auth envelope (`device_id`, `trust_group_id`,
  `public_key_hex`, `signature_hex`) → handles `auth_ok`.
- `connect()` failure: `auth_failed` from server → raises `RelayConnectionError`.
- `connect()` transport error (refused / closed mid-handshake) → wrapped in
  `RelayConnectionError`.
- The signature it sends actually verifies against the device's public key
  (cross-check with `crypto.verify`).
- `send(target, payload_hex)` emits the correct JSON envelope.
- `receive()` yields `{from_device_id, payload}` for each inbound frame and
  terminates cleanly on close.
- async context manager connects on enter and disconnects on exit.

### P0 — relay WebSocket endpoint (`relay/relay/main.py`)

`auth.py`, `session.py`, `router.py` have unit tests, but the `/ws` glue does
not. Add `relay/tests/test_ws_endpoint.py` using FastAPI `TestClient`'s
WebSocket support:

- Full handshake: connect → receive challenge → send valid signed auth →
  receive `auth_ok` → register appears in the session registry.
- Bad signature → `auth_failed`, connection closed, no registration.
- Two clients in the same trust group: a message addressed to one is delivered.
- Cross-group message → `error: namespace_violation`, not delivered.
- Message to an unconnected target → `error: target_not_connected`.
- Malformed frame → `error: invalid_json` / `missing_fields`, connection stays
  up.
- Disconnect unregisters the session (`connected` in `/health` drops).
- `GET /health` returns `{status: "ok", connected: <n>}`.

### P1 — `logging.py` direct tests

Only exercised indirectly today. Add `tests/unit/test_logging.py`:

- `get_logger()` returns a bound logger; emitted records are JSON with the
  expected keys (level, timestamp, event).
- Log-level filtering: at level `WARN`, `info`/`debug` are suppressed and
  `warning`/`error` pass (complements property test p22).
- `install_global_exception_handler()` logs an unhandled exception at ERROR
  with traceback, and leaves `KeyboardInterrupt` alone.
- `log_output` as a file path writes there; `stdout` writes to stdout.

### P1 — `cli/client.py` direct tests

Currently only covered transitively. Add focused tests for the HTTP helper:

- `api_get/post/put/patch/delete` build the right URL/method/body against a
  mocked `httpx` client.
- Connection refused → friendly error + non-zero exit (assert the message, not
  a traceback).
- Non-2xx responses surface the API error envelope to the user.

### P2 — `daemon.py` boot/shutdown internals

`test_daemon_lifecycle.py` covers health/state; add tests for the wiring:

- Boot constructs all stores and attaches them to `app.state` (with a tmp
  `data_dir`, mocked uvicorn so nothing actually listens).
- `register_self()` runs exactly once and is idempotent across restarts
  (same `device_id` on second boot).
- A `ConfigError` during boot aborts startup (doesn't half-initialize).
- SIGTERM handler triggers the graceful-shutdown path (drain → flush → close).

### P2 — store/model edge cases

- `database.py`: WAL mode and `foreign_keys=ON` are actually set on the
  connection; Alembic migrations run cleanly on a fresh DB and are idempotent
  on an already-migrated DB.
- `context_versions` unique `(context_id, version_tag)` constraint is enforced.
- `delete()` cascade removes versions **and** any embeddings rows.

### P3 — relay robustness

Concurrency/abuse cases that the current unit tests skip: multiple simultaneous
connections, large payloads, a client that authenticates then sends garbage,
reconnection after disconnect. Useful before exposing a relay publicly.

---

## 4. Test design rules

- **One behavior per test**, named for the behavior
  (`test_revoked_device_is_not_trusted`), not the method.
- **Arrange via fixtures, assert on observable outcomes** — return values, DB
  rows, HTTP responses, log records — not private attributes.
- **Mock only at the boundary**: the network (WebSocket/httpx), the filesystem
  where it's incidental, and the embeddings model. Never mock the store or the
  sync logic you're testing.
- **Errors are behavior**: assert the exception type/HTTP code/CLI exit code and
  the user-facing message, not just "it raised".
- **Crypto is verified, not asserted-true**: when a test produces a signature or
  ciphertext, verify/decrypt it with the real primitive rather than checking it
  is non-empty.
- **Property tests state an invariant** (round-trip, monotonicity, ordering,
  "private key never in payload") and let Hypothesis search — they complement,
  not duplicate, example-based unit tests.

---

## 5. New property tests worth adding

The numbered `p01`–`p26` set is thorough. Candidate additions:

- **Encrypt→decrypt round-trip** over arbitrary bytes + nonces returns the
  plaintext; a tampered ciphertext or wrong key always fails (`InvalidTag`).
- **Conflict detection symmetry**: for any two versions, at most one of
  `is_ancestor(a,b)` / `is_ancestor(b,a)` holds; a fast-forward is never flagged
  as a conflict.
- **Backoff monotonicity**: `get_backoff_delay(n)` is non-decreasing in `n` and
  never exceeds the bound implied by `max_retries` (extends p16).
- **Relay namespace isolation**: for random trust-group assignments, a message
  is delivered **iff** sender and target share a group (property form of the
  router unit tests).

---

## 6. CI & coverage

1. Add `pytest-cov` to the dev group; run `pytest --cov=contexa
   --cov-report=term-missing`.
2. Establish a baseline, then gate CI at a floor (e.g. 85%) and ratchet up.
3. Run unit + property suites on every PR; pin `--hypothesis-seed` in CI for
   reproducibility but keep a nightly job with a random seed to find new cases.
4. Run the `relay/` suite as a separate CI job (separate package/venv).
5. Treat the **P0 gaps (relay client + WS endpoint)** as the bar for "sync is
   tested end-to-end" before any release that touches sync.

---

## 7. Suggested execution order

1. P0 — `test_relay_client.py` (fake WebSocket).
2. P0 — `relay/tests/test_ws_endpoint.py` (TestClient WebSocket).
3. P1 — `test_logging.py`, `cli/client.py` tests.
4. Wire up `pytest-cov` + CI floor; measure.
5. P2 — daemon boot/shutdown + store/model edge cases.
6. P3 — relay robustness + the new property tests in §5.
