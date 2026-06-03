# Contexa — Usage Guide

A practical reference for running Contexa and every command, endpoint, and SDK
method it exposes. For how it works internally, see [DESIGN.md](./DESIGN.md).

---

## 1. Install & run

```bash
cd contexa
uv sync                       # install deps + create .venv
source .venv/bin/activate.fish   # or .venv/bin/activate for bash/zsh
```

This installs two executables:

- `contexa` — the CLI
- `contexad` — the daemon

Optional semantic search:

```bash
uv sync --extra embeddings
```

Then start the daemon (it initializes the database and keys on first run):

```bash
contexad                # run in the foreground
# or
contexa daemon start    # launch detached in the background
```

The daemon listens on `http://127.0.0.1:7474` by default.

---

## 2. Configuration

Config lives at `~/.config/contexa/config.toml`. If absent, all defaults apply.

```toml
[daemon]
port = 7474             # 1–65535
socket_path = ""        # if set, a Unix socket overrides the TCP port
log_level = "INFO"      # DEBUG | INFO | WARN | ERROR
log_output = "stdout"   # "stdout" or a file path

[storage]
data_dir = "~/.local/share/contexa"

[sync]
interval_seconds = 60
max_retries = 5
backoff_base_seconds = 2
mode = "hosted"         # local-only | self-hosted | hosted

[relay]
endpoint = ""           # required when mode = "self-hosted"

[embeddings]
model = ""              # e.g. "all-MiniLM-L6-v2"; empty = disabled
```

Invalid values (bad port, unknown log level, unknown sync mode, missing relay
endpoint for `self-hosted`) cause the daemon to fail with a `ConfigError`. View
the resolved config any time with `contexa config show`.

---

## 3. CLI reference

All CLI commands talk to the daemon over the local HTTP API. **If the daemon
isn't running, the command prints an error and exits non-zero.** Most read
commands accept `--json` for machine-readable output.

```
contexa
├── daemon    start | stop | status
├── context   create | get | list | label | delete
├── trust      list | add | remove
├── sync       trigger | log
└── config     show
```

### 3.1 `contexa daemon`

| Command | What it does |
|---------|--------------|
| `contexa daemon start`  | Launch the daemon detached; write its PID to `~/.local/share/contexa/daemon.pid`. |
| `contexa daemon stop`   | Send `SIGTERM` to the running daemon for a graceful shutdown. |
| `contexa daemon status` | Report whether the daemon is alive and show its `/health`. |

### 3.2 `contexa context`

```bash
# Create a context from an inline JSON string or a file
contexa context create --json '{"task": "refactor auth", "status": "wip"}' --label auth-refactor
contexa context create --file ./payload.json --label imported

# Read it back (latest version, or a specific one)
contexa context get <context_id>
contexa context get <context_id> --version <version_tag>

# List all contexts (summaries: latest version, checksum, label)
contexa context list

# Change or clear the human label (does NOT create a new version)
contexa context label <context_id> "new label"
contexa context label <context_id>            # omit text to clear

# Delete a context and all its versions
contexa context delete <context_id>
contexa context delete <context_id> --yes     # skip the confirmation
```

| Option | Applies to | Meaning |
|--------|------------|---------|
| `--json TEXT` | create | Content as an inline JSON string. |
| `--file PATH` | create | Content read from a JSON file. |
| `--label TEXT` | create | Optional human-readable label. |
| `--version TAG` | get | Fetch a specific version instead of the latest. |
| `--yes` / `-y` | delete | Skip the confirmation prompt. |
| `--json` | get/list/create | Emit raw JSON instead of the human format. |

> **Updating content:** there is no `context update` CLI verb — content updates
> go through the SDK/API (`PUT /contexts/{id}`). The CLI manages labels and
> lifecycle; the SDK manages content versions.

### 3.3 `contexa trust`

```bash
# List trusted devices (non-revoked)
contexa trust list

# Trust a device. PUBLIC_KEY_FILE holds the peer's hex-encoded public key.
contexa trust add <device_id> <public_key_file> --label "laptop"

# Revoke trust (soft-delete; preserves audit history)
contexa trust remove <device_id>
contexa trust remove <device_id> --yes
```

### 3.4 `contexa sync`

```bash
# Queue a manual sync run (returns immediately; runs async in the daemon)
contexa sync trigger

# Inspect the sync audit log, with optional filters
contexa sync log
contexa sync log --status conflict
contexa sync log --device <device_id> --context <context_id>
contexa sync log --since 2026-06-01T00:00:00Z --json
```

| Option | Meaning |
|--------|---------|
| `--device TEXT`  | Filter by device id. |
| `--context TEXT` | Filter by context id. |
| `--status TEXT`  | Filter by status: `success`, `conflict`, `failed`, `pending`. |
| `--since TEXT`   | Only entries after the given ISO-8601 timestamp. |
| `--json`         | Raw JSON output. |

### 3.5 `contexa config`

```bash
contexa config show          # human-readable resolved config (defaults included)
contexa config show --json   # same, as JSON
```

---

## 4. HTTP API reference

Base URL: `http://127.0.0.1:7474`. Interactive docs at `/docs`.

### Contexts

