# Contexa

Contexa is a local-first context engine for AI agents. It runs as a background daemon and gives agents — and the automation and developer tools around them — a durable, versioned place to store and share structured JSON state across machines, with no cloud dependency, no central server, and no web UI.

**Agents are the primary consumer.** The interface that matters is the local HTTP API (and the typed Python SDK over it): an agent reads and writes contexts at `127.0.0.1:7474` as its persistence and sync layer. The `contexa` CLI exists for the human in the loop — initial setup, inspection, and debugging — not as the main way the system is driven.

Licensed under the [Apache License 2.0](./LICENSE).

---

## What it does

- Runs a daemon (`contexad`) on each of your devices
- Stores versioned, checksummed JSON documents (called *contexts*) in a local SQLite database
- **Exposes a local HTTP API on `127.0.0.1:7474`** — the primary interface agents and tools talk to
- **Ships a typed Python SDK (`pip install contexa`)** — the ergonomic wrapper over that API for agents and scripts
- Optionally generates vector embeddings for semantic search over stored contexts
- Syncs contexts between your trusted devices — directly over LAN or through an optional relay server
- Encrypts all sync payloads end-to-end using device key pairs; the relay never sees plaintext
- Provides a CLI (`contexa`) for humans to set up, inspect, and debug from the terminal

---

## Repository layout

```
/
├── contexa/        # Main Python package — daemon, API, CLI, SDK
├── relay/          # Relay server — stateless WebSocket broker (self-hostable)
├── LICENSE
└── README.md
```

---

## Requirements

- Python 3.11 or later
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

---

## Setup

To set up the development environment:

1. Ensure you have `uv` installed (https://github.com/astral-sh/uv).
2. Install dependencies and create the virtual environment:
   ```bash
   cd contexa
   uv sync
   ```
3. Activate the virtual environment:
   ```bash
   source .venv/bin/activate.fish  # or activate (for bash/zsh)
   ```

This installs two executables into the virtual environment:

- `contexa` — the CLI
- `contexad` — the daemon entry point

### Optional: enable semantic search

Semantic search requires `sentence-transformers`. Install the optional dependency group:

```bash
uv sync --extra embeddings
```

Then set a model in your config (see [Configuration](#configuration)):

```toml
[embeddings]
model = "all-MiniLM-L6-v2"
```

### Install as a library (SDK only)

```bash
pip install contexa
```

---

## Running the daemon

```bash
# Start the daemon in the foreground
contexad

# Or via the CLI
contexa daemon start
```

The daemon listens on `http://127.0.0.1:7474` by default. It initializes the SQLite database and all subsystems on first run.

### Auto-start on boot

**Linux (systemd)**

Copy the included unit file and enable it:

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

## Configuration

Contexa reads configuration from `~/.config/contexa/config.toml`. If the file is absent, all defaults apply.

```toml
[daemon]
port = 7474
log_level = "INFO"      # DEBUG | INFO | WARN | ERROR
log_output = "stdout"   # "stdout" or a file path

[storage]
data_dir = "~/.local/share/contexa"

[sync]
interval_seconds = 60
max_retries = 5
backoff_base_seconds = 2
mode = "hosted"         # "local-only" | "self-hosted" | "hosted"

[relay]
endpoint = ""           # required when mode = "self-hosted"

[embeddings]
model = ""              # e.g. "all-MiniLM-L6-v2"; empty = disabled
```

View the resolved config (including defaults) at any time:

```bash
contexa config show
```

---

## Programmatic access (the primary interface)

This is how agents and tools are expected to use Contexa: talk to the daemon's
local HTTP API, either directly or through the typed Python SDK.

### Python SDK

```python
from contexa.sdk import ContexaClient

client = ContexaClient()  # connects to http://127.0.0.1:7474

# Store context
ctx = client.create_context(
    content={"task": "refactor auth", "status": "in_progress"},
    label="auth-refactor"
)

# Read it back
ctx = client.get_context(ctx["context_id"])

# Update it (creates a new immutable version)
client.update_context(ctx["context_id"], {"task": "refactor auth", "status": "done"})

# Semantic search (requires embeddings to be configured)
results = client.search("authentication tasks")

# Sync
client.trigger_sync()
log = client.get_sync_log(status="conflict")
```

`ContexaConnectionError` is raised if the daemon is not running.

### HTTP API

Any language can use Contexa over plain HTTP on `http://127.0.0.1:7474`. Contexts
are versioned and checksummed, errors come back in a stable envelope
(`{error, detail}`), and interactive docs are served at `/docs`. See
[USAGE.md](./docs/USAGE.md) for the full endpoint reference.

```bash
curl -s http://127.0.0.1:7474/contexts \
  -H 'content-type: application/json' \
  -d '{"content": {"task": "refactor auth", "status": "wip"}, "label": "auth-refactor"}'
```

---

## CLI (the human escape hatch)

The `contexa` CLI is for the operator, not the agent — it's a thin client over
the same HTTP API, meant for first-time setup, inspection, and debugging. Agents
should use the SDK/API above rather than shelling out to the CLI.

```bash
# Daemon
contexa daemon start
contexa daemon stop
contexa daemon status

# Contexts (inspection / lifecycle; content updates go through the SDK/API)
contexa context create --json '{"key": "value"}' --label my-context
contexa context list
contexa context get <context_id>
contexa context label <context_id> "new label"
contexa context delete <context_id>

# Trusted devices
contexa trust list
contexa trust add <device_id> <public_key_file>
contexa trust remove <device_id>

# Sync
contexa sync trigger
contexa sync log --status conflict

# Config
contexa config show
```

---

## Relay server

The relay is a stateless WebSocket broker that lets devices sync when they can't reach each other directly. It never stores or decrypts context data.

```bash
# Run with Docker
docker run -p 8765:8765 contexa/relay

# Or run locally
cd relay
uv sync
uvicorn relay.main:app --host 0.0.0.0 --port 8765
```

Point your devices at it:

```toml
[sync]
mode = "self-hosted"

[relay]
endpoint = "wss://your-relay-host:8765"
```

---

## Data storage

```
~/.config/contexa/config.toml     # configuration
~/.local/share/contexa/
├── contexa.db                    # SQLite database (contexts, sync log, embeddings)
├── device_id                     # this device's UUID
└── device_key.pem                # Ed25519 private key (chmod 600)
```

---

## Development

```bash
cd contexa
uv sync

# Run all tests
pytest tests/ -v

# Unit tests only
pytest tests/unit/ -v

# Property-based tests only
pytest tests/property/ -v --hypothesis-seed=0
```
