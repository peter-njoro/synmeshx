# Feature: contexa-core, Property 21: Invalid Configuration Causes Non-Zero Exit
"""
Property 21: For any configuration file containing an invalid value for any
recognized field (wrong type, out-of-range port, unknown log level), the daemon
must raise ConfigError identifying the invalid field.
Validates: Requirements 11.4
"""

import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

from contexa.config import load_config, ConfigError, _VALID_LOG_LEVELS, _VALID_SYNC_MODES


invalid_ports = st.one_of(
    st.integers(max_value=0),
    st.integers(min_value=65536),
)

invalid_log_levels = st.text(
    alphabet=st.characters(whitelist_categories=("Lu",)),
    min_size=1,
    max_size=10,
).filter(lambda s: s not in _VALID_LOG_LEVELS)

invalid_sync_modes = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu")),
    min_size=1,
    max_size=20,
).filter(lambda s: s not in _VALID_SYNC_MODES)

invalid_positive_ints = st.integers(max_value=0)


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(port=invalid_ports)
def test_invalid_port_raises_config_error(port):
    """Any out-of-range port raises ConfigError identifying daemon.port."""
    with tempfile.NamedTemporaryFile(suffix=".toml", mode="w", delete=False) as f:
        f.write(f"[daemon]\nport = {port}\n")
        tmp = Path(f.name)

    with pytest.raises(ConfigError) as exc_info:
        load_config(tmp)
    tmp.unlink(missing_ok=True)

    assert exc_info.value.field == "daemon.port"


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(log_level=invalid_log_levels)
def test_invalid_log_level_raises_config_error(log_level):
    """Any unrecognized log level raises ConfigError identifying daemon.log_level."""
    assume(log_level not in _VALID_LOG_LEVELS)
    with tempfile.NamedTemporaryFile(suffix=".toml", mode="w", delete=False) as f:
        f.write(f'[daemon]\nlog_level = "{log_level}"\n')
        tmp = Path(f.name)

    with pytest.raises(ConfigError) as exc_info:
        load_config(tmp)
    tmp.unlink(missing_ok=True)

    assert exc_info.value.field == "daemon.log_level"


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(mode=invalid_sync_modes)
def test_invalid_sync_mode_raises_config_error(mode):
    """Any unrecognized sync mode raises ConfigError identifying sync.mode."""
    assume(mode not in _VALID_SYNC_MODES)
    with tempfile.NamedTemporaryFile(suffix=".toml", mode="w", delete=False) as f:
        f.write(f'[sync]\nmode = "{mode}"\n')
        tmp = Path(f.name)

    with pytest.raises(ConfigError) as exc_info:
        load_config(tmp)
    tmp.unlink(missing_ok=True)

    assert exc_info.value.field == "sync.mode"


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(interval=invalid_positive_ints)
def test_invalid_interval_raises_config_error(interval):
    """Non-positive sync interval raises ConfigError identifying sync.interval_seconds."""
    with tempfile.NamedTemporaryFile(suffix=".toml", mode="w", delete=False) as f:
        f.write(f"[sync]\ninterval_seconds = {interval}\n")
        tmp = Path(f.name)

    with pytest.raises(ConfigError) as exc_info:
        load_config(tmp)
    tmp.unlink(missing_ok=True)

    assert exc_info.value.field == "sync.interval_seconds"
