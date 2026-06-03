# Contexa — Design

This document explains how Contexa is put together: its architecture, the
responsibilities of each subsystem, the data model, and the key design
decisions behind versioning, trust, encryption, and sync.

It is descriptive (how the system works today), not aspirational.

---

## 1. What Contexa is

Contexa is a **local-first context engine**. It runs as a background daemon
(`contexad`) on each of your devices and stores versioned, checksummed JSON
documents — called **contexts** — in a local SQLite database. It exposes a
local-only HTTP API for programmatic access, ships a CLI and a Python SDK,
and synchronizes contexts between your **trusted devices** with end-to-end
encryption.

Design goals that shape everything below:

- **Local-first** — every device holds the full state; the network is an
  optimization, not a dependency. The API binds to `127.0.0.1` only.
- **Durable & auditable** — content writes are immutable and checksummed;
  trust changes and sync operations are logged, never silently discarded.
- **Zero-trust transport** — the relay is a dumb pipe; it never sees
  plaintext. Security lives in the device key pairs, not the server.
- **Optional everything** — relay, embeddings, and OAuth identity are all
  opt-in. With no config file, sensible defaults apply.

---

## 2. Component map

```
┌──────────────────────────────────────────────────────────────┐
│  Your device                                                   │
│                                                                │
│   CLI (contexa) ─┐        SDK (ContexaClient) ─┐               │
│                  │                              │              │
│                  ▼                              ▼              │
│            ┌──────────────────────────────────────┐           │
│            │   Local HTTP API  (127.0.0.1:7474)    │           │
│            │   FastAPI app  — api/app.py           │           │
│            └──────────────────────────────────────┘           │
│                  │            │           │          │          │
│         ┌────────┘    ┌───────┘   ┌───────┘    ┌─────┘         │
│         ▼             ▼           ▼            ▼               │
│   ContextStore   TrustStore  EmbeddingStore  SyncEngine        │
│         │             │           │            │               │
│         └─────────────┴───────────┴────────────┘               │
│                          ▼                                     │
│                   SQLite (contexa.db, WAL)                     │
│                          │                                     │
│                   device_id + device_key.pem                   │
└──────────────────────────────────────────────────────────────┘
                              │  encrypted, signed
                              ▼
                   ┌─────────────────────┐        ┌──────────────┐
                   │  Relay (optional)   │◄──────►│ Other device │
                   │  stateless WS broker│        │  (same trust │
                   └─────────────────────┘        │   group)     │
                                                  └──────────────┘
```

The repository has two top-level packages:

| Path       | Package    | Role                                                    |
|------------|------------|---------------------------------------------------------|
| `contexa/` | `contexa`  | Daemon, local API, CLI, SDK, stores, sync engine.       |
| `relay/`   | `relay`    | Stateless WebSocket broker. Self-hostable, no state.    |

---

## 3. The daemon (`contexa/daemon.py`)

`contexad` is the long-lived process. Its boot sequence:

1. Load config from `~/.config/contexa/config.toml` (defaults if absent).
2. Configure structured logging (`structlog`) and install a global
   unhandled-exception handler.
3. Initialize SQLite, run Alembic migrations (safe on every start), build the
   session factory. WAL mode and foreign keys are enabled.
4. Construct the stores: `ContextStore`, `TrustStore`, `EmbeddingStore`.
5. **Register self** — load or generate this device's Ed25519 identity
   (`device_id` + `device_key.pem`) via `TrustStore.register_self()`.
6. Construct the `SyncEngine` for the configured sync mode.
7. Build the FastAPI app, attach every subsystem to `app.state`.
8. Start uvicorn bound to `127.0.0.1` (or a Unix socket if configured).
9. Install `SIGTERM`/`SIGINT` handlers for graceful shutdown — drain
   in-flight requests (~5s), flush pending writes, close the DB, exit 0.

The CLI's `contexa daemon start` launches this process detached
(`subprocess.Popen` with no controlling terminal) and records the PID in
`~/.local/share/contexa/daemon.pid`.

---

## 4. Data model

All persistence is SQLite via SQLAlchemy 2.0 ORM (`store/models.py`), created
through Alembic migrations.

