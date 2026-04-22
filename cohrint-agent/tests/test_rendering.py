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

from cohrint_agent.renderer import (
    render_text_delta,
    render_text_complete,
    render_tool_use_start,
    render_tool_result,
    render_thinking,
    render_cost_summary,
    render_permission_denied,
    render_error,
    render_optimization_preview,
    render_cohrint_analysis,
    render_assistant_header,
    make_waiting_spinner,
)
from cohrint_agent.permissions import PermissionManager
from cohrint_agent.api_client import AgentClient
from cohrint_agent.cost_tracker import SessionCost


def _capture_output(fn, *args, **kwargs) -> str:
    """Capture rich console output to a plain string (no ANSI codes)."""
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=120, no_color=True)
    with patch("cohrint_agent.renderer.console", console):
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
        with patch("cohrint_agent.renderer.console", console):
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
        long_text = "x" * 800
        output = _capture_output(render_thinking, long_text)
        # Some form of truncation indicator must appear for huge thinking
        # blocks so we don't flood the terminal.
        assert "…" in output or "..." in output

    def test_truncates_at_word_boundary(self):
        # The old 200-char cap sliced sentences mid-word, producing
        # "never i..." cliffhangers in the terminal. The renderer must
        # now cut at the nearest whitespace before the cap so the
        # truncated preview ends with a complete word, never a partial
        # one like "hallucin" or "i".
        #
        # Construct a text where a naive hard cut at max_chars would
        # definitely land mid-word: concatenate without spaces in the
        # padding, then insert a known word at the cap position.
        words = [
            "alpha", "beta", "gamma", "delta", "epsilon", "zeta",
            "eta", "theta", "iota", "kappa", "lambda", "mu", "nu",
        ]
        # Build text that we know will force truncation with a word at
        # the boundary — if the renderer slices mid-word, the output
        # will contain a trailing partial like "epsilo…".
        text = (" ".join(words) + " ") * 30
        output = _capture_output(render_thinking, text, 100)
        assert "…" in output
        # The string before the ellipsis must end with one of our full
        # words, never a partial one.
        idx = output.rfind("…")
        before = output[:idx].rstrip()
        last_word = before.rsplit(None, 1)[-1] if before else ""
        # last_word must either be empty (hit max cap with no spaces)
        # or one of the original full words — never a truncation like
        # "alph" or "epsilo".
        assert last_word == "" or last_word in words, (
            f"truncated mid-word to {last_word!r} (full output: {output!r})"
        )

    def test_short_thinking_shown_in_full(self):
        # Under the cap, no truncation indicator should appear.
        text = "Short reasoning here."
        output = _capture_output(render_thinking, text)
        assert "…" not in output and "..." not in output.replace("Short reasoning here.", "")


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
        with patch("cohrint_agent.renderer.console", console):
            render_text_delta("I'll help you ")
            render_text_delta("fix that bug.")
            render_text_complete("I'll help you fix that bug.")
        output = buf.getvalue()
        assert "fix that bug" in output

    def test_turn_2_tool_use_and_result(self):
        """Second turn: model calls a tool, gets result."""
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=False, width=120, no_color=True)
        with patch("cohrint_agent.renderer.console", console):
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
        with patch("cohrint_agent.renderer.console", console):
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
        with patch("cohrint_agent.renderer.console", console):
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
        with patch("cohrint_agent.renderer.console", console):
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

    @patch("cohrint_agent.api_client.anthropic.Anthropic")
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

    @patch("cohrint_agent.api_client.anthropic.Anthropic")
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

    @patch("cohrint_agent.api_client.anthropic.Anthropic")
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
        from cohrint_agent.cli import BANNER
        assert "Cohrint Agent" in BANNER
        assert "/help" in BANNER
        assert "/allow" in BANNER
        assert "/cost" in BANNER
        assert "/optimize" in BANNER

    def test_handle_command_cost(self):
        """The /cost command renders cost summary."""
        from cohrint_agent.cli import _handle_command
        mock_client = MagicMock()
        mock_client.cost = SessionCost(model="claude-sonnet-4-6")
        mock_client.cost.total_input = 1000
        mock_client.cost.total_output = 500
        mock_client.cost.total_cost_usd = 0.0105
        mock_client.cost.prompt_count = 1
        result = _handle_command("/cost", mock_client)
        assert result is True

    def test_handle_command_optimize_toggle(self):
        from cohrint_agent.cli import _handle_command
        mock_client = MagicMock()
        mock_client.optimization = False
        _handle_command("/optimize on", mock_client)
        assert mock_client.optimization is True

    def test_handle_command_model_switch(self):
        from cohrint_agent.cli import _handle_command
        mock_client = MagicMock()
        mock_client.model = "claude-sonnet-4-6"
        mock_client.cost = MagicMock()
        _handle_command("/model claude-opus-4-6", mock_client)
        assert mock_client.model == "claude-opus-4-6"

    def test_unknown_command(self):
        from cohrint_agent.cli import _handle_command
        mock_client = MagicMock()
        result = _handle_command("/foobar", mock_client)
        assert result is True  # Handled (printed error)