| Method | Path | Body | Returns |
|--------|------|------|---------|
| POST   | `/contexts` | `{content, label?}` | `201` ContextVersion |
| GET    | `/contexts` | — | `[ContextSummary]` |
| GET    | `/contexts/{context_id}` | — | ContextVersion (latest) |
| GET    | `/contexts/{context_id}/versions/{version_tag}` | — | ContextVersion |
| GET    | `/contexts/search?q=…&top_n=…` | — | `[ContextVersion]` (semantic; `503` if embeddings disabled) |
| PUT    | `/contexts/{context_id}` | `{content}` | ContextVersion (new version) |
| PATCH  | `/contexts/{context_id}/label` | `{label}` | ContextSummary |
| DELETE | `/contexts/{context_id}` | — | `204` |

**ContextVersion**: `version_id, context_id, version_tag, parent_version,
content, checksum, created_at, label`.
**ContextSummary**: `context_id, latest_version_tag, checksum, created_at, label`.

### Trust

| Method | Path | Body | Returns |
|--------|------|------|---------|
| GET    | `/trust` | — | `[TrustEntry]` |
| POST   | `/trust` | `{device_id, public_key_hex, label?}` | `201` TrustEntry |
| DELETE | `/trust/{device_id}` | — | `204` |

### Sync

| Method | Path | Query | Returns |
|--------|------|-------|---------|
| GET    | `/sync/log` | `device_id?, context_id?, status?, since?` | `[SyncLogEntry]` |
| POST   | `/sync/trigger` | — | `202 {status, message}` |

### Health / metrics / config

| Method | Path | Returns |
|--------|------|---------|
| GET | `/health`  | per-subsystem status (`ok`/`degraded`) |
| GET | `/metrics` | `contexts_stored, syncs_completed, sync_failures, uptime_seconds` |
| GET | `/config`  | resolved configuration |

**Error envelope** (all errors): `{error: "<code>", detail: …}` — codes include
`validation_error` (400), `not_found` (404), `integrity_error` (500),
`internal_error` (500).

---

## 5. Python SDK

```python
from contexa.sdk import (
    ContexaClient,
    ContexaConnectionError,
    ContexaNotFoundError,
    ContexaValidationError,
)

client = ContexaClient()  # defaults to http://127.0.0.1:7474, 10s timeout

# Create — returns a ContextVersion dict
ctx = client.create_context(
    content={"task": "refactor auth", "status": "in_progress"},
    label="auth-refactor",
)

# Read (latest or a specific version)
ctx = client.get_context(ctx["context_id"])
ctx = client.get_context(ctx["context_id"], version_tag="a1b2c3d4")

# List summaries
all_ctx = client.list_contexts()

# Update content → creates a new immutable version
client.update_context(ctx["context_id"], {"task": "refactor auth", "status": "done"})

# Update / clear the label → no new version
client.update_label(ctx["context_id"], "done")

# Delete
client.delete_context(ctx["context_id"])

# Semantic search (requires embeddings configured; else raises ContexaError/503)
results = client.search("authentication tasks", top_n=10)

# Sync
client.trigger_sync()
log = client.get_sync_log(status="conflict")

# Introspection
client.health()
client.get_config()
```

**Exceptions:** `ContexaError` (base), `ContexaConnectionError` (daemon
unreachable), `ContexaNotFoundError` (404), `ContexaValidationError` (400/422).

---

## 6. Multi-device sync

1. **Start the daemon** on each device (creates its `device_id` + key pair).
2. **Exchange public keys.** Each device's hex public key can be derived from
   `~/.local/share/contexa/device_key.pem`. Trust the peer:
   ```bash
   contexa trust add <peer_device_id> <peer_public_key_file> --label "phone"
   ```
   Do this on both devices.
3. **Pick a sync mode** in config:
   - `local-only` — direct, same LAN, no relay.
   - `self-hosted` — set `[relay] endpoint = "wss://your-host:8765"`.
   - `hosted` — use the default hosted relay.
4. **Sync** automatically on the configured interval, or on demand:
   ```bash
   contexa sync trigger
   contexa sync log            # check what happened
   ```

Conflicts (divergent versions) are **logged, not auto-merged** — inspect them
with `contexa sync log --status conflict` and resolve by writing a new version.

---

## 7. Running your own relay

```bash
# Docker
docker run -p 8765:8765 contexa/relay

# Or locally
cd relay
uv sync
uvicorn relay.main:app --host 0.0.0.0 --port 8765
```

Point devices at it:

```toml
[sync]
mode = "self-hosted"
[relay]
endpoint = "wss://your-relay-host:8765"
```

The relay only routes encrypted bytes between devices in the same trust group —
it never sees plaintext. `GET /health` reports the connected device count.

---

## 8. Auto-start on boot

**Linux (systemd, user service)**

```bash
cp contexa/contexad.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now contexad
```

**macOS (launchd)**

```bash
cp contexa/com.contexa.daemon.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.contexa.daemon.plist
```

---

## 9. Troubleshooting

| Symptom | Likely cause / fix |
|---------|--------------------|
| CLI says it can't connect | Daemon not running — `contexa daemon start`. |
| `503` on search | Embeddings disabled — install `--extra embeddings` and set `[embeddings] model`. |
| Daemon won't start, `ConfigError` | Invalid `config.toml` value — check port/log_level/sync mode; `relay.endpoint` is required for `self-hosted`. |
| Sync entries stuck `pending`/`failed` | Peer unreachable or relay down; retries use exponential backoff up to `max_retries`. |
| `integrity_error` (500) on read | Stored content checksum mismatch — the version is corrupted. |
