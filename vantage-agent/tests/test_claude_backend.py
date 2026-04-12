"""Tests for ClaudeCliBackend stream-json parser (no subprocess spawned)."""
from __future__ import annotations

import json
import queue
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from vantage_agent.backends.claude_backend import ClaudeCliBackend, _parse_stream_event


def _make_event(**kwargs) -> bytes:
    return (json.dumps(kwargs) + "\n").encode()


def test_parse_result_event_extracts_cost_and_session_id():
    event = {
        "type": "result",
        "subtype": "success",
        "total_cost_usd": 0.0523,
        "session_id": "abc-123",
        "usage": {"input_tokens": 500, "output_tokens": 80},
    }
    state = {"result": None}
    _parse_stream_event(event, state, render=False)
    assert state["result"]["total_cost_usd"] == 0.0523
    assert state["result"]["session_id"] == "abc-123"
    assert state["result"]["input_tokens"] == 500
    assert state["result"]["output_tokens"] == 80


def test_parse_assistant_text_event_accumulates_text():
    event = {
        "type": "assistant",
        "message": {
            "content": [{"type": "text", "text": "Hello world"}],
        },
    }
    state = {"text": "", "result": None}
    _parse_stream_event(event, state, render=False)
    assert state["text"] == "Hello world"


def test_parse_rate_limit_event_sets_resets_at():
    future_ts = int(datetime.now(timezone.utc).timestamp()) + 300
    event = {
        "type": "rate_limit_event",
        "rate_limit_info": {"resetsAt": future_ts, "rateLimitType": "five_hour"},
    }
    state = {"result": None, "rate_limit_resets_at": None}
    _parse_stream_event(event, state, render=False)
    assert state["rate_limit_resets_at"] == future_ts


def test_session_id_persisted_between_calls(tmp_path):
    """ClaudeCliBackend stores session_id from result and uses it in next --resume."""
    backend = ClaudeCliBackend(model="claude-sonnet-4-6", config_dir=tmp_path)
    backend._claude_session_id = "prev-session-xyz"

    cmd = backend._build_command(prompt="hello", cwd=str(tmp_path))
    assert "--resume" in cmd
    idx = cmd.index("--resume")
    assert cmd[idx + 1] == "prev-session-xyz"


def test_no_resume_on_first_call(tmp_path):
    backend = ClaudeCliBackend(model="claude-sonnet-4-6", config_dir=tmp_path)
    assert backend._claude_session_id is None
    cmd = backend._build_command(prompt="hello", cwd=str(tmp_path))
    assert "--resume" not in cmd


def test_build_command_includes_required_flags(tmp_path):
    backend = ClaudeCliBackend(model="claude-opus-4-6", config_dir=tmp_path)
    cmd = backend._build_command(prompt="test", cwd="/tmp")
    assert "claude" in cmd[0]
    assert "-p" in cmd
    assert "--output-format" in cmd
    assert "stream-json" in cmd
    assert "--permission-mode" in cmd
    assert "bypassPermissions" in cmd
    assert "--no-session-persistence" in cmd
    assert "--model" in cmd
    assert "claude-opus-4-6" in cmd


def test_capabilities():
    from vantage_agent.backends.base import BackendCapabilities
    backend = ClaudeCliBackend.__new__(ClaudeCliBackend)
    assert backend.capabilities.token_count == "exact"
    assert backend.capabilities.supports_process is False
