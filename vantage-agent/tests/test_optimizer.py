"""Tests for optimizer.py — prompt compression engine."""
import pytest
from vantage_agent.optimizer import (
    compress_prompt,
    count_tokens,
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