# ---------------------------------------------------------------------------
# render_cost_summary_v2 tests
# ---------------------------------------------------------------------------

def _capture_v2(**kwargs) -> str:
    buf = io.StringIO()
    con = Console(file=buf, no_color=True)
    import cohrint_agent.renderer as r
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


# ── Section: Optimization preview (pre-send) ────────────────────────────
#
# Shown BEFORE the prompt is dispatched to the backend. The user should see
# what was stripped and how many tokens/dollars they just saved — the previous
# UX only showed this afterward, which was too late to be useful.


from cohrint_agent.optimizer import OptimizationResult


def _opt(original, optimized, original_tokens, optimized_tokens, changes=None):
    saved = max(0, original_tokens - optimized_tokens)
    pct = round(saved / original_tokens * 100) if original_tokens else 0
    return OptimizationResult(
        original=original, optimized=optimized,
        original_tokens=original_tokens, optimized_tokens=optimized_tokens,
        saved_tokens=saved, saved_percent=pct, changes=changes or [],
    )


class TestOptimizationPreview:
    def test_shows_token_savings(self):
        result = _opt("verbose", "short", 100, 40, ["removed filler phrases"])
        out = _capture_output(render_optimization_preview, result, "claude-sonnet-4-6")
        assert "100" in out and "40" in out
        assert "60" in out or "60%" in out

    def test_shows_dollar_savings(self):
        # 60 input tokens saved on sonnet @ $3/M = $0.00018
        result = _opt("verbose", "short", 100, 40)
        out = _capture_output(render_optimization_preview, result, "claude-sonnet-4-6")
        # Render as cents with 4 decimals — user sees "$0.0002" or similar
        assert "$" in out

    def test_shows_optimized_prompt_text(self):
        # Post-feedback: we no longer print the bullet list of optimizer
        # layers ("removed filler phrases: …"). Instead we show the
        # actual optimized prompt text in dim so the user sees exactly
        # what's about to be sent to the model.
        result = _opt(
            "please could you fix the login bug",
            "fix the login bug",
            120, 60,
            ["removed filler phrases: \"please could you\""],
        )
        out = _capture_output(render_optimization_preview, result, "claude-sonnet-4-6")
        assert "fix the login bug" in out

    def test_does_not_show_algorithm_change_list(self):
        # Guardrail: algorithmic internals must NOT leak into the preview.
        # These phrases are the historical render_optimization_preview
        # bullet-list output that we are now suppressing.
        result = _opt(
            "I'd like you to fix the login bug in order to unblock the team",
            "fix the login bug to unblock the team",
            200, 90,
            [
                "removed filler phrases: \"I'd like you to\"",
                "rewrote verbose phrases: \"in order to\" → \"to\"",
                "stripped filler words: really, basically",
            ],
        )
        out = _capture_output(render_optimization_preview, result, "claude-sonnet-4-6")
        assert "removed filler phrases" not in out.lower()
        assert "rewrote verbose phrases" not in out.lower()
        assert "stripped filler words" not in out.lower()
        # The header's `200→90 tokens` arrow is fine; only the
        # change-list rewrite arrows like `"in order to" → "to"` must
        # be absent. Test by asserting no quoted-rewrite pattern lands.
        assert '" → "' not in out
        assert "+" + " more" not in out  # "+N more" summary suppressed

    def test_truncates_long_optimized_text(self):
        # Even after optimization a prompt can be thousands of chars —
        # we cap the dim preview at a terminal-friendly length and
        # append an ellipsis so users see the head of their prompt
        # without drowning the analysis block below it.
        big = "fix " * 500  # ~2000 chars of optimized prompt
        result = _opt("x " * 800, big, 800, 500)
        out = _capture_output(render_optimization_preview, result, "claude-sonnet-4-6")
        # The preview must be truncated — nowhere near the full 2000
        # chars should land in terminal output.
        assert "…" in out or "..." in out
        # And it must stay far under the full prompt length.
        assert len(out) < len(big) + 400  # header + dim framing ~ 400 chars

    def test_no_savings_skips_preview(self):
        # If nothing was saved (already optimal), don't clutter the terminal.
        result = _opt("fix bug", "fix bug", 3, 3)
        out = _capture_output(render_optimization_preview, result, "claude-sonnet-4-6")
        assert out.strip() == "", f"Expected empty output, got: {out!r}"

    def test_sanitizes_optimized_text(self):
        # The optimized text comes directly from user input, so must be
        # scrubbed before echoing — an OSC-52 payload smuggled in a
        # prompt must not reach the terminal (T-SAFETY.5/6/12).
        optimized = "fix the bug \x1b]52;c;BADSTUFF\x07 now"
        result = _opt("verbose original", optimized, 120, 60)
        out = _capture_output(render_optimization_preview, result, "claude-sonnet-4-6")
        assert "\x1b]52" not in out


