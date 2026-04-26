"""Suite 53 — cohrint-agent CLI UX redesign.

End-to-end tests covering the five UX improvements shipped in
``feat/agent-cli-ux-redesign``:

  1. Multi-line / paste-aware REPL input (``repl_input.aggregate_lines``).
  2. Pre-send optimization preview (``render_optimization_preview``).
  3. Assistant stream stage markers (``render_assistant_header``).
  4. Consolidated post-response Cohrint analysis block
     (``render_cohrint_analysis``).
  5. Cost-saved computation (``optimizer.estimated_cost_saved``).

These tests are intentionally CLI-local (no API calls) so they run in CI
without cohrint.com credentials, but they live in ``tests/suites/`` to
satisfy the CLAUDE.md rule "every PR needs tests in tests/suites/".
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from rich.console import Console
from unittest.mock import patch

# Allow imports from cohrint-agent even when pytest is invoked from repo root.
_AGENT_ROOT = Path(__file__).resolve().parents[3] / "cohrint-agent"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from cohrint_agent.optimizer import (
    estimated_cost_saved,
    optimize_prompt,
    OptimizationResult,
)
from cohrint_agent.renderer import (
    render_optimization_preview,
    render_cohrint_analysis,
    render_assistant_header,
)
from cohrint_agent.repl_input import aggregate_lines


# ── Fixtures ─────────────────────────────────────────────────────────


def _capture(fn, *args, **kwargs) -> str:
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=120, no_color=True)
    with patch("cohrint_agent.renderer.console", console):
        fn(*args, **kwargs)
    return buf.getvalue()


def _make_lines(items):
    it = iter(items)

    def source(_p):
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    return source


# ── 1. Multi-line REPL input ─────────────────────────────────────────


class TestMultilineInput:
    """Regression tests for the fragmented-paste bug that motivated this PR.

    Before: a multi-line paste submitted each line as a separate prompt,
    spawning one backend roundtrip per fragment and producing a garbled
    transcript. The aggregator must now treat the whole paste as one prompt.
    """

    def test_bracketed_paste_single_prompt(self):
        # bracketed-paste arrives as ONE input() call with embedded newlines.
        pasted = "please analyze the following:\nline 2 of my paste\nline 3"
        assert aggregate_lines(_make_lines([pasted])) == pasted

    def test_paragraph_via_triple_quote(self):
        result = aggregate_lines(_make_lines([
            '"""analyze the cohrint agent cli output',
            'Output is not formatted correctly.',
            '1. We should take whole paragraph as input',
            '2. Post enter we should optimize prompt"""',
        ]))
        assert "analyze" in result
        assert "whole paragraph" in result
        assert '"""' not in result

    def test_backslash_continuation_paragraph(self):
        result = aggregate_lines(_make_lines([
            "please fix the bug \\",
            "that appears in the login flow \\",
            "when the session expires",
        ]))
        assert "login flow" in result
        assert result.count("\n") == 2
        assert "\\" not in result

    def test_ctrl_d_on_empty_prompt_quits(self):
        assert aggregate_lines(_make_lines([])) is None

    def test_slash_command_one_line(self):
        # Critical: /quit, /help, /cost etc. must never wait for a blank
        # line — that would hang the REPL on common commands.
        assert aggregate_lines(_make_lines(["/quit"])) == "/quit"
        assert aggregate_lines(_make_lines(["/help"])) == "/help"


# ── 2. Pre-send optimization preview ─────────────────────────────────


class TestPreSendPreview:
    def test_real_verbose_prompt_shows_savings(self):
        # Same prompt style as the transcript in the PR description.
        verbose = (
            "I would appreciate it if you could, for all intents and "
            "purposes, recommend a specific npm package that can validate "
            "LLM outputs in real time, due to the fact that hallucinations "
            "are basically actually a significant problem."
        )
        opt = optimize_prompt(verbose)
        assert opt.saved_tokens > 0, "verbose prompt must optimize"
        out = _capture(render_optimization_preview, opt, "claude-sonnet-4-6")
        # Shows before/after token counts, percent, and dollar savings
        assert str(opt.original_tokens) in out
        assert str(opt.optimized_tokens) in out
        assert "%" in out
        assert "$" in out

    def test_clean_prompt_emits_no_preview(self):
        opt = optimize_prompt("fix bug")  # already minimal
        out = _capture(render_optimization_preview, opt, "claude-sonnet-4-6")
        assert out.strip() == "", f"expected quiet preview, got: {out!r}"

    def test_cost_saved_matches_optimizer_helper(self):
        # The preview's $ figure must be what estimated_cost_saved returns
        # — a mismatch would make the post-response analysis block disagree
        # with the pre-send banner.
        opt = OptimizationResult(
            original="x", optimized="y",
            original_tokens=500, optimized_tokens=200,
            saved_tokens=300, saved_percent=60, changes=["removed filler phrases"],
        )
        out = _capture(render_optimization_preview, opt, "claude-sonnet-4-6")
        expected_cost = estimated_cost_saved(opt, "claude-sonnet-4-6")
        assert f"${expected_cost:.4f}" in out


