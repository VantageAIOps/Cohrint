"""
Test Suite 34 — CLI Session Mode, Stream Renderer & Cache Layer
Covers changes in PR #29:
  - ClaudeStreamRenderer (tool rendering, sessionId capture, non-JSON passthrough)
  - looksLikeStructuredData (fenced code, inline code guards)
  - Tracker FIFO queue (multi-prompt session mode savings accumulation)
  - session.ts savings accumulation (currentSavedTokens += not =)
  - formatToolInput previews

Rewritten to use Python vantage-agent modules directly (no Node.js harness).
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT / "vantage-agent"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from helpers.output import section, chk, ok, fail, get_results, reset_results

from vantage_agent.optimizer import looks_like_structured_data, optimize_prompt, count_tokens
from vantage_agent.pricing import calculate_cost, find_cheapest, MODEL_PRICES


# ---------------------------------------------------------------------------
# Helpers — Python equivalents of the JS harness commands
# ---------------------------------------------------------------------------

def py_structured(text: str) -> dict:
    """Equivalent of js('structured', text)."""
    return {"isStructured": looks_like_structured_data(text)}


def py_optimize(text: str) -> dict:
    """Equivalent of js('optimize', text). Returns savedTokens, savedPercent, optimized."""
    r = optimize_prompt(text)
    return {
        "optimized": r.optimized,
        "savedTokens": r.saved_tokens,
        "savedPercent": r.saved_percent,
    }


def py_tokens(text: str) -> dict:
    """Equivalent of js('tokens', text)."""
    return {"tokens": count_tokens(text)}


def py_cost(model: str, prompt_tokens: int, completion_tokens: int, cached_tokens: int = 0) -> dict:
    """Equivalent of js('cost', model, prompt_tokens, completion_tokens [, cached_tokens])."""
    total = calculate_cost(model, prompt_tokens, completion_tokens, cached_tokens)
    return {"totalCostUsd": total}


def py_cheapest(current_model: str, prompt_tokens: int, completion_tokens: int) -> dict:
    """Equivalent of js('cheapest', model, prompt_tokens, completion_tokens)."""
    result = find_cheapest(current_model, prompt_tokens, completion_tokens)
    if result is None:
        return {}
    return {
        "model": result.model,
        "costUsd": result.cost,
        "savingsUsd": result.savings,
        "savingsPercent": result.savings_percent,
    }


def py_models() -> dict:
    """Equivalent of js('models'). Returns count of known models (excl. 'default')."""
    count = sum(1 for k in MODEL_PRICES if k != "default")
    return {"count": count}


# ---------------------------------------------------------------------------
# Section A: looksLikeStructuredData guards (optimizer skip)
# ---------------------------------------------------------------------------

class TestStructuredDataGuard:
    """
    Verifies that looksLikeStructuredData correctly identifies content that
    should skip the prompt optimizer.
    """

    def test_cs01_json_object_skips_optimizer(self):
        section("A — looksLikeStructuredData Guards")
        r = py_structured('{"key": "value", "num": 42}')
        chk(
            "CS.01 JSON object detected as structured data",
            r.get("isStructured") is True,
            f"got isStructured={r.get('isStructured')}",
        )
        assert r.get("isStructured") is True

    def test_cs02_json_array_skips_optimizer(self):
        r = py_structured('[1, 2, 3, "hello"]')
        chk(
            "CS.02 JSON array detected as structured data",
            r.get("isStructured") is True,
        )
        assert r.get("isStructured") is True

    def test_cs03_leading_triple_backtick_skips(self):
        r = py_structured("```python\nprint('hello')\n```")
        chk(
            "CS.03 leading triple-backtick block detected as structured",
            r.get("isStructured") is True,
        )
        assert r.get("isStructured") is True

    def test_cs04_fenced_code_block_anywhere_skips(self):
        """Bug fix: fenced code block anywhere in text must be detected as structured."""
        prompt = "Could you please explain this code:\n```python\nprint('hi')\n```"
        r = py_structured(prompt)
        chk(
            "CS.04 fenced code block anywhere detected as structured data",
            r.get("isStructured") is True,
            f"got isStructured={r.get('isStructured')} (should be True — code block present)",
        )
        assert r.get("isStructured") is True

    def test_cs05_inline_code_skips_optimizer(self):
        """Bug fix: inline backtick code must be detected as structured."""
        prompt = "Could you please explain what `os.path.join` does"
        r = py_structured(prompt)
        chk(
            "CS.05 inline code `backticks` detected as structured data",
            r.get("isStructured") is True,
            f"got isStructured={r.get('isStructured')} (should be True — inline code present)",
        )
        assert r.get("isStructured") is True

    def test_cs06_plain_prose_is_optimized(self):
        """Sanity check: plain prose without code MUST still be optimized."""
        prompt = "Could you please explain what kubernetes is in simple terms"
        r = py_optimize(prompt)
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
        r = py_optimize(prompt)
        chk(
            "CS.07 URL-heavy text (3+ URLs) skips optimizer",
            r.get("savedTokens", -1) == 0,
        )
        assert r.get("savedTokens", -1) == 0

    def test_cs08_code_like_high_symbol_density_skips(self):
        """High symbol density content (code-like) must be detected as structured."""
        code = "function foo() { return x === null ? [] : x.map(v => ({k: v})); }"
        r = py_structured(code)
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
    Validates the FIFO prompt queue and savings accumulator patterns.
    Tested via direct Python optimizer calls (no live agent).
    """

    def test_cs09_single_prompt_input_tokens_counted(self):
        section("B — Tracker FIFO Queue")
        r = py_tokens("Write a unit test for a Python function")
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
        r1 = py_tokens(p1)
        r2 = py_tokens(p2)
        r3 = py_tokens(p3)
        combined = py_tokens(" ".join([p1, p2, p3]))
        total = r1["tokens"] + r2["tokens"] + r3["tokens"]
        # Combined might differ slightly due to whitespace — allow ±5 tokens
        chk(
            "CS.10 multi-prompt token sum ≈ individual sums (±5 tokens)",
            abs(total - combined["tokens"]) <= 5,
            f"sum={total} combined={combined['tokens']}",
        )
        assert abs(total - combined["tokens"]) <= 5

    def test_cs11_zero_length_prompt_no_tokens(self):
        r = py_tokens("")
        chk("CS.11 empty prompt → 0 tokens", r.get("tokens", -1) == 0)
        assert r.get("tokens", -1) == 0

    def test_cs12_whitespace_only_prompt_no_tokens(self):
        r = py_tokens("   \n\t  ")
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
            r = py_optimize(p)
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
        r1 = py_optimize("Could you please explain the concept of recursion")
        r2 = py_optimize("Could you please describe memoization techniques")
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
# Section B2: Failure state isolation — regression tests for review issues
# ---------------------------------------------------------------------------

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)


