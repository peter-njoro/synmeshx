# Feature: contexa-core, Property 22: Log Level Filtering
"""
For any configured log level L, the daemon must emit log messages at level L
and above, and must suppress log messages at levels below L.
Validates: Requirements 12.1
"""

from __future__ import annotations

import logging
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from contexa.daemon import _configure_logging

LOG_LEVELS = ["DEBUG", "INFO", "WARN", "ERROR"]
LEVEL_VALUES = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
}


@settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(configured_level=st.sampled_from(LOG_LEVELS))
def test_log_level_filtering(configured_level):
    """Messages at or above the configured level are enabled; below are suppressed."""
    _configure_logging(configured_level, "stdout")

    configured_value = LEVEL_VALUES[configured_level]

    # Check root logger effective level
    root_level = logging.root.level

    for level_name, level_value in LEVEL_VALUES.items():
        if level_value >= configured_value:
            assert logging.root.isEnabledFor(level_value), (
                f"Expected {level_name} to be enabled at configured level {configured_level}"
            )
        else:
            assert not logging.root.isEnabledFor(level_value), (
                f"Expected {level_name} to be suppressed at configured level {configured_level}"
            )
