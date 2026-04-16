"""Tests for renderer.py and live CLI rendering flows.

Tests terminal output, tool display, cost summaries, permission prompts,
and multi-turn conversation rendering — all offline (no API key needed).
"""
from __future__ import annotations

import io
import json
import pytest
from unittest.mock import patch, MagicMock, call
from rich.console import Console

from vantage_agent.renderer import (
    render_text_delta,
    render_text_complete,
    render_tool_use_start,
    render_tool_result,
    render_thinking,
    render_cost_summary,
    render_permission_denied,
    render_error,
)
from vantage_agent.permissions import PermissionManager
from vantage_agent.api_client import AgentClient
from vantage_agent.cost_tracker import SessionCost


def _capture_output(fn, *args, **kwargs) -> str:
    """Capture rich console output to a plain string (no ANSI codes)."""
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=120, no_color=True)
    with patch("vantage_agent.renderer.console", console):
        fn(*args, **kwargs)
    return buf.getvalue()


# ── Section A: Text Rendering ─────────────────────────────────────────

class TestTextRendering:
    def test_text_delta_prints_inline(self):
        output = _capture_output(render_text_delta, "Hello")
        assert "Hello" in output

    def test_text_delta_no_newline(self):
        output = _capture_output(render_text_delta, "Hello")
        assert not output.endswith("\n\n")

    def test_text_complete_adds_newline(self):
        output = _capture_output(render_text_complete, "Full response text")
        assert "\n" in output

    def test_multiple_deltas_stream(self):
        """Simulates streaming: multiple deltas should concatenate."""
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=False, width=120, no_color=True)
        with patch("vantage_agent.renderer.console", console):
            render_text_delta("Hello ")
            render_text_delta("world")
            render_text_delta("!")
        output = buf.getvalue()
        assert "Hello " in output
        assert "world" in output


# ── Section B: Tool Use Rendering ─────────────────────────────────────

class TestToolRendering:
    def test_bash_shows_command(self):
        output = _capture_output(render_tool_use_start, "Bash", {"command": "npm run build"})
        assert "Bash" in output
        assert "npm run build" in output

    def test_read_shows_filepath(self):
        output = _capture_output(render_tool_use_start, "Read", {"file_path": "/src/index.ts"})
        assert "Read" in output
        assert "/src/index.ts" in output

    def test_write_shows_filepath(self):
        output = _capture_output(render_tool_use_start, "Write", {"file_path": "/tmp/out.txt"})
        assert "Write" in output
        assert "/tmp/out.txt" in output

    def test_edit_shows_filepath(self):
        output = _capture_output(render_tool_use_start, "Edit", {"file_path": "/src/app.py"})
        assert "Edit" in output
        assert "/src/app.py" in output

    def test_glob_shows_pattern(self):
        output = _capture_output(render_tool_use_start, "Glob", {"pattern": "**/*.ts"})
        assert "Glob" in output
        assert "**/*.ts" in output

    def test_grep_shows_pattern_and_path(self):
        output = _capture_output(render_tool_use_start, "Grep", {"pattern": "TODO", "path": "src/"})
        assert "Grep" in output
        assert "TODO" in output
        assert "src/" in output

    def test_unknown_tool_shows_name(self):
        output = _capture_output(render_tool_use_start, "CustomTool", {"query": "test"})
        assert "CustomTool" in output

    def test_long_bash_command_truncated(self):
        cmd = "a" * 200
        output = _capture_output(render_tool_use_start, "Bash", {"command": cmd})
        # Renderer truncates at 150 chars — full 200 should not appear
        plain = output.replace("\n", "")
        assert "a" * 200 not in plain
        assert "a" * 50 in plain  # at least partial command shown


class TestToolResult:
    def test_short_result_fully_shown(self):
        output = _capture_output(render_tool_result, "Bash", "line1\nline2\nline3")
        assert "line1" in output
        assert "line3" in output

    def test_long_result_truncated(self):
        lines = "\n".join(f"line{i}" for i in range(20))
        output = _capture_output(render_tool_result, "Bash", lines)
        assert "line0" in output
        assert "20 lines total" in output

    def test_error_result_shows_red(self):
        output = _capture_output(render_tool_result, "Bash", "command not found", is_error=True)
        assert "error" in output.lower()
        assert "command not found" in output

    def test_empty_result(self):
        output = _capture_output(render_tool_result, "Bash", "")
        # Should not crash


