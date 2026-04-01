# Contexa

Contexa is a local-first context engine that runs as a background daemon on your devices. It lets you store, version, and synchronize structured JSON context across machines — with no cloud dependency, no central server, and no web UI required.

It is designed as the persistence and sync layer for AI agents, developer tools, and automation scripts that need shared, durable state.

Licensed under the [Apache License 2.0](./LICENSE).

---

## What it does

- Runs a daemon (`contexad`) on each of your devices
- Stores versioned, checksummed JSON documents (called *contexts*) in a local SQLite database
- Exposes a local HTTP API on `127.0.0.1:7474` for programmatic access
- Provides a CLI (`contexa`) for managing contexts, devices, and sync from the terminal
- Ships a typed Python SDK (`pip install contexa`) for use in agents and scripts
- Syncs contexts between your trusted devices — directly over LAN or through an optional relay server
- Encrypts all sync payloads end-to-end using device key pairs; the relay never sees plaintext
- Optionally generates vector embeddings for semantic search over stored contexts

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

## CLI quick reference

```bash
# Daemon
contexa daemon start
contexa daemon stop
contexa daemon status

# Contexts
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

## Python SDK

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