class TestWaitingSpinner:
    """The waiting spinner is what prevents users from thinking the CLI is
    stuck while the backend subprocess (claude / codex / gemini) boots and
    the model generates its first token. It MUST:
      - be a context manager (usable with ``with``)
      - not raise when stdout is not a TTY (non-interactive pipes, CI)
      - auto-stop when the context exits (so subsequent prints render
        cleanly below it, not mid-spinner)
      - expose a ``stop_immediate()`` method for the backend to clear the
        spinner the moment the first event arrives (before printing text)
    """

    def test_is_context_manager(self):
        with make_waiting_spinner("Thinking"):
            pass  # no crash

    def test_nested_enter_exit_safe(self):
        # Double enter/exit must not raise — the backend calls stop()
        # eagerly on first event AND on exit via the `with` block.
        spinner = make_waiting_spinner("Thinking")
        with spinner:
            spinner.stop_immediate()  # safe to call before __exit__
            spinner.stop_immediate()  # safe to call twice

    def test_noop_when_not_tty(self):
        # In a non-tty environment the spinner must be a no-op — otherwise
        # ANSI escapes leak into piped / logged output (`cohrint-agent ...
        # | tee log`). We verify by capturing stdout: nothing rich-specific
        # should appear.
        import sys
        from io import StringIO
        import cohrint_agent.renderer as r
        fake_out = StringIO()
        buf = Console(file=fake_out, force_terminal=False, width=120, no_color=True)
        orig = r.console
        r.console = buf
        try:
            with make_waiting_spinner("Thinking"):
                pass
        finally:
            r.console = orig
        # A real spinner emits dots/ticks via cursor control. In non-tty
        # Rich suppresses output, so the buffer stays empty or contains
        # only plain text (no \x1b[ escape).
        out = fake_out.getvalue()
        assert "\x1b[" not in out

    def test_custom_label_shown(self):
        # Label is visible in terminal rendering — we verify the factory
        # accepts and stores it for later display (we can't easily intercept
        # the live-updating status text in a test).
        spinner = make_waiting_spinner("Running tool")
        assert spinner is not None


class TestAssistantHeader:
    def test_prints_claude_banner(self):
        out = _capture_output(render_assistant_header, "claude")
        assert "Claude" in out or "claude" in out

    def test_honors_custom_label(self):
        out = _capture_output(render_assistant_header, "gpt-4o")
        assert "gpt-4o" in out