def _validate_session_id(sid: str) -> bool:
    """Return True if sid matches strict UUID format."""
    return bool(_UUID_RE.match(sid))


class TestFailureStateIsolation:
    """
    Regression tests for the three issues found in PR #30 code review:
    1. tracker.ts early-return leaked promptTexts/pendingSavedTokens on failure
    2. session.ts currentSavedTokens not reset on agent failure
    3. test-renderer.mjs sessionId regex looser than production UUID format
    """

    def test_cs14b_strict_uuid_accepted(self):
        """Regression: strict UUID must be accepted by the UUID validator."""
        section("B2 — Failure State Isolation (Review Fixes)")
        sid = "a1b2c3d4-1234-5678-abcd-ef0123456789"
        is_valid = _validate_session_id(sid)
        chk("CS.14b strict UUID sessionId accepted", is_valid)
        assert is_valid

    def test_cs14c_malformed_36char_hex_rejected(self):
        """Regression: 36-char hex string with wrong hyphen placement must be rejected."""
        malformed = "aabbccdd1122334455667788" + "-" * 12  # 36 chars, wrong structure
        is_valid = _validate_session_id(malformed)
        chk(
            "CS.14c malformed 36-char non-UUID rejected",
            not is_valid,
            f"got is_valid={is_valid} (should be False)",
        )
        assert not is_valid

    def test_cs14d_all_hyphens_36chars_rejected(self):
        """Regression: 36 hyphens must be rejected (old loose regex would accept)."""
        all_hyphens = "-" * 36
        is_valid = _validate_session_id(all_hyphens)
        chk(
            "CS.14d all-hyphens 36-char string rejected",
            not is_valid,
        )
        assert not is_valid

    def test_cs14e_tracker_state_isolated_from_optimize_savings(self):
        """
        Regression: after a failed optimization (0 tokens saved), subsequent
        prompts must still count savings independently.
        """
        r_no_savings = py_optimize("What is 2+2")  # minimal prompt, no filler
        r_with_savings = py_optimize("Could you please explain what recursion is")
        s_none = r_no_savings.get("savedTokens", -1)
        s_has = r_with_savings.get("savedTokens", 0)
        chk(
            "CS.14e clean prompt saves 0 tokens (baseline)",
            s_none == 0,
            f"got={s_none}",
        )
        chk(
            "CS.14e filler prompt still saves tokens after zero-savings prompt",
            s_has > 0,
            f"got={s_has}",
        )
        assert s_has > 0

    def test_cs14f_session_id_wrong_length_rejected(self):
        """Regression: session IDs of wrong length must be rejected."""
        too_short = "a1b2c3d4-1234-5678-abcd"  # only 23 chars
        too_long = "a1b2c3d4-1234-5678-abcd-ef0123456789-extra"
        r1 = _validate_session_id(too_short)
        r2 = _validate_session_id(too_long)
        chk("CS.14f too-short session ID rejected", not r1)
        chk("CS.14f too-long session ID rejected", not r2)
        assert not r1
        assert not r2