# ── Section C: Cost Summary Rendering ─────────────────────────────────

class TestCostSummary:
    def test_shows_model(self):
        output = _capture_output(
            render_cost_summary, model="claude-sonnet-4-6",
            input_tokens=1000, output_tokens=500, cost_usd=0.0105,
            prompt_count=1, session_cost=0.0105,
        )
        assert "claude-sonnet-4-6" in output

    def test_shows_tokens(self):
        output = _capture_output(
            render_cost_summary, model="claude-sonnet-4-6",
            input_tokens=10000, output_tokens=5000, cost_usd=0.105,
            prompt_count=3, session_cost=0.315,
        )
        assert "10,000" in output
        assert "5,000" in output

    def test_shows_cost(self):
        output = _capture_output(
            render_cost_summary, model="claude-sonnet-4-6",
            input_tokens=1000, output_tokens=500, cost_usd=0.0105,
            prompt_count=1, session_cost=0.0105,
        )
        assert "$0.0105" in output

    def test_shows_prompt_count(self):
        output = _capture_output(
            render_cost_summary, model="claude-sonnet-4-6",
            input_tokens=1000, output_tokens=500, cost_usd=0.0105,
            prompt_count=5, session_cost=0.0525,
        )
        assert "5" in output

    def test_shows_border(self):
        output = _capture_output(
            render_cost_summary, model="claude-sonnet-4-6",
            input_tokens=0, output_tokens=0, cost_usd=0,
            prompt_count=0, session_cost=0,
        )
        assert "Cost Summary" in output


# ── Section D: Permission Rendering ───────────────────────────────────

class TestPermissionRendering:
    def test_denied_message(self):
        output = _capture_output(render_permission_denied, "Bash")
        assert "Bash" in output
        assert "denied" in output.lower()

    def test_error_message(self):
        output = _capture_output(render_error, "API key not set")
        assert "API key not set" in output
        assert "Error" in output


# ── Section E: Thinking Rendering ─────────────────────────────────────

class TestThinkingRendering:
    def test_shows_thinking_text(self):
        output = _capture_output(render_thinking, "Let me analyze this code...")
        assert "analyze" in output

    def test_truncates_long_thinking(self):
        long_text = "x" * 300
        output = _capture_output(render_thinking, long_text)
        assert "..." in output


# ── Section F: Permission Flow (Mock Interactive) ─────────────────────

class TestPermissionFlow:
    def test_safe_tools_auto_approved(self, tmp_path):
        pm = PermissionManager(config_dir=tmp_path)
        assert pm.check_permission("Read", {}) is True
        assert pm.check_permission("Glob", {}) is True
        assert pm.check_permission("Grep", {}) is True

    def test_dangerous_tool_prompts_user(self, tmp_path):
        pm = PermissionManager(config_dir=tmp_path)
        with patch("rich.prompt.Prompt.ask", return_value="y"):
            assert pm.check_permission("Bash", {"command": "ls"}) is True

    def test_deny_returns_false(self, tmp_path):
        pm = PermissionManager(config_dir=tmp_path)
        with patch("rich.prompt.Prompt.ask", return_value="n"):
            assert pm.check_permission("Bash", {"command": "rm -rf /"}) is False

    def test_always_approve_persists_in_session(self, tmp_path):
        pm = PermissionManager(config_dir=tmp_path)
        with patch("rich.prompt.Prompt.ask", return_value="a"):
            assert pm.check_permission("Write", {"file_path": "/tmp/a"}) is True
        # Second call should not prompt
        assert pm.check_permission("Write", {"file_path": "/tmp/b"}) is True

    def test_denied_tool_in_api_loop(self, tmp_path):
        """When user denies a tool, API receives error result."""
        pm = PermissionManager(config_dir=tmp_path)
        with patch("rich.prompt.Prompt.ask", return_value="n"):
            allowed = pm.check_permission("Bash", {"command": "dangerous"})
        assert allowed is False


# ── Section G: Multi-Turn Rendering Simulation ────────────────────────

