"""Tests for pricing.py — multi-model cost calculation and cheapest finder.

Covers test scenarios from suites 21C, 26B, 30E, 34E, 31-Flow5.
"""
import pytest
from vantage_agent.pricing import calculate_cost, find_cheapest, MODEL_PRICES


class TestCalculateCost:
    """CL19-CL25, CI06-CI15, CS30-CS34, FN28-FN33."""

    def test_claude_sonnet_cost_positive(self):
        cost = calculate_cost("claude-sonnet-4-6", 1000, 500)
        assert cost > 0

    def test_gpt4o_cost_positive(self):
        cost = calculate_cost("gpt-4o", 1000, 500)
        assert cost > 0

    def test_gemini_flash_cost_positive(self):
        cost = calculate_cost("gemini-2.0-flash", 1000, 500)
        assert cost > 0

    def test_unknown_model_uses_default_pricing(self):
        """Unknown models now fall back to claude-sonnet-4-6 pricing with a warning."""
        import sys
        import io
        stderr_capture = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = stderr_capture
        try:
            cost = calculate_cost("totally-unknown-model-xyz", 1000, 500)
        finally:
            sys.stderr = old_stderr
        # Should use "default" pricing (claude-sonnet-4-6 rates) — not zero
        assert cost > 0
        assert "unknown model" in stderr_capture.getvalue()

    def test_zero_tokens_zero_cost(self):
        assert calculate_cost("gpt-4o", 0, 0) == 0

    def test_cache_reduces_cost(self):
        no_cache = calculate_cost("claude-sonnet-4-6", 10000, 5000, cached_tokens=0)
        with_cache = calculate_cost("claude-sonnet-4-6", 10000, 5000, cached_tokens=5000)
        assert with_cache < no_cache

    def test_cost_proportional_to_tokens(self):
        small = calculate_cost("gpt-4o", 100, 50)
        large = calculate_cost("gpt-4o", 10000, 5000)
        ratio = large / small
        assert 90 < ratio < 110  # ~100x

    def test_opus_most_expensive_claude(self):
        opus = calculate_cost("claude-opus-4-6", 10000, 5000)
        sonnet = calculate_cost("claude-sonnet-4-6", 10000, 5000)
        assert opus > sonnet

    def test_gpt4o_more_than_mini(self):
        full = calculate_cost("gpt-4o", 10000, 5000)
        mini = calculate_cost("gpt-4o-mini", 10000, 5000)
        assert full > mini

    def test_gemini_flash_cheaper_than_pro(self):
        flash = calculate_cost("gemini-2.0-flash", 10000, 5000)
        pro = calculate_cost("gemini-1.5-pro", 10000, 5000)
        assert flash < pro

    def test_claude_sonnet_1m_tokens_cost(self):
        # 1M input + 1M output = $3 + $15 = $18
        cost = calculate_cost("claude-sonnet-4-6", 1_000_000, 1_000_000)
        assert abs(cost - 18.0) < 0.01

    def test_fully_cached_input_cheaper(self):
        no_cache = calculate_cost("claude-sonnet-4-6", 10000, 0, cached_tokens=0)
        full_cache = calculate_cost("claude-sonnet-4-6", 10000, 0, cached_tokens=10000)
        assert full_cache < no_cache

    def test_cross_provider_all_positive(self):
        for model in ["claude-sonnet-4-6", "gpt-4o", "gemini-2.0-flash"]:
            assert calculate_cost(model, 10000, 5000) > 0

    def test_prefix_match_versioned_model(self):
        # "claude-sonnet-4-6-20250514" should match "claude-sonnet-4-6"
        cost = calculate_cost("claude-sonnet-4-6-20250514", 1000, 500)
        assert cost > 0


class TestModelPrices:
    """CL25, CI13, FN32."""

    def test_model_count_at_least_15(self):
        assert len(MODEL_PRICES) >= 15

    def test_all_models_have_required_fields(self):
        for model, prices in MODEL_PRICES.items():
            assert "input" in prices, f"{model} missing input"
            assert "output" in prices, f"{model} missing output"
            assert "cache" in prices, f"{model} missing cache"


class TestFindCheapest:
    """CL22, CI11-CI12, CS35, XA27-XA29."""

    def test_finds_cheaper_than_opus(self):
        result = find_cheapest("claude-opus-4-6", 1000, 500)
        assert result is not None
        assert result.model != "claude-opus-4-6"
        assert result.savings > 0

    def test_cheapest_not_same_model(self):
        result = find_cheapest("claude-opus-4-6", 1000, 500)
        assert result is not None
        assert result.model != "claude-opus-4-6"

    def test_cheapest_has_positive_savings(self):
        result = find_cheapest("o1", 1000, 500)
        assert result is not None
        assert result.savings > 0

    def test_cheapest_savings_percent(self):
        result = find_cheapest("claude-opus-4-6", 10000, 5000)
        assert result is not None
        assert result.savings_percent > 0

    def test_unknown_model_returns_none(self):
        result = find_cheapest("totally-unknown-model-xyz", 1000, 500)
        assert result is None

    def test_cheapest_already_cheapest(self):
        # gemini-1.5-flash is likely the cheapest — may return None
        result = find_cheapest("gemini-1.5-flash", 1000, 500)
        # Either None or a genuinely cheaper model
        if result is not None:
            assert result.cost < calculate_cost("gemini-1.5-flash", 1000, 500)
