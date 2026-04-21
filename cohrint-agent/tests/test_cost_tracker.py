"""
Tests for cohrint_agent.cost_tracker — token usage and cost calculation.
"""
from types import SimpleNamespace

import pytest

from cohrint_agent.cost_tracker import SessionCost, TurnUsage, MODEL_PRICING


class TestModelPricing:
    def test_sonnet_pricing_exists(self):
        assert "claude-sonnet-4-6" in MODEL_PRICING

    def test_opus_pricing_exists(self):
        assert "claude-opus-4-6" in MODEL_PRICING

    def test_default_fallback_exists(self):
        assert "default" in MODEL_PRICING

    def test_pricing_has_all_fields(self):
        for model, pricing in MODEL_PRICING.items():
            assert "input" in pricing
            assert "output" in pricing
            assert "cache_read" in pricing
            assert "cache_write" in pricing


class TestSessionCost:
    def test_initial_state(self):
        sc = SessionCost(model="claude-sonnet-4-6")
        assert sc.total_input == 0
        assert sc.total_output == 0
        assert sc.total_cost_usd == 0.0
        assert sc.prompt_count == 0
        assert len(sc.turns) == 0

    def test_record_usage(self):
        sc = SessionCost(model="claude-sonnet-4-6")
        usage = SimpleNamespace(
            input_tokens=1000,
            output_tokens=500,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        turn = sc.record_usage(usage)
        assert turn.input_tokens == 1000
        assert turn.output_tokens == 500
        assert sc.total_input == 1000
        assert sc.total_output == 500
        assert sc.total_cost_usd > 0

    def test_cost_calculation_sonnet(self):
        sc = SessionCost(model="claude-sonnet-4-6")
        usage = SimpleNamespace(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        turn = sc.record_usage(usage)
        # Sonnet: $3/M input + $15/M output = $18
        assert abs(turn.cost_usd - 18.0) < 0.01

    def test_cost_calculation_opus(self):
        sc = SessionCost(model="claude-opus-4-6")
        usage = SimpleNamespace(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        turn = sc.record_usage(usage)
        # Opus: $15/M input + $75/M output = $90
        assert abs(turn.cost_usd - 90.0) < 0.01

    def test_accumulates_across_turns(self):
        sc = SessionCost(model="claude-sonnet-4-6")
        for _ in range(3):
            usage = SimpleNamespace(
                input_tokens=100,
                output_tokens=50,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            )
            sc.record_usage(usage)
        assert sc.total_input == 300
        assert sc.total_output == 150
        assert len(sc.turns) == 3

    def test_record_prompt_increments(self):
        sc = SessionCost()
        sc.record_prompt()
        sc.record_prompt()
        assert sc.prompt_count == 2

    def test_unknown_model_uses_default(self):
        sc = SessionCost(model="unknown-model-xyz")
        usage = SimpleNamespace(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        turn = sc.record_usage(usage)
        # Default = sonnet pricing: $3 + $15 = $18
        assert abs(turn.cost_usd - 18.0) < 0.01

    def test_cache_tokens_affect_cost(self):
        sc = SessionCost(model="claude-sonnet-4-6")
        usage = SimpleNamespace(
            input_tokens=0,
            output_tokens=0,
            cache_read_input_tokens=1_000_000,
            cache_creation_input_tokens=1_000_000,
        )
        turn = sc.record_usage(usage)
        # $0.30/M cache_read + $3.75/M cache_write = $4.05
        assert abs(turn.cost_usd - 4.05) < 0.01

    def test_handles_none_usage_fields(self):
        sc = SessionCost(model="claude-sonnet-4-6")
        usage = SimpleNamespace(
            input_tokens=100,
            output_tokens=None,
            cache_read_input_tokens=None,
            cache_creation_input_tokens=None,
        )
        turn = sc.record_usage(usage)
        assert turn.output_tokens == 0
        assert turn.cost_usd > 0