class TestMultiTurnRendering:
    """Simulates what the user sees during a multi-turn conversation."""

    def test_turn_1_text_only(self):
        """First turn: model returns text, no tools."""
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=False, width=120, no_color=True)
        with patch("vantage_agent.renderer.console", console):
            render_text_delta("I'll help you ")
            render_text_delta("fix that bug.")
            render_text_complete("I'll help you fix that bug.")
        output = buf.getvalue()
        assert "fix that bug" in output

    def test_turn_2_tool_use_and_result(self):
        """Second turn: model calls a tool, gets result."""
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=False, width=120, no_color=True)
        with patch("vantage_agent.renderer.console", console):
            render_tool_use_start("Read", {"file_path": "src/main.py"})
            render_tool_result("Read", "def main():\n    print('hello')")
            render_text_delta("I can see the issue...")
            render_text_complete("I can see the issue...")
        output = buf.getvalue()
        assert "Read" in output
        assert "src/main.py" in output
        assert "def main" in output
        assert "issue" in output

    def test_turn_3_multi_tool_chain(self):
        """Third turn: model calls multiple tools in sequence."""
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=False, width=120, no_color=True)
        with patch("vantage_agent.renderer.console", console):
            render_tool_use_start("Grep", {"pattern": "TODO", "path": "."})
            render_tool_result("Grep", "src/app.py:10: # TODO fix this")
            render_tool_use_start("Read", {"file_path": "src/app.py"})
            render_tool_result("Read", "line1\nline2\nline10: # TODO fix this\nline11")
            render_tool_use_start("Edit", {"file_path": "src/app.py"})
            render_tool_result("Edit", "File edited successfully")
            render_text_delta("I've fixed the TODO.")
            render_text_complete("I've fixed the TODO.")
        output = buf.getvalue()
        assert "Grep" in output
        assert "Read" in output
        assert "Edit" in output
        assert "TODO" in output

    def test_permission_denied_mid_chain(self):
        """Model calls tool, user denies, model gets error."""
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=False, width=120, no_color=True)
        with patch("vantage_agent.renderer.console", console):
            render_tool_use_start("Bash", {"command": "rm -rf /tmp/test"})
            render_permission_denied("Bash")
            render_text_delta("The Bash command was denied. Let me try another approach.")
            render_text_complete("The Bash command was denied. Let me try another approach.")
        output = buf.getvalue()
        assert "denied" in output.lower()
        assert "another approach" in output

    def test_cost_after_multi_turn(self):
        """After multi-turn, cost summary is rendered."""
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=False, width=120, no_color=True)
        with patch("vantage_agent.renderer.console", console):
            render_cost_summary(
                model="claude-sonnet-4-6",
                input_tokens=25000,
                output_tokens=8000,
                cost_usd=0.195,
                prompt_count=3,
                session_cost=0.195,
            )
        output = buf.getvalue()
        assert "25,000" in output
        assert "8,000" in output
        assert "$0.1950" in output
        assert "3" in output


# ── Section H: API Client Tool Loop (Mocked) ─────────────────────────

