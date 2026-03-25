"""
Configuration loader for Contexa.
Reads ~/.config/contexa/config.toml via tomllib, maps values onto the
ContexaConfig dataclass, and applies documented defaults when the file is absent.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("~/.config/contexa/config.toml")

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARN", "ERROR"}
_VALID_SYNC_MODES = {"local-only", "self-hosted", "hosted"}


class ConfigError(Exception):
    """Raised when a configuration value is invalid."""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(f"Invalid config field '{field}': {message}")


@dataclass
class DaemonConfig:
    port: int = 7474
    socket_path: str = ""
    log_level: str = "INFO"
    log_output: str = "stdout"


@dataclass
class StorageConfig:
    data_dir: Path = field(default_factory=lambda: Path("~/.local/share/contexa"))


@dataclass
class SyncConfig:
    interval_seconds: int = 60
    max_retries: int = 5
    backoff_base_seconds: int = 2
    mode: str = "hosted"


@dataclass
class RelayConfig:
    endpoint: str = ""


@dataclass
class EmbeddingsConfig:
    model: str = ""


@dataclass
class ContexaConfig:
    daemon: DaemonConfig = field(default_factory=DaemonConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)
    relay: RelayConfig = field(default_factory=RelayConfig)
    embeddings: EmbeddingsConfig = field(default_factory=EmbeddingsConfig)


def _validate_daemon(raw: dict) -> DaemonConfig:
    port = raw.get("port", 7474)
    if not isinstance(port, int) or not (1 <= port <= 65535):
        raise ConfigError("daemon.port", "must be an integer between 1 and 65535")

    log_level = raw.get("log_level", "INFO")
    if log_level not in _VALID_LOG_LEVELS:
        raise ConfigError("daemon.log_level", f"must be one of {sorted(_VALID_LOG_LEVELS)}")

    log_output = raw.get("log_output", "stdout")
    if log_output != "stdout":
        log_output = str(Path(log_output).expanduser())

    return DaemonConfig(
        port=port,
        socket_path=raw.get("socket_path", ""),
        log_level=log_level,
        log_output=log_output,
    )


def _validate_storage(raw: dict) -> StorageConfig:
    data_dir = Path(raw.get("data_dir", "~/.local/share/contexa")).expanduser()
    return StorageConfig(data_dir=data_dir)


def _validate_sync(raw: dict) -> SyncConfig:
    mode = raw.get("mode", "hosted")
    if mode not in _VALID_SYNC_MODES:
        raise ConfigError("sync.mode", f"must be one of {sorted(_VALID_SYNC_MODES)}")

    interval_seconds = raw.get("interval_seconds", 60)
    if not isinstance(interval_seconds, int) or interval_seconds < 1:
        raise ConfigError("sync.interval_seconds", "must be a positive integer")

    max_retries = raw.get("max_retries", 5)
    if not isinstance(max_retries, int) or max_retries < 1:
        raise ConfigError("sync.max_retries", "must be a positive integer")

    backoff_base_seconds = raw.get("backoff_base_seconds", 2)
    if not isinstance(backoff_base_seconds, int) or backoff_base_seconds < 1:
        raise ConfigError("sync.backoff_base_seconds", "must be a positive integer")

    return SyncConfig(
        interval_seconds=interval_seconds,
        max_retries=max_retries,
        backoff_base_seconds=backoff_base_seconds,
        mode=mode,
    )


def _validate_relay(raw: dict, sync_mode: str) -> RelayConfig:
    endpoint = raw.get("endpoint", "")
    if sync_mode == "self-hosted" and not endpoint:
        raise ConfigError("relay.endpoint", "must be a non-empty string when sync.mode is 'self-hosted'")
    return RelayConfig(endpoint=endpoint)


def load_config(path: Path | None = None) -> ContexaConfig:
    """Load configuration from a TOML file.

    Uses the default path ~/.config/contexa/config.toml if none is provided.
    Returns defaults if the file does not exist.
    Raises ConfigError on invalid values.
    """
    if path is None:
        path = DEFAULT_CONFIG_PATH.expanduser()
    else:
        path = Path(path).expanduser()

    raw: dict = {}
    if path.exists():
        with open(path, "rb") as f:
            raw = tomllib.load(f)

    daemon = _validate_daemon(raw.get("daemon", {}))
    storage = _validate_storage(raw.get("storage", {}))
    sync = _validate_sync(raw.get("sync", {}))
    relay = _validate_relay(raw.get("relay", {}), sync.mode)
    embeddings = EmbeddingsConfig(model=raw.get("embeddings", {}).get("model", ""))

    return ContexaConfig(
        daemon=daemon,
        storage=storage,
        sync=sync,
        relay=relay,
        embeddings=embeddings,
    )