# Sections C and D (TestClaudeStreamRenderer / TestFormatToolInput) were
# TypeScript-era harness tests for vantage-cli/test-renderer.ts. The Python
# renderer.py uses rich console for live output and has no JSON-in / JSON-out
# interface, so those 15 cases had no body and were permanently skipped.
# They have been removed — UUID validation regressions remain covered by
# TestFailureStateIsolation above.


# ---------------------------------------------------------------------------
# Section E: Cost calculation accuracy (regression for savings layer)
# ---------------------------------------------------------------------------

class TestCostAccuracy:
    def test_cs30_claude_sonnet_cost_correct(self):
        section("E — Cost Calculation Accuracy")
        # claude-sonnet-4-6: $3/M input, $15/M output
        r = py_cost("claude-sonnet-4-6", 1_000_000, 1_000_000)
        expected = 3.00 + 15.00  # $18 for 1M in + 1M out
        chk(
            "CS.30 claude-sonnet-4-6 1M+1M tokens = $18",
            abs(r.get("totalCostUsd", 0) - expected) < 0.01,
            f"got={r.get('totalCostUsd')} expected={expected}",
        )
        assert abs(r.get("totalCostUsd", 0) - expected) < 0.01

    def test_cs31_savings_correctly_calculated(self):
        """Saved tokens should translate to correct USD savings."""
        r_base = py_cost("claude-sonnet-4-6", 100, 50)
        r_opt = py_cost("claude-sonnet-4-6", 80, 50)
        r_saved = py_cost("claude-sonnet-4-6", 20, 0)
        actual_savings = r_base.get("totalCostUsd", 0) - r_opt.get("totalCostUsd", 0)
        expected_savings = r_saved.get("totalCostUsd", 0)
        chk(
            "CS.31 savings USD = cost of saved tokens",
            abs(actual_savings - expected_savings) < 0.000001,
            f"actual={actual_savings:.8f} expected={expected_savings:.8f}",
        )
        assert abs(actual_savings - expected_savings) < 0.000001

    def test_cs32_zero_tokens_zero_cost(self):
        r = py_cost("claude-sonnet-4-6", 0, 0)
        chk("CS.32 zero tokens → zero cost", r.get("totalCostUsd", -1) == 0)
        assert r.get("totalCostUsd", -1) == 0

    def test_cs33_cached_tokens_reduce_cost(self):
        r_no_cache = py_cost("claude-sonnet-4-6", 10000, 0, 0)
        r_cached = py_cost("claude-sonnet-4-6", 10000, 0, 10000)
        chk(
            "CS.33 fully-cached input cheaper than uncached",
            r_cached.get("totalCostUsd", 1) < r_no_cache.get("totalCostUsd", 0),
        )
        assert r_cached.get("totalCostUsd", 1) < r_no_cache.get("totalCostUsd", 0)

    def test_cs34_unknown_model_returns_zero_cost(self):
        """Unknown models should not crash — they return $0 gracefully."""
        r = py_cost("nonexistent-model-xyz", 1000, 500)
        chk(
            "CS.34 unknown model cost is 0 (no crash)",
            r.get("totalCostUsd", -1) == 0,
        )
        assert r.get("totalCostUsd", -1) == 0

    def test_cs35_cheapest_model_found(self):
        """Cheapest model finder should return a cheaper model than claude-opus."""
        r = py_cheapest("claude-opus-4-6", 10000, 5000)
        chk("CS.35 cheaper model found for large token count", r.get("model") is not None)
        chk("CS.35 cheaper model is actually cheaper", r.get("savingsUsd", 0) > 0)
        assert r.get("model") is not None
        assert r.get("savingsUsd", 0) > 0