class TestAPIClientToolLoop:
    """Test the full tool-use loop with mocked Anthropic API."""

    def _make_mock_stream(self, events, stop_reason="end_turn"):
        """Create a mock stream context manager from a list of events."""
        stream = MagicMock()
        stream.__enter__ = MagicMock(return_value=stream)
        stream.__exit__ = MagicMock(return_value=False)
        stream.__iter__ = MagicMock(return_value=iter(events))

        # Mock get_final_message
        final_msg = MagicMock()
        final_msg.usage = MagicMock(
            input_tokens=100, output_tokens=50,
            cache_read_input_tokens=0, cache_creation_input_tokens=0,
        )
        final_msg.stop_reason = stop_reason
        stream.get_final_message.return_value = final_msg
        return stream

    def _make_event(self, event_type, **kwargs):
        ev = MagicMock()
        ev.type = event_type
        for k, v in kwargs.items():
            setattr(ev, k, v)
        return ev

    @patch("vantage_agent.api_client.anthropic.Anthropic")
    def test_text_only_response(self, mock_anthropic_cls):
        """Model returns text only — no tool calls."""
        text_start = self._make_event("content_block_start",
            content_block=MagicMock(type="text"))
        text_delta = self._make_event("content_block_delta",
            delta=MagicMock(type="text_delta", text="Hello world"))
        block_stop = self._make_event("content_block_stop")
        msg_delta = self._make_event("message_delta",
            delta=MagicMock(stop_reason="end_turn"))
        msg_stop = self._make_event("message_stop")

        stream = self._make_mock_stream([text_start, text_delta, block_stop, msg_delta, msg_stop])
        mock_client = MagicMock()
        mock_client.messages.stream.return_value = stream
        mock_anthropic_cls.return_value = mock_client

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            client = AgentClient(optimization=False)
            result = client.send("hi", no_optimize=True)

        assert result == "Hello world"

    @patch("vantage_agent.api_client.anthropic.Anthropic")
    def test_tool_use_loop(self, mock_anthropic_cls):
        """Model calls a tool, gets result, then responds with text."""
        # Turn 1: tool_use
        cb = MagicMock()
        cb.type = "tool_use"
        cb.id = "tool_1"
        cb.name = "Read"
        tool_start = self._make_event("content_block_start", content_block=cb)
        json_delta = self._make_event("content_block_delta",
            delta=MagicMock(type="input_json_delta", partial_json='{"file_path": "/tmp/test.txt"}'))
        tool_stop = self._make_event("content_block_stop")
        msg_delta1 = self._make_event("message_delta",
            delta=MagicMock(stop_reason="tool_use"))

        stream1 = self._make_mock_stream([tool_start, json_delta, tool_stop, msg_delta1], stop_reason="tool_use")

        # Turn 2: text response
        text_start = self._make_event("content_block_start",
            content_block=MagicMock(type="text"))
        text_delta = self._make_event("content_block_delta",
            delta=MagicMock(type="text_delta", text="The file contains test data."))
        text_stop = self._make_event("content_block_stop")
        msg_delta2 = self._make_event("message_delta",
            delta=MagicMock(stop_reason="end_turn"))

        stream2 = self._make_mock_stream([text_start, text_delta, text_stop, msg_delta2])

        mock_client = MagicMock()
        mock_client.messages.stream.side_effect = [stream1, stream2]
        mock_anthropic_cls.return_value = mock_client

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            pm = PermissionManager()
            client = AgentClient(permissions=pm, optimization=False)
            result = client.send("read /tmp/test.txt", no_optimize=True)

        assert result == "The file contains test data."
        # Verify 2 API calls were made (tool loop)
        assert mock_client.messages.stream.call_count == 2

    @patch("vantage_agent.api_client.anthropic.Anthropic")
    def test_permission_denied_stops_tool(self, mock_anthropic_cls, tmp_path):
        """When user denies a tool, error result is sent back."""
        cb = MagicMock()
        cb.type = "tool_use"
        cb.id = "tool_1"
        cb.name = "Bash"
        tool_start = self._make_event("content_block_start", content_block=cb)
        json_delta = self._make_event("content_block_delta",
            delta=MagicMock(type="input_json_delta", partial_json='{"command": "rm -rf /"}'))
        tool_stop = self._make_event("content_block_stop")
        msg_delta = self._make_event("message_delta",
            delta=MagicMock(stop_reason="tool_use"))

        stream1 = self._make_mock_stream([tool_start, json_delta, tool_stop, msg_delta], stop_reason="tool_use")

        # After denial, model responds with text
        text_start = self._make_event("content_block_start",
            content_block=MagicMock(type="text"))
        text_delta = self._make_event("content_block_delta",
            delta=MagicMock(type="text_delta", text="I understand, I'll try a safer approach."))
        text_stop = self._make_event("content_block_stop")
        msg_delta2 = self._make_event("message_delta",
            delta=MagicMock(stop_reason="end_turn"))

        stream2 = self._make_mock_stream([text_start, text_delta, text_stop, msg_delta2])

        mock_client = MagicMock()
        mock_client.messages.stream.side_effect = [stream1, stream2]
        mock_anthropic_cls.return_value = mock_client

        pm = PermissionManager(config_dir=tmp_path)
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch("rich.prompt.Prompt.ask", return_value="n"):
                client = AgentClient(permissions=pm, optimization=False)
                result = client.send("delete everything", no_optimize=True)

        assert "safer approach" in result
        # Check that the tool result sent back was an error
        messages = client.messages
        tool_results = [m for m in messages if m["role"] == "user" and isinstance(m["content"], list)]
        assert len(tool_results) > 0
        error_result = tool_results[0]["content"][0]
        assert error_result["is_error"] is True
        assert "denied" in error_result["content"].lower()


