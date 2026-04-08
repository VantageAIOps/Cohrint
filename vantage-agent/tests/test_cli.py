"""Tests for CLI argument parsing, command handling, and main() dispatch."""
from __future__ import annotations

import sys
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from vantage_agent.cli import parse_args, _handle_command, _print_summary
from vantage_agent.cost_tracker import SessionCost


def _make_client(model="claude-sonnet-4-6"):
    client = MagicMock()
    client.model = model
    client.cwd = "/tmp"
    client.optimization = True
    client.cost = SessionCost(model=model)
    client.permissions = MagicMock()
    client.permissions.status.return_value = (set(), set())
    return client


# ── parse_args ────────────────────────────────────────────────────────────────

def test_parse_args_defaults():
    with patch.object(sys, "argv", ["vantageai-agent"]):
        args = parse_args()
    assert args.prompt == []
    assert args.model is None
    assert args.max_tokens == 16384
    assert args.no_optimize is False
    assert args.backend is None
    assert args.resume is None


def test_parse_args_oneshot_prompt():
    with patch.object(sys, "argv", ["vantageai-agent", "hello", "world"]):
        args = parse_args()
    assert args.prompt == ["hello", "world"]


def test_parse_args_backend_choices():
    for backend in ("api", "claude", "codex", "gemini"):
        with patch.object(sys, "argv", ["vantageai-agent", "--backend", backend]):
            args = parse_args()
        assert args.backend == backend


def test_parse_args_invalid_backend_exits():
    with patch.object(sys, "argv", ["vantageai-agent", "--backend", "llama"]):
        with pytest.raises(SystemExit):
            parse_args()


def test_parse_args_resume():
    with patch.object(sys, "argv", ["vantageai-agent", "--resume", "abc123"]):
        args = parse_args()
    assert args.resume == "abc123"


def test_parse_args_no_optimize():
    with patch.object(sys, "argv", ["vantageai-agent", "--no-optimize"]):
        args = parse_args()
    assert args.no_optimize is True


# ── _handle_command ───────────────────────────────────────────────────────────

def test_handle_quit_returns_true():
    client = _make_client()
    assert _handle_command("/quit", client) is True
    assert _handle_command("/exit", client) is True
    assert _handle_command("/q", client) is True


def test_handle_help_returns_true():
    client = _make_client()
    assert _handle_command("/help", client) is True


def test_handle_tools_returns_true():
    client = _make_client()
    assert _handle_command("/tools", client) is True


def test_handle_cost_returns_true():
    client = _make_client()
    assert _handle_command("/cost", client) is True


def test_handle_reset_clears_state():
    client = _make_client()
    client.cost.total_cost_usd = 9.99
    assert _handle_command("/reset", client) is True
    client.permissions.reset.assert_called_once()
    client.clear_history.assert_called_once()


def test_handle_optimize_toggle():
    client = _make_client()
    _handle_command("/optimize off", client)
    assert client.optimization is False
    _handle_command("/optimize on", client)
    assert client.optimization is True


def test_handle_model_switch():
    client = _make_client()
    _handle_command("/model claude-opus-4-6", client)
    assert client.model == "claude-opus-4-6"
    assert client.cost.model == "claude-opus-4-6"


def test_handle_allow_known_tool():
    client = _make_client()
    result = _handle_command("/allow Bash", client)
    assert result is True
    client.permissions.approve.assert_called_once()


def test_handle_allow_unknown_tool_does_not_approve():
    client = _make_client()
    _handle_command("/allow NonExistentTool999", client)
    client.permissions.approve.assert_not_called()


def test_handle_unknown_command_returns_true():
    client = _make_client()
    assert _handle_command("/foobar", client) is True


def test_non_command_returns_false():
    client = _make_client()
    assert _handle_command("just a prompt", client) is False
    assert _handle_command("explain main.py", client) is False


# ── _print_summary ────────────────────────────────────────────────────────────

def test_print_summary_no_sessions(capsys):
    # SessionStore is imported inside _print_summary — patch at source
    with patch("vantage_agent.session_store.SessionStore") as MockStore:
        MockStore.return_value.list_all.return_value = []
        MockStore.return_value.total_cost_usd.return_value = 0.0
        _print_summary()
    out = capsys.readouterr().out
    assert "No sessions" in out


def test_print_summary_with_sessions(capsys):
    with patch("vantage_agent.session_store.SessionStore") as MockStore:
        MockStore.return_value.list_all.return_value = [
            {"id": "abc12345xyz", "backend": "api", "cost_summary": {"total_cost_usd": 0.05},
             "messages": ["a", "b", "c", "d"], "last_active_at": "2026-04-08T10:00:00"},
        ]
        MockStore.return_value.total_cost_usd.return_value = 0.05
        _print_summary()
    out = capsys.readouterr().out
    assert "Sessions:" in out
