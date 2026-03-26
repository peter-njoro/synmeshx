# Feature: contexa-core, Property 16: Exponential Backoff on Retry
"""
For any sequence of consecutive sync failures, the delay between retry
attempt n and attempt n+1 must be at least backoff_base^n seconds, and
the total number of attempts must not exceed the configured maximum.
Validates: Requirements 8.7, 9.5
"""

from __future__ import annotations

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from contexa.sync.engine import SyncEngine


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    backoff_base=st.floats(min_value=1.1, max_value=10.0, allow_nan=False, allow_infinity=False),
    attempt=st.integers(min_value=0, max_value=10),
)
def test_backoff_delay_is_base_to_the_power_of_attempt(backoff_base, attempt):
    """Backoff delay for attempt n equals backoff_base^n."""
    engine = SyncEngine.__new__(SyncEngine)
    engine._backoff_base = backoff_base
    engine._max_retries = 20

    delay = engine.get_backoff_delay(attempt)
    expected = backoff_base ** attempt
    assert abs(delay - expected) < 1e-9, f"Expected {expected}, got {delay}"


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    max_retries=st.integers(min_value=1, max_value=10),
    backoff_base=st.floats(min_value=1.5, max_value=5.0, allow_nan=False, allow_infinity=False),
)
def test_backoff_increases_monotonically(max_retries, backoff_base):
    """Each successive backoff delay is strictly greater than the previous."""
    engine = SyncEngine.__new__(SyncEngine)
    engine._backoff_base = backoff_base
    engine._max_retries = max_retries

    delays = [engine.get_backoff_delay(i) for i in range(max_retries)]
    for i in range(1, len(delays)):
        assert delays[i] > delays[i - 1], (
            f"Delay at attempt {i} ({delays[i]}) not greater than {i-1} ({delays[i-1]})"
        )