class TestCohrintAnalysis:
    """Post-response analysis block — consolidates optimization savings,
    guardrails, anomaly, recommendation, and cost/tokens for the turn."""

    def _call(self, **overrides):
        defaults = dict(
            optimization=_opt("x", "y", 100, 50, ["removed filler"]),
            model="claude-sonnet-4-6",
            guardrail_hedge_detected=False,
            guardrail_active=["hallucination"],
            anomaly_line=None,
            recommendation=None,
            turn_input_tokens=500,
            turn_output_tokens=300,
            turn_cost_usd=0.0045,
            session_cost_usd=0.0090,
        )
        defaults.update(overrides)
        return _capture_output(render_cohrint_analysis, **defaults)

    def test_shows_cost_saved(self):
        out = self._call()
        assert "saved" in out.lower()
        assert "$" in out

    def test_shows_tokens_and_cost_for_turn(self):
        out = self._call(turn_input_tokens=500, turn_output_tokens=300, turn_cost_usd=0.0045)
        assert "800" in out  # total this turn
        assert "0.0045" in out

    def test_shows_session_total(self):
        out = self._call(session_cost_usd=0.0090)
        assert "0.0090" in out

    def test_shows_hedge_detected(self):
        out = self._call(guardrail_hedge_detected=True, guardrail_active=["hallucination"])
        assert "declined to fabricate" in out.lower() or "hedge" in out.lower() or "verify independently" in out.lower()

    def test_shows_no_hedge_when_guardrail_active(self):
        out = self._call(guardrail_hedge_detected=False, guardrail_active=["hallucination"])
        assert "no hedge" in out.lower() or "double-check" in out.lower()

    def test_omits_guardrail_line_when_not_active(self):
        out = self._call(guardrail_active=[])
        assert "hedge" not in out.lower()
        assert "hallucination" not in out.lower()

    def test_shows_anomaly_when_present(self):
        out = self._call(anomaly_line="Cost anomaly: $0.05 this turn vs $0.01 avg (5.0x)")
        assert "anomaly" in out.lower()
        assert "5.0x" in out

    def test_omits_anomaly_when_absent(self):
        out = self._call(anomaly_line=None)
        assert "anomaly" not in out.lower()

    def test_shows_recommendation_when_present(self):
        out = self._call(recommendation="Use ! prefix for shell commands")
        assert "Use ! prefix" in out

    def test_omits_optimization_line_when_no_savings(self):
        # Zero-savings turns should NOT print a misleading "0 tokens saved" row.
        result = _opt("short", "short", 5, 5)
        out = self._call(optimization=result)
        # "saved" still allowed if it appears in an anomaly or recommendation —
        # we only forbid a spurious "0 tokens saved" row.
        assert "0 tokens" not in out or "saved" not in out.lower().split("\n")[0]

    def test_analysis_header_present(self):
        out = self._call()
        # A visual divider / header identifies this block distinctly from
        # Claude's answer above it.
        assert "Cohrint" in out or "cohrint" in out or "analysis" in out.lower()

    def test_shows_cache_saved_when_cache_hit(self):
        # Semantic cache / prompt-cache hit produced $ savings this turn.
        out = self._call(cache_saved_usd=0.0034, cache_read_tokens=12000)
        assert "ache" in out  # "Cache" or "cache"
        assert "0.0034" in out
        assert "12,000" in out or "12000" in out

    def test_omits_cache_line_when_no_cache(self):
        out = self._call(cache_saved_usd=0.0, cache_read_tokens=0)
        assert "cache saved" not in out.lower()

    def test_combined_savings_shown(self):
        # Turn with BOTH optimizer + cache savings — both should be visible.
        opt = OptimizationResult(
            original="x", optimized="y",
            original_tokens=500, optimized_tokens=200,
            saved_tokens=300, saved_percent=60, changes=[],
        )
        out = self._call(
            optimization=opt,
            cache_saved_usd=0.0050,
            cache_read_tokens=20000,
        )
        assert "Tokens saved" in out
        assert "Cost saved" in out
        assert "ache" in out
        assert "0.0050" in out
