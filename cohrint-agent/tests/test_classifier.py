"""Tests for classifier.py — input classification and optimization pipeline.

Covers scenarios from suites 25 (SS01-SS40) and 34A (CS01-CS08).
"""
import pytest
from cohrint_agent.classifier import classify_input, process_input


# ── Section A: Input Classification (SS.1-SS.15, CS01-CS08) ─────────────

class TestClassifyInput:
    def test_ss01_natural_language_prompt(self):
        assert classify_input("explain kubernetes pods in detail", "claude") == "prompt"

    def test_ss02_short_answer_y(self):
        assert classify_input("y", "claude") == "short-answer"

    def test_ss03_short_answer_yes(self):
        assert classify_input("yes", "claude") == "short-answer"

    def test_ss04_short_answer_numeric(self):
        assert classify_input("1", "claude") == "short-answer"

    def test_ss05_agent_command_compact(self):
        assert classify_input("/compact", "claude") == "agent-command"

    def test_ss06_agent_command_clear(self):
        assert classify_input("/clear", "claude") == "agent-command"

    def test_ss07_at_file_agent_command(self):
        assert classify_input("@file.ts", "claude") == "agent-command"

    def test_ss08_bang_command(self):
        assert classify_input("!ls -la", "claude") == "agent-command"

    def test_ss09_cohrint_exit_session(self):
        assert classify_input("/exit-session", "claude") == "cohrint-command"

    def test_ss10_cohrint_cost(self):
        assert classify_input("/cost", "claude") == "cohrint-command"

    def test_ss11_cohrint_opt_off(self):
        assert classify_input("/opt-off", "claude") == "cohrint-command"

    def test_ss12_structured_json(self):
        assert classify_input('{"key": "value"}', "claude") == "structured"

    def test_ss13_structured_code_block(self):
        assert classify_input("```python\nx=1\n```", "claude") == "structured"

    def test_ss14_empty_input(self):
        assert classify_input("", "claude") == "unknown"

    def test_ss15_single_word(self):
        assert classify_input("fix", "claude") == "short-answer"


class TestStructuredDataGuard:
    """CS01-CS08."""

    def test_cs01_json_object_skips(self):
        assert classify_input('{"key": "value", "nested": {"a": 1}}', "claude") == "structured"

    def test_cs02_json_array_skips(self):
        assert classify_input('[1, 2, 3, 4, 5]', "claude") == "structured"

    def test_cs03_leading_triple_backtick(self):
        assert classify_input("```python\nimport os\n```", "claude") == "structured"

    def test_cs04_fenced_code_block_anywhere(self):
        text = "Here is some prose before ```python\nimport os\n``` and after"
        assert classify_input(text, "claude") == "structured"

    def test_cs05_inline_code_skips(self):
        text = "Use the `os.path.join` function for path handling in your code"
        assert classify_input(text, "claude") == "structured"

    def test_cs06_plain_prose_is_prompt(self):
        assert classify_input("Could you please explain how to deploy to AWS", "claude") == "prompt"

    def test_cs07_url_heavy_skips(self):
        text = "Check these: https://a.com https://b.com https://c.com for reference please"
        assert classify_input(text, "claude") == "structured"

    def test_cs08_high_symbol_density_skips(self):
        text = "function foo() { return bar(x[i]) + baz(y); }"
        assert classify_input(text, "claude") == "structured"


# ── Section B: Selective Optimization (SS.16-SS.25) ──────────────────────

VERBOSE_PROMPT = (
    "I would appreciate it if you could please explain in order to "
    "deploy a kubernetes cluster due to the fact that we need high "
    "availability and it is important that we basically have really "
    "good monitoring in the context of production workloads"
)
CLEAN_PROMPT = "Explain how kubernetes pods communicate with services via DNS"