| Table              | Purpose                                                        | Key columns |
|--------------------|----------------------------------------------------------------|-------------|
| `contexts`         | Top-level context record. The `label` is mutable metadata.     | `context_id` (PK, UUID), `owner_device`, `label`, `created_at` |
| `context_versions` | Immutable content snapshots. One row per write.                | `version_id` (PK), `context_id` (FK), `version_tag`, `parent_version`, `content` (JSON), `checksum` (SHA-256), `created_at`. Unique (`context_id`, `version_tag`). |
| `devices`          | Known devices (self + peers).                                  | `device_id` (PK), `public_key` (32-byte Ed25519), `identity_id` |
| `trust_entries`    | Trust registry. Revocation is a soft-delete.                   | `device_id` (PK/FK), `label`, `trusted_at`, `revoked` |
| `sync_log`         | Audit log of every sync operation.                             | `log_id`, `device_id`, `context_id`, `version_tag`, `status`, `error_msg`, `created_at` |
| `embeddings`       | Optional vector embeddings for semantic search.                | `embedding_id`, `context_id` (FK), `version_tag`, `model_name`, `vector` (float32 bytes) |

### Versioning & checksums

- A context is a chain of immutable **versions**. `create()` makes the first
  version (`parent_version = None`); `update()` appends a new version whose
  `parent_version` points at the previous latest. Old versions are never
  mutated.
- `version_tag` is derived from the version UUID (first 8 hex chars) — a short
  handle for a version within a context.
- Every version stores a **SHA-256 checksum of its canonical JSON** (sorted
  keys, UTF-8). On read, the checksum is recomputed and compared; a mismatch
  raises `ChecksumError` (surfaced as HTTP 500 `integrity_error`).
- **Labels are mutable and do not create a version.** `update_label()` changes
  metadata only — it does not affect content history or trigger sync.

This append-only chain is what makes decentralized conflict detection possible
(see §6).

---

## 5. Stores

- **`ContextStore`** — CRUD over contexts/versions. Computes and verifies
  checksums, returns `ContextVersion` / `ContextSummary` dataclasses, raises
  `NotFoundError` / `ChecksumError`. `delete()` cascades to all versions.

- **`TrustStore`** — owns this device's identity (`register_self()`, idempotent)
  and the registry of trusted peers. `add_trusted(device_id, public_key, label)`,
  `remove_trusted()` (sets `revoked=True`), `is_trusted()`, `list_trusted()`,
  `get_public_key()`. Public keys are stored as raw 32-byte Ed25519 bytes.
  Revocation preserves audit history and allows later re-trust.

- **`EmbeddingStore`** — optional semantic search. When a model is configured,
  it lazily loads `sentence-transformers`, encodes a version's canonical JSON
  into a unit-normalized float32 vector, and stores it. `search(query, top_n)`
  ranks by cosine similarity (dot product of normalized vectors). When no model
  is configured it is disabled and the API returns 503 for search.

---

## 6. Sync

Sync is **peer-to-peer between trusted devices**, with the relay only used as a
transport when peers can't reach each other directly.

### Identity & crypto (`sync/crypto.py`)

- Each device has an **Ed25519** key pair. The private key lives in
  `device_key.pem` (PKCS8, mode `0600`); the public key is shared with peers and
  stored in `devices.public_key`. Ed25519 is used for signing auth challenges.
- Per sync session, an **ephemeral X25519** key pair is generated. ECDH between
  the local X25519 private key and the peer's X25519 public key yields a shared
  secret, fed through **HKDF-SHA256** (salt = nonce, info = `contexa-sync-v1`)
  to derive a 32-byte session key.
- Payloads are encrypted with **AES-256-GCM** (12-byte random nonce, with AAD).
  Decryption failures raise `InvalidTag`.

### Protocol (`sync/protocol.py`)

A four-message exchange, JSON-serialized:

| Message          | Direction          | Contents |
|------------------|--------------------|----------|
| `HELLO`          | initiator → peer   | `device_id`, `identity_id`, challenge, Ed25519 signature |
| `KNOWN_VERSIONS` | peer → initiator   | `{context_id → version_tag}` the peer already has |
| `PUSH`           | initiator → peer   | list of `PushEntry` (encrypted content + checksum + parent chain + nonce) |
| `ACK`            | peer → initiator   | accepted / conflicted / rejected version IDs |

### Conflict detection

Detection is **ancestor-chain based** — no merge logic, no central authority:

```
version_map = {version_id → parent_version_id}

is_ancestor(a, b):  walk b's parent pointers; True if a is found
detect_conflict(local, remote):
    if is_ancestor(local, remote):  return False   # remote is a fast-forward
    if is_ancestor(remote, local):  return False   # local already newer
    return True                                     # diverged → CONFLICT
```

Conflicts are **logged, not auto-resolved** — both versions are preserved and
the application layer decides what to do.

### The sync engine (`sync/engine.py`)

`sync_with_peer()` runs the full cycle: enforce trust (`is_trusted`), verify the
peer's claimed identity, diff local vs. peer version tags, prepare encrypted
`PushEntry`s for what the peer is missing, run conflict detection on what the
peer has, and write a `sync_log` row for every operation. It tracks
`syncs_completed` / `sync_failures` counters.

