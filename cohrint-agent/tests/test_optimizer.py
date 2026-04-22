"""Tests for optimizer.py — prompt compression engine."""
import pytest
from cohrint_agent.optimizer import (
    compress_prompt,
    count_tokens,
    estimated_cost_saved,
    looks_like_structured_data,
    optimize_prompt,
    OptimizationResult,
    _compress_prose,
    _deduplicate_sentences,
    _split_code_and_prose,
)


class TestCountTokens:
    def test_empty_string(self):
        assert count_tokens("") == 0

    def test_whitespace_only(self):
        assert count_tokens("   ") == 0

    def test_prose_approx_4_chars_per_token(self):
        text = "This is a normal sentence with some words in it."
        tokens = count_tokens(text)
        assert tokens == len(text.strip()) // 4

    def test_code_heavy_approx_3_chars_per_token(self):
        text = "if (x > 0) { return foo(bar[i]); }"
        tokens = count_tokens(text)
        assert tokens == len(text.strip()) // 3

    def test_minimum_one_token(self):
        assert count_tokens("hi") >= 1


class TestSplitCodeAndProse:
    def test_pure_prose(self):
        result = _split_code_and_prose("hello world")
        assert result == [("prose", "hello world")]

    def test_inline_code(self):
        result = _split_code_and_prose("use `foo()` here")
        assert len(result) == 3
        assert result[0] == ("prose", "use ")
        assert result[1] == ("code", "`foo()`")
        assert result[2] == ("prose", " here")

    def test_fenced_code_block(self):
        text = "before\n```python\nx = 1\n```\nafter"
        result = _split_code_and_prose(text)
        assert result[0][0] == "prose"
        assert result[1][0] == "code"
        assert result[2][0] == "prose"


class TestDeduplicateSentences:
    def test_removes_duplicate(self):
        result = _deduplicate_sentences("Hello world. Hello world. Goodbye.")
        assert result == "Hello world. Goodbye."

    def test_no_duplicates(self):
        result = _deduplicate_sentences("First. Second. Third.")
        assert result == "First. Second. Third."


class TestCompressProse:
    def test_removes_filler_phrase(self):
        result = _compress_prose("I'd like you to fix this bug")
        assert "i'd like you to" not in result.lower()
        assert "fix" in result.lower()

    def test_verbose_rewrite(self):
        # "in the near future" is not a filler phrase, only a verbose rewrite
        result = _compress_prose("it will happen in the near future")
        assert "soon" in result.lower()
        assert "in the near future" not in result.lower()

    def test_removes_filler_words(self):
        result = _compress_prose("just basically fix the really broken thing")
        assert "just" not in result.lower()
        assert "basically" not in result.lower()
        assert "really" not in result.lower()

    def test_collapses_whitespace(self):
        result = _compress_prose("fix   the    bug")
        assert "  " not in result


class TestCompressPrompt:
    def test_preserves_code_blocks(self):
        text = "please fix ```python\nx = 1\n``` this code"
        result = compress_prompt(text)
        assert "```python\nx = 1\n```" in result

    def test_compresses_prose_around_code(self):
        text = "I'd like you to fix ```python\nx = 1\n``` due to the fact that it breaks"
        result = compress_prompt(text)
        assert "```python\nx = 1\n```" in result
        assert "i'd like you to" not in result.lower()

    def test_short_input_unchanged(self):
        result = compress_prompt("fix bug")
        assert result == "fix bug"