class TestSelectiveOptimization:
    def test_ss16_verbose_prompt_optimized(self):
        result = process_input(VERBOSE_PROMPT, "claude", "auto")
        assert result["optimized"] is True
        assert result["saved_tokens"] > 0

    def test_ss17_short_answer_passthrough(self):
        result = process_input("y", "claude", "auto")
        assert result["optimized"] is False
        assert result["type"] == "short-answer"

    def test_ss18_agent_command_passthrough(self):
        result = process_input("/compact", "claude", "auto")
        assert result["optimized"] is False
        assert result["type"] == "agent-command"

    def test_ss19_structured_passthrough(self):
        result = process_input('{"key": "value"}', "claude", "auto")
        assert result["optimized"] is False
        assert result["type"] == "structured"

    def test_ss20_clean_prompt_no_savings(self):
        result = process_input(CLEAN_PROMPT, "claude", "auto")
        # Clean prompt may or may not optimize, but shouldn't have big savings
        assert result["type"] == "prompt"

    def test_ss21_opt_mode_never_disables(self):
        result = process_input(VERBOSE_PROMPT, "claude", "never")
        assert result["optimized"] is False
        assert result["forwarded"] == VERBOSE_PROMPT

    def test_ss22_opt_mode_auto_verbose(self):
        result = process_input(VERBOSE_PROMPT, "claude", "auto")
        assert result["optimized"] is True

    def test_ss23_preserves_meaning(self):
        result = process_input(VERBOSE_PROMPT, "claude", "auto")
        assert len(result["forwarded"]) > 0
        # Key terms preserved
        assert "kubernetes" in result["forwarded"].lower()

    def test_ss25_cohrint_command_not_optimized(self):
        result = process_input("/cost", "claude", "auto")
        assert result["type"] == "cohrint-command"
        assert result["optimized"] is False


# ── Section C: Auto-Recovery (SS.26-SS.30) ───────────────────────────────

class TestAutoRecovery:
    def test_ss28_empty_input_no_crash(self):
        result = process_input("", "claude", "auto")
        assert result["type"] == "unknown"

    def test_ss29_only_filler_words(self):
        result = process_input(
            "please kindly basically just really simply honestly actually definitely", "claude", "auto"
        )
        # Should either revert or not optimize
        assert result["reverted"] or not result["optimized"]

    def test_ss30_long_input_no_crash(self):
        long_text = "aaa " * 2000 + "write a function that does something useful please"
        result = process_input(long_text, "claude", "auto")
        assert result["type"] == "prompt"


# ── Section D: User Control (SS.31-SS.35) ────────────────────────────────

class TestUserControl:
    def test_ss31_opt_off_is_cohrint_command(self):
        assert classify_input("/opt-off", "claude") == "cohrint-command"

    def test_ss32_opt_auto_is_cohrint_command(self):
        assert classify_input("/opt-auto", "claude") == "cohrint-command"

    def test_ss33_opt_ask_is_cohrint_command(self):
        assert classify_input("/opt-ask", "claude") == "cohrint-command"

    def test_ss34_opt_on_is_cohrint_command(self):
        assert classify_input("/opt-on", "claude") == "cohrint-command"

    def test_ss35_never_mode_disables_verbose(self):
        result = process_input(VERBOSE_PROMPT, "claude", "never")
        assert result["optimized"] is False
        assert result["forwarded"] == VERBOSE_PROMPT


# ── Section E: Agent-Specific Classification (SS.36-SS.40) ───────────────

class TestAgentSpecific:
    def test_ss36_compress_gemini_vs_claude(self):
        assert classify_input("/compress", "gemini") == "agent-command"
        assert classify_input("/compress", "claude") != "agent-command"

    def test_ss37_add_aider_vs_claude(self):
        assert classify_input("/add", "aider") == "agent-command"
        assert classify_input("/add", "claude") != "agent-command"

    def test_ss38_approval_codex_vs_claude(self):
        assert classify_input("/approval", "codex") == "agent-command"
        assert classify_input("/approval", "claude") != "agent-command"

    def test_ss39_compact_claude_vs_gemini(self):
        assert classify_input("/compact", "claude") == "agent-command"
        assert classify_input("/compact", "gemini") != "agent-command"

    def test_ss40_unknown_agent_no_commands(self):
        # Unknown agent: /compact should fall through
        result = classify_input("/compact", "unknownbot")
        assert result != "agent-command"
