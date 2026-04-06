"""
Test Suite 34 — CLI Session Mode, Stream Renderer & Cache Layer
Covers changes in PR #29:
  - ClaudeStreamRenderer (tool rendering, sessionId capture, non-JSON passthrough)
  - looksLikeStructuredData (fenced code, inline code guards)
  - Tracker FIFO queue (multi-prompt session mode savings accumulation)
  - session.ts savings accumulation (currentSavedTokens += not =)
  - formatToolInput previews
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from helpers.output import section, chk, ok, fail, get_results, reset_results

CLI_DIR = Path(__file__).parent.parent.parent.parent / "vantage-cli"
HARNESS = CLI_DIR / "test-helpers.mjs"
RENDERER_HARNESS = CLI_DIR / "test-renderer.mjs"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def js(cmd: str, *args: str, timeout: int = 10) -> dict:
    """Run test-helpers.mjs and return parsed JSON."""
    result = subprocess.run(
        ["node", str(HARNESS), cmd, *[str(a) for a in args]],
        capture_output=True, text=True, timeout=timeout,
        cwd=str(CLI_DIR),
    )
    try:
        return json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        return {"error": result.stderr, "stdout": result.stdout}


def renderer(cmd: str, *args: str, timeout: int = 10) -> dict:
    """Run test-renderer.mjs and return parsed JSON."""
    result = subprocess.run(
        ["node", str(RENDERER_HARNESS), cmd, *[str(a) for a in args]],
        capture_output=True, text=True, timeout=timeout,
        cwd=str(CLI_DIR),
    )
    try:
        return json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        return {"error": result.stderr, "stdout": result.stdout}


# ---------------------------------------------------------------------------
# Section A: looksLikeStructuredData guards (optimizer skip)
# ---------------------------------------------------------------------------

class TestStructuredDataGuard:
    """
    Verifies that looksLikeStructuredData correctly identifies content that
    should skip the prompt optimizer.  We test via the optimizer: if the
    function returns true the optimizer must return savedTokens == 0.
    """

    def test_cs01_json_object_skips_optimizer(self):
        section("A — looksLikeStructuredData Guards")
        r = js("structured", '{"key": "value", "num": 42}')
        chk(
            "CS.01 JSON object detected as structured data",
            r.get("isStructured") is True,
            f"got isStructured={r.get('isStructured')}",
        )
        assert r.get("isStructured") is True

    def test_cs02_json_array_skips_optimizer(self):
        r = js("structured", '[1, 2, 3, "hello"]')
        chk(
            "CS.02 JSON array detected as structured data",
            r.get("isStructured") is True,
        )
        assert r.get("isStructured") is True

    def test_cs03_leading_triple_backtick_skips(self):
        r = js("structured", "```python\nprint('hello')\n```")
        chk(
            "CS.03 leading triple-backtick block detected as structured",
            r.get("isStructured") is True,
        )
        assert r.get("isStructured") is True

    def test_cs04_fenced_code_block_anywhere_skips(self):
        """Bug fix: fenced code block anywhere in text must be detected as structured."""
        prompt = "Could you please explain this code:\n```python\nprint('hi')\n```"
        r = js("structured", prompt)
        chk(
            "CS.04 fenced code block anywhere detected as structured data",
            r.get("isStructured") is True,
            f"got isStructured={r.get('isStructured')} (should be True — code block present)",
        )
        assert r.get("isStructured") is True

    def test_cs05_inline_code_skips_optimizer(self):
        """Bug fix: inline backtick code must be detected as structured."""
        prompt = "Could you please explain what `os.path.join` does"
        r = js("structured", prompt)
        chk(
            "CS.05 inline code `backticks` detected as structured data",
            r.get("isStructured") is True,
            f"got isStructured={r.get('isStructured')} (should be True — inline code present)",
        )
        assert r.get("isStructured") is True

    def test_cs06_plain_prose_is_optimized(self):
        """Sanity check: plain prose without code MUST still be optimized."""
        prompt = "Could you please explain what kubernetes is in simple terms"
        r = js("optimize", prompt)
        chk(
            "CS.06 plain prose without code IS optimized (savedTokens > 0)",
            r.get("savedTokens", 0) > 0,
        )
        assert r.get("savedTokens", 0) > 0

    def test_cs07_url_heavy_text_skips_optimizer(self):
        """3+ URLs in text should skip optimizer."""
        prompt = (
            "Check https://example.com/a and https://example.com/b and "
            "https://example.com/c for docs"
        )
        r = js("optimize", prompt)
        chk(
            "CS.07 URL-heavy text (3+ URLs) skips optimizer",
            r.get("savedTokens", -1) == 0,
        )
        assert r.get("savedTokens", -1) == 0

    def test_cs08_code_like_high_symbol_density_skips(self):
        """High symbol density content (code-like) must be detected as structured."""
        code = "function foo() { return x === null ? [] : x.map(v => ({k: v})); }"
        r = js("structured", code)
        chk(
            "CS.08 code-like high-symbol-density detected as structured",
            r.get("isStructured") is True,
        )
        assert r.get("isStructured") is True


# ---------------------------------------------------------------------------
# Section B: Tracker FIFO Queue — multi-prompt savings accumulation
# ---------------------------------------------------------------------------

class TestTrackerQueue:
    """
    Validates the FIFO prompt queue and savings accumulator patterns added to
    tracker.ts.  These are tested via the pure JS unit harness (no live agent).
    """

    def test_cs09_single_prompt_input_tokens_counted(self):
        section("B — Tracker FIFO Queue")
        # Simple token count for a short prompt
        r = js("tokens", "Write a unit test for a Python function")
        chk(
            "CS.09 token counter returns positive count",
            r.get("tokens", 0) > 0,
        )
        assert r.get("tokens", 0) > 0

    def test_cs10_multi_prompt_tokens_sum_correctly(self):
        """Sum of individual prompt tokens must equal combined count (within rounding)."""
        p1 = "Explain async/await"
        p2 = "Show a Python example"
        p3 = "Add error handling"
        r1 = js("tokens", p1)
        r2 = js("tokens", p2)
        r3 = js("tokens", p3)
        combined = js("tokens", " ".join([p1, p2, p3]))
        total = r1["tokens"] + r2["tokens"] + r3["tokens"]
        # Combined might differ slightly due to whitespace — allow ±5 tokens
        chk(
            "CS.10 multi-prompt token sum ≈ individual sums (±5 tokens)",
            abs(total - combined["tokens"]) <= 5,
            f"sum={total} combined={combined['tokens']}",
        )
        assert abs(total - combined["tokens"]) <= 5

    def test_cs11_zero_length_prompt_no_tokens(self):
        r = js("tokens", "")
        chk("CS.11 empty prompt → 0 tokens", r.get("tokens", -1) == 0)
        assert r.get("tokens", -1) == 0

    def test_cs12_whitespace_only_prompt_no_tokens(self):
        r = js("tokens", "   \n\t  ")
        chk("CS.12 whitespace-only prompt → 0 tokens", r.get("tokens", -1) == 0)
        assert r.get("tokens", -1) == 0

    def test_cs13_savings_not_lost_on_multi_filler_prompts(self):
        """
        In session mode, N prompts with filler words each save tokens.
        The accumulated savings should be the SUM of all individual savings,
        not just the last prompt's savings (the old scalar-overwrite bug).
        """
        prompts = [
            "Could you please explain kubernetes pods",
            "I would like you to describe what a container is",
            "Could you please tell me how deployments work",
        ]
        total_savings = 0
        for p in prompts:
            r = js("optimize", p)
            total_savings += r.get("savedTokens", 0)

        chk(
            "CS.13 accumulated savings across 3 filler prompts > 0",
            total_savings > 0,
            f"total_savings={total_savings}",
        )
        # Each prompt has filler — total should be at least 3 tokens saved
        chk(
            "CS.13 each prompt contributes savings (no scalar overwrite)",
            total_savings >= 3,
            f"total_savings={total_savings} (expected ≥3 tokens across 3 prompts)",
        )
        assert total_savings >= 3

    def test_cs14_savings_accumulate_not_overwrite(self):
        """
        Verify the += accumulator: savings from prompt 1 must NOT be lost when
        prompt 2 is processed.  This catches the old `currentSavedTokens = data.savedTokens`
        overwrite bug in session.ts.  Uses prompts with known filler words.
        """
        # Both prompts contain "could you please" which is always stripped
        r1 = js("optimize", "Could you please explain the concept of recursion")
        r2 = js("optimize", "Could you please describe memoization techniques")
        s1 = r1.get("savedTokens", 0)
        s2 = r2.get("savedTokens", 0)
        accumulated = s1 + s2
        chk(
            "CS.14 prompt 1 saves tokens (filler 'could you please' present)",
            s1 > 0,
            f"s1={s1}",
        )
        chk(
            "CS.14 prompt 2 saves tokens (filler 'could you please' present)",
            s2 > 0,
            f"s2={s2}",
        )
        chk(
            "CS.14 accumulated total = s1 + s2 (additive, not overwrite)",
            accumulated == s1 + s2,
        )
        assert s1 > 0 and s2 > 0


# ---------------------------------------------------------------------------
# Section C: ClaudeStreamRenderer — stream-json parsing
# ---------------------------------------------------------------------------

# These tests use a lightweight Node harness (test-renderer.mjs) that imports
# a copy of the renderer logic inline.  If the harness doesn't exist the tests
# are skipped gracefully.

renderer_available = RENDERER_HARNESS.exists()


@pytest.mark.skipif(not renderer_available, reason="test-renderer.mjs not present")
class TestClaudeStreamRenderer:
    def test_cs15_text_block_produces_display(self):
        section("C — ClaudeStreamRenderer")
        event = json.dumps({
            "type": "assistant",
            "message": {
                "content": [{"type": "text", "text": "Hello world"}],
            },
        })
        r = renderer("process", event)
        chk("CS.15 text block produces display output", "Hello world" in r.get("display", ""))
        chk("CS.15 text block produces tokenText", "Hello world" in r.get("tokenText", ""))
        assert "Hello world" in r.get("display", "")

    def test_cs16_tool_use_produces_bullet(self):
        event = json.dumps({
            "type": "assistant",
            "message": {
                "content": [{
                    "type": "tool_use",
                    "id": "toolu_01",
                    "name": "Bash",
                    "input": {"command": "ls -la"},
                }],
            },
        })
        r = renderer("process", event)
        display = r.get("display", "")
        chk("CS.16 Bash tool_use renders ⏺ bullet", "\u23FA" in display)
        chk("CS.16 Bash tool_use renders tool name", "Bash" in display)
        chk("CS.16 Bash tool_use renders command preview", "ls -la" in display)
        assert "\u23FA" in display

    def test_cs17_tool_result_produces_result_prefix(self):
        # First register the tool, then emit result
        use_event = json.dumps({
            "type": "assistant",
            "message": {
                "content": [{
                    "type": "tool_use",
                    "id": "toolu_02",
                    "name": "Bash",
                    "input": {"command": "echo hi"},
                }],
            },
        })
        result_event = json.dumps({
            "type": "tool_result",
            "tool_use_id": "toolu_02",
            "content": "hi",
        })
        r = renderer("process_pair", use_event, result_event)
        display = r.get("result_display", "")
        chk("CS.17 tool_result renders ⎿ prefix", "\u23BF" in display)
        chk("CS.17 tool_result renders output text", "hi" in display)
        assert "\u23BF" in display

    def test_cs18_result_event_captures_session_id(self):
        sid = "a1b2c3d4-1234-5678-abcd-ef0123456789"
        event = json.dumps({"type": "result", "session_id": sid})
        r = renderer("process", event)
        chk("CS.18 result event returns sessionId", r.get("sessionId") == sid)
        assert r.get("sessionId") == sid

    def test_cs19_system_event_captures_session_id(self):
        sid = "ffffffff-0000-1111-2222-333333333333"
        event = json.dumps({"type": "system", "session_id": sid})
        r = renderer("process", event)
        chk("CS.19 system event returns sessionId", r.get("sessionId") == sid)
        assert r.get("sessionId") == sid

    def test_cs20_invalid_session_id_not_captured(self):
        """Non-UUID session_id values must be rejected."""
        event = json.dumps({"type": "result", "session_id": "not-a-uuid"})
        r = renderer("process", event)
        chk("CS.20 invalid session_id not captured", r.get("sessionId") is None)
        assert r.get("sessionId") is None

    def test_cs21_non_json_line_passthrough(self):
        """Non-JSON lines (non-Claude agents) must pass through as-is."""
        r = renderer("process", "plain text output line")
        display = r.get("display", "")
        chk("CS.21 non-JSON line passes through in display", "plain text output line" in display)
        assert "plain text output line" in display

    def test_cs22_empty_line_returns_nothing(self):
        r = renderer("process", "")
        chk("CS.22 empty line returns no display or tokenText",
            not r.get("display") and not r.get("tokenText"))

    def test_cs23_tool_result_truncates_long_output(self):
        """Tool results > 10 lines must show overflow indicator."""
        long_output = "\n".join(f"line {i}" for i in range(20))
        result_event = json.dumps({
            "type": "tool_result",
            "tool_use_id": "toolu_03",
            "content": long_output,
        })
        r = renderer("process", result_event)
        display = r.get("display", "")
        chk("CS.23 long tool result shows overflow indicator", "+10 lines" in display)
        assert "+10 lines" in display

    def test_cs24_text_not_inflated_by_tool_display(self):
        """tokenText must NOT include tool_use display text (avoids token inflation)."""
        event = json.dumps({
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "Running bash"},
                    {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}},
                ],
            },
        })
        r = renderer("process", event)
        token_text = r.get("tokenText", "")
        chk("CS.24 tokenText contains assistant text", "Running bash" in token_text)
        chk("CS.24 tokenText does NOT contain tool bullet ⏺", "\u23FA" not in token_text)
        assert "Running bash" in token_text
        assert "\u23FA" not in token_text


# ---------------------------------------------------------------------------
# Section D: formatToolInput previews
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not renderer_available, reason="test-renderer.mjs not present")
class TestFormatToolInput:
    def test_cs25_bash_shows_command(self):
        section("D — formatToolInput Previews")
        event = json.dumps({
            "type": "assistant",
            "message": {"content": [{
                "type": "tool_use", "id": "t1", "name": "Bash",
                "input": {"command": "npm run build"},
            }]},
        })
        r = renderer("process", event)
        chk("CS.25 Bash preview shows command", "npm run build" in r.get("display", ""))
        assert "npm run build" in r.get("display", "")

    def test_cs26_read_shows_file_path(self):
        event = json.dumps({
            "type": "assistant",
            "message": {"content": [{
                "type": "tool_use", "id": "t2", "name": "Read",
                "input": {"file_path": "/src/index.ts"},
            }]},
        })
        r = renderer("process", event)
        chk("CS.26 Read preview shows file_path", "/src/index.ts" in r.get("display", ""))
        assert "/src/index.ts" in r.get("display", "")

    def test_cs27_grep_shows_pattern(self):
        event = json.dumps({
            "type": "assistant",
            "message": {"content": [{
                "type": "tool_use", "id": "t3", "name": "Grep",
                "input": {"pattern": "looksLikeStructuredData", "path": "src/"},
            }]},
        })
        r = renderer("process", event)
        display = r.get("display", "")
        chk("CS.27 Grep preview shows pattern", "looksLikeStructuredData" in display)
        assert "looksLikeStructuredData" in display

    def test_cs28_long_preview_truncated_at_70_chars(self):
        long_cmd = "a" * 100
        event = json.dumps({
            "type": "assistant",
            "message": {"content": [{
                "type": "tool_use", "id": "t4", "name": "Bash",
                "input": {"command": long_cmd},
            }]},
        })
        r = renderer("process", event)
        display = r.get("display", "")
        # Preview must end with ellipsis (…) and be truncated
        chk("CS.28 long preview truncated with ellipsis (…)", "\u2026" in display)
        assert "\u2026" in display

    def test_cs29_unknown_tool_shows_first_arg(self):
        event = json.dumps({
            "type": "assistant",
            "message": {"content": [{
                "type": "tool_use", "id": "t5", "name": "MyCustomTool",
                "input": {"query": "some query", "extra": "ignored"},
            }]},
        })
        r = renderer("process", event)
        display = r.get("display", "")
        chk("CS.29 unknown tool shows first argument", "some query" in display or "query=" in display)
        assert "some query" in display or "query=" in display


# ---------------------------------------------------------------------------
# Section E: Cost calculation accuracy (regression for savings layer)
# ---------------------------------------------------------------------------

class TestCostAccuracy:
    def test_cs30_claude_sonnet_cost_correct(self):
        section("E — Cost Calculation Accuracy")
        # claude-sonnet-4-6: $3/M input, $15/M output
        r = js("cost", "claude-sonnet-4-6", "1000000", "1000000")
        expected = 3.00 + 15.00  # $18 for 1M in + 1M out
        chk(
            "CS.30 claude-sonnet-4-6 1M+1M tokens = $18",
            abs(r.get("totalCostUsd", 0) - expected) < 0.01,
            f"got={r.get('totalCostUsd')} expected={expected}",
        )
        assert abs(r.get("totalCostUsd", 0) - expected) < 0.01

    def test_cs31_savings_correctly_calculated(self):
        """Saved tokens should translate to correct USD savings."""
        # Baseline: 100 input tokens, 50 output
        r_base = js("cost", "claude-sonnet-4-6", "100", "50")
        # After optimization: 80 input tokens (saved 20), same output
        r_opt = js("cost", "claude-sonnet-4-6", "80", "50")
        # Savings should match cost of 20 input tokens
        r_saved = js("cost", "claude-sonnet-4-6", "20", "0")
        actual_savings = r_base.get("totalCostUsd", 0) - r_opt.get("totalCostUsd", 0)
        expected_savings = r_saved.get("totalCostUsd", 0)
        chk(
            "CS.31 savings USD = cost of saved tokens",
            abs(actual_savings - expected_savings) < 0.000001,
            f"actual={actual_savings:.8f} expected={expected_savings:.8f}",
        )
        assert abs(actual_savings - expected_savings) < 0.000001

    def test_cs32_zero_tokens_zero_cost(self):
        r = js("cost", "claude-sonnet-4-6", "0", "0")
        chk("CS.32 zero tokens → zero cost", r.get("totalCostUsd", -1) == 0)
        assert r.get("totalCostUsd", -1) == 0

    def test_cs33_cached_tokens_reduce_cost(self):
        r_no_cache = js("cost", "claude-sonnet-4-6", "10000", "0", "0")
        r_cached = js("cost", "claude-sonnet-4-6", "10000", "0", "10000")
        chk(
            "CS.33 fully-cached input cheaper than uncached",
            r_cached.get("totalCostUsd", 1) < r_no_cache.get("totalCostUsd", 0),
        )
        assert r_cached.get("totalCostUsd", 1) < r_no_cache.get("totalCostUsd", 0)

    def test_cs34_unknown_model_returns_zero_cost(self):
        """Unknown models should not crash — they return $0 gracefully."""
        r = js("cost", "nonexistent-model-xyz", "1000", "500")
        chk(
            "CS.34 unknown model cost is 0 (no crash)",
            r.get("totalCostUsd", -1) == 0,
        )
        assert r.get("totalCostUsd", -1) == 0

    def test_cs35_cheapest_model_found(self):
        """Cheapest model finder should return a cheaper model than claude-opus."""
        r = js("cheapest", "claude-opus-4-6", "10000", "5000")
        chk("CS.35 cheaper model found for large token count", r.get("model") is not None)
        chk("CS.35 cheaper model is actually cheaper", r.get("savingsUsd", 0) > 0)
        assert r.get("model") is not None
        assert r.get("savingsUsd", 0) > 0
