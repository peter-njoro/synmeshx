"""Unit tests for contexa.config module."""

import pytest
from pathlib import Path

from contexa.config import load_config, ContexaConfig, ConfigError


def test_missing_file_returns_defaults(tmp_path):
    """Missing config file returns all documented defaults."""
    cfg = load_config(tmp_path / "nonexistent.toml")
    assert cfg.daemon.port == 7474
    assert cfg.daemon.log_level == "INFO"
    assert cfg.daemon.log_output == "stdout"
    assert cfg.daemon.socket_path == ""
    assert cfg.sync.mode == "hosted"
    assert cfg.sync.interval_seconds == 60
    assert cfg.sync.max_retries == 5
    assert cfg.sync.backoff_base_seconds == 2
    assert cfg.relay.endpoint == ""
    assert cfg.embeddings.model == ""


def test_valid_toml_applies_all_values(tmp_path):
    """Valid TOML file applies all values correctly."""
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        "[daemon]\n"
        "port = 8080\n"
        'log_level = "DEBUG"\n'
        'log_output = "stdout"\n'
        "\n"
        "[storage]\n"
        'data_dir = "/tmp/contexa"\n'
        "\n"
        "[sync]\n"
        "interval_seconds = 30\n"
        "max_retries = 3\n"
        "backoff_base_seconds = 1\n"
        'mode = "local-only"\n'
        "\n"
        "[relay]\n"
        'endpoint = ""\n'
        "\n"
        "[embeddings]\n"
        'model = "all-MiniLM-L6-v2"\n'
    )
    cfg = load_config(config_file)
    assert cfg.daemon.port == 8080
    assert cfg.daemon.log_level == "DEBUG"
    assert cfg.sync.interval_seconds == 30
    assert cfg.sync.max_retries == 3
    assert cfg.sync.backoff_base_seconds == 1
    assert cfg.sync.mode == "local-only"
    assert cfg.embeddings.model == "all-MiniLM-L6-v2"
    assert cfg.storage.data_dir == Path("/tmp/contexa")


def test_invalid_port_zero_raises_config_error(tmp_path):
    """Port=0 raises ConfigError with field='daemon.port'."""
    config_file = tmp_path / "config.toml"
    config_file.write_text("[daemon]\nport = 0\n")
    with pytest.raises(ConfigError) as exc_info:
        load_config(config_file)
    assert exc_info.value.field == "daemon.port"


def test_invalid_log_level_raises_config_error(tmp_path):
    """Invalid log_level raises ConfigError with field='daemon.log_level'."""
    config_file = tmp_path / "config.toml"
    config_file.write_text('[daemon]\nlog_level = "VERBOSE"\n')
    with pytest.raises(ConfigError) as exc_info:
        load_config(config_file)
    assert exc_info.value.field == "daemon.log_level"


def test_invalid_sync_mode_raises_config_error(tmp_path):
    """Invalid sync.mode raises ConfigError with field='sync.mode'."""
    config_file = tmp_path / "config.toml"
    config_file.write_text('[sync]\nmode = "cloud"\n')
    with pytest.raises(ConfigError) as exc_info:
        load_config(config_file)
    assert exc_info.value.field == "sync.mode"


def test_self_hosted_with_empty_endpoint_raises_config_error(tmp_path):
    """sync.mode='self-hosted' with empty relay endpoint raises ConfigError."""
    config_file = tmp_path / "config.toml"
    config_file.write_text('[sync]\nmode = "self-hosted"\n[relay]\nendpoint = ""\n')
    with pytest.raises(ConfigError) as exc_info:
        load_config(config_file)
    assert exc_info.value.field == "relay.endpoint"


def test_data_dir_tilde_expanded(tmp_path):
    """data_dir with ~ is expanded to an absolute path."""
    config_file = tmp_path / "config.toml"
    config_file.write_text('[storage]\ndata_dir = "~/mydata"\n')
    cfg = load_config(config_file)
    assert not str(cfg.storage.data_dir).startswith("~")
    assert cfg.storage.data_dir.is_absolute()


def test_log_output_tilde_expanded(tmp_path):
    """log_output with ~ is expanded to an absolute path."""
    config_file = tmp_path / "config.toml"
    config_file.write_text('[daemon]\nlog_output = "~/logs/contexa.log"\n')
    cfg = load_config(config_file)
    assert not cfg.daemon.log_output.startswith("~")
    assert Path(cfg.daemon.log_output).is_absolute()