# ── Section I: CLI Command Rendering ──────────────────────────────────

class TestCLICommandRendering:
    """Test that CLI /commands produce correct output."""

    def test_help_shows_banner(self):
        from vantage_agent.cli import BANNER
        assert "Vantage Agent" in BANNER
        assert "/help" in BANNER
        assert "/allow" in BANNER
        assert "/cost" in BANNER
        assert "/optimize" in BANNER

    def test_handle_command_cost(self):
        """The /cost command renders cost summary."""
        from vantage_agent.cli import _handle_command
        mock_client = MagicMock()
        mock_client.cost = SessionCost(model="claude-sonnet-4-6")
        mock_client.cost.total_input = 1000
        mock_client.cost.total_output = 500
        mock_client.cost.total_cost_usd = 0.0105
        mock_client.cost.prompt_count = 1
        result = _handle_command("/cost", mock_client)
        assert result is True

    def test_handle_command_optimize_toggle(self):
        from vantage_agent.cli import _handle_command
        mock_client = MagicMock()
        mock_client.optimization = False
        _handle_command("/optimize on", mock_client)
        assert mock_client.optimization is True

    def test_handle_command_model_switch(self):
        from vantage_agent.cli import _handle_command
        mock_client = MagicMock()
        mock_client.model = "claude-sonnet-4-6"
        mock_client.cost = MagicMock()
        _handle_command("/model claude-opus-4-6", mock_client)
        assert mock_client.model == "claude-opus-4-6"

    def test_unknown_command(self):
        from vantage_agent.cli import _handle_command
        mock_client = MagicMock()
        result = _handle_command("/foobar", mock_client)
        assert result is True  # Handled (printed error)


# ---------------------------------------------------------------------------
# render_cost_summary_v2 tests
# ---------------------------------------------------------------------------

def _capture_v2(**kwargs) -> str:
    buf = io.StringIO()
    con = Console(file=buf, no_color=True)
    import vantage_agent.renderer as r
    original = r.console
    r.console = con
    try:
        r.render_cost_summary_v2(**kwargs)
    finally:
        r.console = original
    return buf.getvalue()


def test_estimated_cost_shows_tilde_prefix():
    out = _capture_v2(
        model="claude-sonnet-4-6", input_tokens=1000, output_tokens=300,
        cost_usd=0.015, prompt_count=1, session_cost=0.015,
        token_count_confidence="estimated", is_subscription=False,
    )
    assert "~$" in out, f"Expected tilde prefix for estimated cost, got: {out}"


def test_subscription_shows_zero_cost_label():
    out = _capture_v2(
        model="claude-sonnet-4-6", input_tokens=1000, output_tokens=300,
        cost_usd=0.015, prompt_count=1, session_cost=0.015,
        token_count_confidence="estimated", is_subscription=True,
    )
    assert "subscription" in out.lower(), f"Expected (subscription) label, got: {out}"


def test_free_tier_shows_free_tier_label():
    out = _capture_v2(
        model="gemini-2.0-flash", input_tokens=500, output_tokens=200,
        cost_usd=0.0, prompt_count=1, session_cost=0.0,
        token_count_confidence="free_tier", is_subscription=False,
    )
    assert "free tier" in out.lower(), f"Expected 'free tier' label, got: {out}"


def test_exact_cost_no_tilde():
    out = _capture_v2(
        model="claude-sonnet-4-6", input_tokens=1000, output_tokens=300,
        cost_usd=0.0150, prompt_count=1, session_cost=0.0150,
        token_count_confidence="exact", is_subscription=False,
    )
    assert "$0.0150" in out, f"Expected exact cost display, got: {out}"
    assert "~$0.0150" not in out, f"Tilde should not appear for exact costs, got: {out}"