# ── 3. Assistant stream stage marker ─────────────────────────────────


class TestAssistantHeader:
    def test_claude_label_rendered(self):
        out = _capture(render_assistant_header, "claude")
        assert "Claude" in out

    def test_header_visually_distinct(self):
        # Must contain a divider-style character so it stands out from
        # free-form assistant text — that's the whole point of the marker.
        out = _capture(render_assistant_header, "claude")
        assert "──" in out or "---" in out or "==" in out or "──" in out


# ── 4. Cohrint analysis block ────────────────────────────────────────


class TestCohrintAnalysisBlock:
    BASE = dict(
        optimization=None,
        model="claude-sonnet-4-6",
        guardrail_hedge_detected=False,
        guardrail_active=[],
        anomaly_line=None,
        recommendation=None,
        turn_input_tokens=100,
        turn_output_tokens=50,
        turn_cost_usd=0.001,
        session_cost_usd=0.005,
    )

    def _call(self, **overrides):
        args = {**self.BASE, **overrides}
        return _capture(render_cohrint_analysis, **args)

    def test_block_has_header_separator(self):
        out = self._call()
        assert "Cohrint" in out or "cohrint" in out

    def test_token_and_cost_footer_always_present(self):
        out = self._call(turn_input_tokens=800, turn_output_tokens=200,
                         turn_cost_usd=0.042, session_cost_usd=0.100)
        assert "1,000" in out  # total
        assert "0.0420" in out
        assert "0.1000" in out

    def test_all_signals_combined(self):
        # Simulates a turn where every cohrint signal fires at once.
        opt = OptimizationResult(
            original="x", optimized="y",
            original_tokens=500, optimized_tokens=200,
            saved_tokens=300, saved_percent=60, changes=[],
        )
        out = self._call(
            optimization=opt,
            guardrail_active=["hallucination"],
            guardrail_hedge_detected=True,
            anomaly_line="$0.05 this turn vs $0.01 avg (5.0x)",
            recommendation="Use ! prefix for shell commands",
        )
        assert "Tokens saved" in out
        assert "Cost saved" in out
        assert "declined to fabricate" in out.lower() or "verify independently" in out.lower()
        assert "Anomaly" in out
        assert "5.0x" in out
        assert "Recommendation" in out

    def test_quiet_turn_still_shows_footer(self):
        # No optimization, no guardrail, no anomaly, no recommendation:
        # user should still see the ↳ tokens/cost line.
        out = self._call()
        assert "tokens" in out.lower()
        assert "$" in out


# ── 5. Cost-saved computation integration ────────────────────────────


class TestCostSavedIntegration:
    """Confirms optimizer→renderer→model integration stays consistent."""

    @pytest.mark.parametrize("model,expected_rate", [
        ("claude-sonnet-4-6", 3.00),
        ("claude-opus-4-6", 15.00),
        ("claude-haiku-4-5", 0.80),
        ("gpt-4o", 2.50),
        ("gpt-4o-mini", 0.15),
    ])
    def test_cost_saved_uses_model_input_rate(self, model, expected_rate):
        # 10000 tokens saved → model_rate * 0.01 dollars
        result = OptimizationResult(
            original="x", optimized="y",
            original_tokens=20000, optimized_tokens=10000,
            saved_tokens=10000, saved_percent=50, changes=[],
        )
        expected = 10000 * expected_rate / 1_000_000
        assert estimated_cost_saved(result, model) == pytest.approx(expected)

    def test_zero_savings_zero_cost(self):
        result = OptimizationResult(
            original="x", optimized="x",
            original_tokens=10, optimized_tokens=10,
            saved_tokens=0, saved_percent=0, changes=[],
        )
        assert estimated_cost_saved(result, "claude-sonnet-4-6") == 0.0
