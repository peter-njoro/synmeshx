# Feature: contexa-core, Property 25: SDK Connection Error
"""
For any SDK method call when the daemon is not running, the SDK must raise
ContexaConnectionError and must not surface a raw httpx.ConnectError.
Validates: Requirements 13.5
"""

from __future__ import annotations

import pytest
from unittest.mock import patch
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

import httpx

from contexa.sdk import ContexaClient, ContexaConnectionError


SDK_METHODS = [
    ("list_contexts", [], {}),
    ("get_context", ["some-id"], {}),
    ("create_context", [{"x": 1}], {}),
    ("update_context", ["some-id", {"x": 2}], {}),
    ("delete_context", ["some-id"], {}),
    ("health", [], {}),
    ("get_config", [], {}),
    ("get_sync_log", [], {}),
    ("trigger_sync", [], {}),
]


@pytest.mark.parametrize("method_name,args,kwargs", SDK_METHODS)
def test_connection_error_raises_contexa_error(method_name, args, kwargs):
    """Every SDK method raises ContexaConnectionError when daemon is offline."""
    client = ContexaClient()

    with patch("httpx.get", side_effect=httpx.ConnectError("refused")), \
         patch("httpx.post", side_effect=httpx.ConnectError("refused")), \
         patch("httpx.put", side_effect=httpx.ConnectError("refused")), \
         patch("httpx.patch", side_effect=httpx.ConnectError("refused")), \
         patch("httpx.delete", side_effect=httpx.ConnectError("refused")):

        method = getattr(client, method_name)
        with pytest.raises(ContexaConnectionError):
            method(*args, **kwargs)


@settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(base_url=st.just("http://127.0.0.1:7474"))
def test_connection_error_includes_base_url(base_url):
    """ContexaConnectionError message includes the base URL."""
    client = ContexaClient(base_url=base_url)

    with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
        try:
            client.list_contexts()
            assert False, "Should have raised"
        except ContexaConnectionError as e:
            assert base_url in str(e)