class TestLooksLikeStructuredData:
    def test_json_object(self):
        assert looks_like_structured_data('{"key": "value"}') is True

    def test_json_array(self):
        assert looks_like_structured_data('[1, 2, 3]') is True

    def test_fenced_code_block_only(self):
        # Entire prompt is a code block — no prose to compress.
        assert looks_like_structured_data("```python\nx=1\n```") is True

    def test_prose_with_embedded_fenced_code_optimizes(self):
        # The _split_code_and_prose helper already preserves code blocks, so
        # a prompt that is mostly prose with an embedded fence should still
        # optimize (previously this was incorrectly skipped entirely).
        text = (
            "I would appreciate it if you could please fix this bug.\n"
            "```python\nx = 1\n```\n"
            "Due to the fact that it crashes on every boot."
        )
        assert looks_like_structured_data(text) is False

    def test_prose_with_inline_code_optimizes(self):
        # A single inline `foo()` reference inside prose must not skip
        # optimization — this was the bug users hit with technical prompts
        # like "confirm `validateStream()` exists in package X".
        text = (
            "I would appreciate it if you could, at this point in time, "
            "confirm that `validateStream()` exists in the package."
        )
        assert looks_like_structured_data(text) is False

    def test_url_heavy(self):
        assert looks_like_structured_data("see https://a.com https://b.com https://c.com") is True

    def test_code_like_symbols(self):
        text = "if (x > 0) { return foo(bar[i]); } else { baz(); }"
        assert looks_like_structured_data(text) is True

    def test_plain_prose(self):
        assert looks_like_structured_data("please fix the login bug") is False

    def test_skips_optimization_for_json(self):
        result = optimize_prompt('{"key": "value", "nested": {"a": 1}}')
        assert result.saved_tokens == 0
        assert result.optimized == result.original


class TestOptimizePrompt:
    def test_returns_optimization_result(self):
        result = optimize_prompt("I'd like you to fix this bug due to the fact that it crashes")
        assert isinstance(result, OptimizationResult)
        assert result.saved_tokens >= 0
        assert result.optimized_tokens <= result.original_tokens

    def test_no_savings_on_clean_input(self):
        result = optimize_prompt("fix bug")
        assert result.saved_tokens == 0
        assert result.optimized == result.original

    def test_savings_on_verbose_input(self):
        result = optimize_prompt(
            "I'd like you to please fix this bug due to the fact that it is really broken"
        )
        assert result.saved_tokens > 0
        assert result.saved_percent > 0


class TestEstimatedCostSaved:
    """cost_saved turns token savings into the $ a user would have spent on those
    tokens as *input* to the model. Output pricing is irrelevant — we're
    measuring what the user *didn't* send."""

    def test_zero_saved_tokens_returns_zero(self):
        result = OptimizationResult(
            original="fix bug", optimized="fix bug",
            original_tokens=2, optimized_tokens=2,
            saved_tokens=0, saved_percent=0, changes=[],
        )
        assert estimated_cost_saved(result, "claude-sonnet-4-6") == 0.0

    def test_sonnet_4_6_saves_at_input_rate(self):
        # Sonnet 4.6 input price is $3.00 per million tokens.
        # 1000 saved tokens = $0.003.
        result = OptimizationResult(
            original="x", optimized="x",
            original_tokens=2000, optimized_tokens=1000,
            saved_tokens=1000, saved_percent=50, changes=[],
        )
        assert estimated_cost_saved(result, "claude-sonnet-4-6") == pytest.approx(0.003)

    def test_opus_4_6_saves_at_higher_rate(self):
        # Opus 4.6 is $15/M — 1000 saved tokens = $0.015.
        result = OptimizationResult(
            original="x", optimized="x",
            original_tokens=2000, optimized_tokens=1000,
            saved_tokens=1000, saved_percent=50, changes=[],
        )
        assert estimated_cost_saved(result, "claude-opus-4-6") == pytest.approx(0.015)

    def test_unknown_model_falls_back_to_default(self):
        # Default table uses claude-sonnet-4-6 rate ($3/M).
        result = OptimizationResult(
            original="x", optimized="x",
            original_tokens=2000, optimized_tokens=1000,
            saved_tokens=1000, saved_percent=50, changes=[],
        )
        assert estimated_cost_saved(result, "some-new-model-v99") == pytest.approx(0.003)

    def test_none_model_falls_back_to_default(self):
        result = OptimizationResult(
            original="x", optimized="x",
            original_tokens=2000, optimized_tokens=1000,
            saved_tokens=1000, saved_percent=50, changes=[],
        )
        assert estimated_cost_saved(result, None) == pytest.approx(0.003)

    def test_negative_saved_tokens_clamps_to_zero(self):
        # Defensive: if a buggy caller passes negative savings (e.g. due to a
        # miscount), we return 0.0 rather than a negative cost that would
        # poison a dashboard or session accumulator.
        result = OptimizationResult(
            original="x", optimized="x",
            original_tokens=100, optimized_tokens=200,
            saved_tokens=-100, saved_percent=0, changes=[],
        )
        assert estimated_cost_saved(result, "claude-sonnet-4-6") == 0.0
