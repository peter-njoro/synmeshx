"""
Unit tests for the Contexa CLI.
Tests command output, --json flag, offline daemon error, and non-zero exit on failure.
Requirements: 5.1–5.6
"""

from __future__ import annotations

import json
import time
from unittest.mock import patch, MagicMock

import httpx
import pytest
from typer.testing import CliRunner

from contexa.cli.main import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def mock_get(path: str):
    """Return mock API responses keyed by path prefix."""
    if path == "/contexts":
        return [
            {"context_id": "abc-123", "latest_version_tag": "v1", "checksum": "a" * 64,
             "created_at": "2024-01-01T00:00:00", "label": "my-task"},
        ]
    if path.startswith("/contexts/abc-123/versions/"):
        return _mock_version("abc-123", "v1")
    if path.startswith("/contexts/abc-123"):
        return _mock_version("abc-123", "v1")
    if path == "/health":
        return {"status": "ok", "context_store": {"status": "ok"},
                "sync_engine": {"status": "ok"}, "trust_store": {"status": "ok"}}
    if path == "/config":
        return {"daemon_port": 7474, "sync_mode": "hosted", "storage_data_dir": "/tmp",
                "daemon_log_level": "INFO", "daemon_log_output": "stdout",
                "daemon_socket_path": "", "sync_interval_seconds": 60,
                "sync_max_retries": 5, "sync_backoff_base_seconds": 2,
                "relay_endpoint": "", "embeddings_model": ""}
    return {}


def _mock_version(context_id: str, version_tag: str) -> dict:
    return {
        "version_id": "ver-001",
        "context_id": context_id,
        "version_tag": version_tag,
        "parent_version": None,
        "content": {"task": "test"},
        "checksum": "a" * 64,
        "created_at": "2024-01-01T00:00:00",
        "label": "my-task",
    }


# ---------------------------------------------------------------------------
# context list
# ---------------------------------------------------------------------------

def test_context_list_human_readable():
    with patch("contexa.cli.commands.context.api_get", side_effect=mock_get):
        result = runner.invoke(app, ["context", "list"])
    assert result.exit_code == 0
    assert "abc-123" in result.output
    assert "my-task" in result.output


def test_context_list_json_flag():
    with patch("contexa.cli.commands.context.api_get", side_effect=mock_get):
        result = runner.invoke(app, ["context", "list", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert data[0]["context_id"] == "abc-123"


def test_context_list_empty():
    with patch("contexa.cli.commands.context.api_get", return_value=[]):
        result = runner.invoke(app, ["context", "list"])
    assert result.exit_code == 0
    assert "No contexts found" in result.output


# ---------------------------------------------------------------------------
# context get
# ---------------------------------------------------------------------------

def test_context_get_human_readable():
    with patch("contexa.cli.commands.context.api_get", side_effect=mock_get):
        result = runner.invoke(app, ["context", "get", "abc-123"])
    assert result.exit_code == 0
    assert "abc-123" in result.output
    assert "v1" in result.output


def test_context_get_json_flag():
    with patch("contexa.cli.commands.context.api_get", side_effect=mock_get):
        result = runner.invoke(app, ["context", "get", "abc-123", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["context_id"] == "abc-123"


def test_context_get_specific_version():
    with patch("contexa.cli.commands.context.api_get", side_effect=mock_get):
        result = runner.invoke(app, ["context", "get", "abc-123", "--version", "v1"])
    assert result.exit_code == 0
    assert "abc-123" in result.output


# ---------------------------------------------------------------------------
# context create
# ---------------------------------------------------------------------------

def test_context_create_with_json_flag():
    mock_response = _mock_version("new-ctx", "abc12345")
    with patch("contexa.cli.commands.context.api_post", return_value=mock_response):
        result = runner.invoke(app, ["context", "create", "--json", '{"key": "value"}'])
    assert result.exit_code == 0
    assert "new-ctx" in result.output


def test_context_create_with_label():
    mock_response = {**_mock_version("new-ctx", "abc12345"), "label": "my-label"}
    with patch("contexa.cli.commands.context.api_post", return_value=mock_response):
        result = runner.invoke(app, ["context", "create", "--json", '{"x": 1}', "--label", "my-label"])
    assert result.exit_code == 0
    assert "new-ctx" in result.output


def test_context_create_invalid_json():
    result = runner.invoke(app, ["context", "create", "--json", "not-json"])
    assert result.exit_code == 1
    assert "invalid JSON" in result.output


def test_context_create_no_input():
    result = runner.invoke(app, ["context", "create"])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# context delete
# ---------------------------------------------------------------------------

def test_context_delete_with_yes_flag():
    with patch("contexa.cli.commands.context.api_delete") as mock_del:
        result = runner.invoke(app, ["context", "delete", "abc-123", "--yes"])
    assert result.exit_code == 0
    assert "Deleted" in result.output
    mock_del.assert_called_once_with("/contexts/abc-123")


def test_context_delete_aborted():
    result = runner.invoke(app, ["context", "delete", "abc-123"], input="n\n")
    assert result.exit_code == 0
    assert "Aborted" in result.output


# ---------------------------------------------------------------------------
# context label
# ---------------------------------------------------------------------------

def test_context_label_set():
    mock_response = {"context_id": "abc-123", "latest_version_tag": "v1",
                     "checksum": "a" * 64, "created_at": "2024-01-01T00:00:00", "label": "new-label"}
    with patch("contexa.cli.commands.context.api_patch", return_value=mock_response):
        result = runner.invoke(app, ["context", "label", "abc-123", "new-label"])
    assert result.exit_code == 0
    assert "new-label" in result.output


# ---------------------------------------------------------------------------
# config show
# ---------------------------------------------------------------------------

def test_config_show_human_readable():
    with patch("contexa.cli.commands.config.api_get", side_effect=mock_get):
        result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert "7474" in result.output


def test_config_show_json_flag():
    with patch("contexa.cli.commands.config.api_get", side_effect=mock_get):
        result = runner.invoke(app, ["config", "show", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["daemon_port"] == 7474


# ---------------------------------------------------------------------------
# Offline daemon error (Req 5.6)
# ---------------------------------------------------------------------------

def test_offline_daemon_shows_clear_message():
    """When daemon is offline, CLI prints a clear message — not a raw connection error."""
    with patch("contexa.cli.client.httpx.get", side_effect=httpx.ConnectError("refused")):
        result = runner.invoke(app, ["context", "list"])
    assert result.exit_code == 1
    assert "not running" in result.output.lower() or "not running" in (result.stderr or "").lower()


def test_offline_daemon_exits_nonzero():
    with patch("contexa.cli.client.httpx.get", side_effect=httpx.ConnectError("refused")):
        result = runner.invoke(app, ["context", "list"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Non-zero exit on API error (Req 5.4)
# ---------------------------------------------------------------------------

def test_api_error_exits_nonzero():
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.json.return_value = {"error": "not_found"}
    with patch("contexa.cli.client.httpx.get",
               side_effect=httpx.HTTPStatusError("not found", request=MagicMock(), response=mock_resp)):
        result = runner.invoke(app, ["context", "get", "bad-id"])
    assert result.exit_code != 0
