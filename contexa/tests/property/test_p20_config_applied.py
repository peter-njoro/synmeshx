# Feature: contexa-core, Property 20: Configuration Values Applied
"""
Property 20: For any valid configuration file specifying values for port,
sync.interval_seconds, relay.endpoint, embeddings.model, or log_level,
the running daemon must use those values rather than the built-in defaults.
Validates: Requirements 11.2
"""

import tempfile
from pathlib import Path

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from contexa.config import load_config, _VALID_LOG_LEVELS, _VALID_SYNC_MODES


valid_ports = st.integers(min_value=1, max_value=65535)
valid_log_levels = st.sampled_from(sorted(_VALID_LOG_LEVELS))
valid_intervals = st.integers(min_value=1, max_value=3600)
valid_retries = st.integers(min_value=1, max_value=100)
valid_backoff = st.integers(min_value=1, max_value=60)
valid_models = st.one_of(
    st.just(""),
    st.just("all-MiniLM-L6-v2"),
    st.just("paraphrase-MiniLM-L6-v2"),
)


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    port=valid_ports,
    log_level=valid_log_levels,
    interval=valid_intervals,
    model=valid_models,
)
def test_config_values_applied(port, log_level, interval, model):
    """Config values from TOML are applied — not overridden by defaults."""
    lines = [
        "[daemon]",
        f"port = {port}",
        f'log_level = "{log_level}"',
        "[sync]",
        f"interval_seconds = {interval}",
        'mode = "local-only"',
        "[embeddings]",
        f'model = "{model}"',
    ]
    with tempfile.NamedTemporaryFile(suffix=".toml", mode="w", delete=False) as f:
        f.write("\n".join(lines))
        tmp = Path(f.name)

    cfg = load_config(tmp)
    tmp.unlink(missing_ok=True)

    assert cfg.daemon.port == port
    assert cfg.daemon.log_level == log_level
    assert cfg.sync.interval_seconds == interval
    assert cfg.embeddings.model == model


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    mode=st.sampled_from(["local-only", "hosted"]),
    retries=valid_retries,
    backoff=valid_backoff,
)
def test_sync_config_values_applied(mode, retries, backoff):
    """Sync config values from TOML are applied correctly."""
    lines = [
        "[sync]",
        f'mode = "{mode}"',
        f"max_retries = {retries}",
        f"backoff_base_seconds = {backoff}",
    ]
    with tempfile.NamedTemporaryFile(suffix=".toml", mode="w", delete=False) as f:
        f.write("\n".join(lines))
        tmp = Path(f.name)

    cfg = load_config(tmp)
    tmp.unlink(missing_ok=True)

    assert cfg.sync.mode == mode
    assert cfg.sync.max_retries == retries
    assert cfg.sync.backoff_base_seconds == backoff