Failed operations are queued (`PendingOperation`) and retried with
**exponential backoff**: `backoff_base ^ attempts` up to `max_retries`.

Three sync **modes**:

- `local-only` — direct peer-to-peer, no relay.
- `self-hosted` — use the relay at the configured `[relay] endpoint`.
- `hosted` — use the default hosted relay (`wss://relay.contexa.dev`).

### Relay client (`sync/relay_client.py`)

An async WebSocket client. On `connect()` it receives a challenge, signs it with
the device's Ed25519 key, and authenticates with its `device_id` + trust-group
id + public key + signature. `send()`/`receive()` exchange hex-encoded encrypted
envelopes. Errors raise `RelayConnectionError`.

---

## 7. The relay server (`relay/`)

A **stateless WebSocket broker**. It authenticates devices and routes encrypted
bytes between devices **in the same trust group** — and nothing else. It never
decrypts payloads and keeps no durable state.

- **Handshake** (`/ws`): server sends a 32-byte challenge → client replies with
  `device_id`, `trust_group_id`, `public_key_hex`, `signature_hex` → server
  verifies the Ed25519 signature (`auth.py`) and replies `auth_ok` or
  `auth_failed`.
- **Routing** (`router.py`): a message `{target_device_id, payload}` is
  forwarded as `{from_device_id, payload}` only if the target is connected and
  in the **same trust group** (namespace isolation). Errors: `invalid_json`,
  `missing_fields`, `namespace_violation`, `target_not_connected`, `send_failed`.
- **Sessions** (`session.py`): an in-memory registry of connected devices keyed
  by `device_id`, grouped by `trust_group_id`. Cleared on disconnect.
- **Health**: `GET /health → {status, connected}`.
- **Deploy**: Dockerfile runs `uvicorn relay.main:app` on port `8765`.

Because routing is gated on trust group and payloads are end-to-end encrypted,
a compromised relay can drop or misroute messages but cannot read or forge them.

---

## 8. Local HTTP API (`api/`)

FastAPI app, bound to `127.0.0.1`, docs at `/docs`. Domain exceptions are mapped
to stable error envelopes: `NotFoundError → 404 not_found`,
`ChecksumError → 500 integrity_error`, validation → `400 validation_error`, and
a catch-all `500 internal_error`. Subsystems are reached through `app.state`.
Routes are summarized in [USAGE.md](./USAGE.md) (contexts, trust, sync, health/
metrics/config).

---

## 9. Identity / auth (`auth.py`)

Optional OAuth **device authorization grant** (RFC 8628) links a device to a
stable user identity (`identity_id` = OAuth `sub`). The token (`identity.json`,
mode `0600`) is used to form the **trust group** so multiple devices owned by the
same user can find each other through the relay. Device-to-device sync
additionally verifies that a peer's claimed `identity_id` matches what's recorded
for that device.

---

## 10. Configuration & observability

- **Config** (`config.py`): TOML at `~/.config/contexa/config.toml`, parsed into
  typed dataclasses with validation (port range, log level enum, sync mode enum,
  relay endpoint required when `self-hosted`). Invalid values raise `ConfigError`.
- **Logging** (`logging.py`): `structlog` with JSON output, ISO-8601 timestamps,
  level filtering, and a global exception handler.
- **Metrics**: `GET /metrics` exposes `contexts_stored`, `syncs_completed`,
  `sync_failures`, `uptime_seconds`.

---

## 11. Key design decisions (summary)

| Decision | Why |
|----------|-----|
| Immutable versions + parent pointers | Cheap ancestor checks for conflict detection; full audit trail. |
| Ancestor-chain conflict detection | Decentralized, offline-capable, no merge authority. |
| Checksum on every read | Detect corruption deterministically across devices. |
| AES-256-GCM + ephemeral X25519 + HKDF | Authenticated encryption with per-session forward secrecy. |
| Soft-delete trust (revoked flag) | Preserve audit history; allow re-trust. |
| Relay is stateless & blind | Minimize trust in transport; security in device keys. |
| Local API on 127.0.0.1 only | No network exposure; CLI/SDK are the only clients. |
| Optional embeddings / relay / OAuth | Keep the core small; opt into cost and dependencies. |
| Graceful shutdown w/ drain | Avoid losing in-flight writes. |

---

## 12. Storage layout

```
~/.config/contexa/config.toml      # configuration
~/.config/contexa/identity.json    # OAuth identity token (mode 0600)
~/.local/share/contexa/
├── contexa.db                     # SQLite (contexts, versions, trust, sync log, embeddings)
├── daemon.pid                     # PID of the running daemon
├── device_id                      # this device's UUID (plaintext)
└── device_key.pem                 # Ed25519 private key (mode 0600)
```
