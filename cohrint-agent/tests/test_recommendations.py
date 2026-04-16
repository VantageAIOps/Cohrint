"""Tests for recommendations.py — agent-aware recommendation engine.

Covers all scenarios from suite 35_recommendations (R01-R30).
"""
import pytest
from vantage_agent.recommendations import (
    get_recommendations,
    get_inline_tip,
    format_recommendations,
    normalize_agent_name,
    SessionMetrics,
)


def _zero_metrics(**overrides) -> SessionMetrics:
    base = dict(
        prompt_count=0, total_cost_usd=0.0, total_input_tokens=0,
        total_output_tokens=0, total_cached_tokens=0,
    )
    base.update(overrides)
    return SessionMetrics(**base)


class TestGetRecommendations:
    """R01-R08."""

    def test_r01_empty_when_no_conditions_met(self):
        tips = get_recommendations(_zero_metrics())
        assert len(tips) == 0

    def test_r02_default_max_tips_3(self):
        m = _zero_metrics(agent="claude", model="claude-opus-4-6",
                          prompt_count=20, total_cost_usd=6.0,
                          total_input_tokens=60000, total_cached_tokens=100)
        tips = get_recommendations(m)
        assert len(tips) <= 3

    def test_r03_explicit_max_tips_1(self):
        m = _zero_metrics(agent="claude", model="claude-opus-4-6",
                          prompt_count=20, total_cost_usd=6.0,
                          total_input_tokens=60000, total_cached_tokens=100)
        tips = get_recommendations(m, max_tips=1)
        assert len(tips) <= 1

    def test_r04_claude_tips_filtered_for_gemini(self):
        m = _zero_metrics(agent="gemini", model="gemini-1.5-pro",
                          prompt_count=10, total_cost_usd=2.0,
                          total_input_tokens=5000, total_cached_tokens=0)
        tips = get_recommendations(m, max_tips=10)
        ids = [t.id for t in tips]
        claude_ids = [i for i in ids if i.startswith("claude-")]
        assert len(claude_ids) == 0

    def test_r05_gemini_tips_filtered_for_claude(self):
        m = _zero_metrics(agent="claude", model="claude-sonnet-4-6",
                          prompt_count=10, total_cost_usd=6.0,
                          total_input_tokens=60000, total_cached_tokens=100)
        tips = get_recommendations(m, max_tips=10)
        ids = [t.id for t in tips]
        gemini_ids = [i for i in ids if i.startswith("gemini-")]
        assert len(gemini_ids) == 0

    def test_r06_universal_tips_for_any_agent(self):
        m = _zero_metrics(agent="gemini", model="gemini-2.0-flash",
                          prompt_count=10, total_cost_usd=6.0,
                          total_input_tokens=5000, total_cached_tokens=0)
        tips = get_recommendations(m, max_tips=10)
        ids = [t.id for t in tips]
        assert "all-high-cost-alert" in ids

    def test_r07_priority_order_critical_before_high(self):
        m = _zero_metrics(agent="claude", model="claude-opus-4-6",
                          prompt_count=20, total_cost_usd=6.0,
                          total_input_tokens=60000, total_cached_tokens=100)
        tips = get_recommendations(m, max_tips=10)
        priorities = [t.priority for t in tips]
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        for i in range(len(priorities) - 1):
            assert order[priorities[i]] <= order[priorities[i + 1]]

    def test_r08_unknown_agent_gets_universal_only(self):
        m = _zero_metrics(agent="unknown-tool", total_cost_usd=6.0,
                          prompt_count=10, total_input_tokens=5000,
                          total_cached_tokens=0)
        tips = get_recommendations(m, max_tips=10)
        for t in tips:
            assert t.id.startswith("all-"), f"Non-universal tip {t.id} for unknown agent"


class TestConditionTriggers:
    """R09-R15."""

    def test_r09_claude_use_sonnet_fires_for_cheap_opus(self):
        m = _zero_metrics(agent="claude", model="claude-opus-4-6",
                          prompt_count=5, total_cost_usd=0.20,
                          total_input_tokens=5000, total_cached_tokens=0)
        tips = get_recommendations(m, max_tips=10)
        assert "claude-use-sonnet" in [t.id for t in tips]

    def test_r10_claude_use_sonnet_not_for_expensive_opus(self):
        m = _zero_metrics(agent="claude", model="claude-opus-4-6",
                          prompt_count=5, total_cost_usd=2.50,
                          total_input_tokens=5000, total_cached_tokens=0)
        tips = get_recommendations(m, max_tips=10)
        assert "claude-use-sonnet" not in [t.id for t in tips]

    def test_r11_high_cost_fires_above_5(self):
        m = _zero_metrics(total_cost_usd=5.01, prompt_count=1,
                          total_input_tokens=100, total_cached_tokens=0)
        tips = get_recommendations(m, max_tips=10)
        assert "all-high-cost-alert" in [t.id for t in tips]

    def test_r12_high_cost_not_below_5(self):
        m = _zero_metrics(total_cost_usd=4.99, prompt_count=1,
                          total_input_tokens=100, total_cached_tokens=0)
        tips = get_recommendations(m, max_tips=10)
        assert "all-high-cost-alert" not in [t.id for t in tips]

    def test_r13_claude_compact_fires_at_50k_tokens(self):
        m = _zero_metrics(agent="claude", model="claude-sonnet-4-6",
                          prompt_count=6, total_cost_usd=1.0,
                          total_input_tokens=51000, total_cached_tokens=0)
        tips = get_recommendations(m, max_tips=10)
        assert "claude-compact" in [t.id for t in tips]

    def test_r14_gemini_use_flash_fires_for_pro(self):
        m = _zero_metrics(agent="gemini", model="gemini-1.5-pro",
                          prompt_count=5, total_cost_usd=1.0,
                          total_input_tokens=5000, total_cached_tokens=0)
        tips = get_recommendations(m, max_tips=10)
        assert "gemini-use-flash" in [t.id for t in tips]

    def test_r15_large_prompt_fires_above_10k(self):
        m = _zero_metrics(prompt_count=5, total_cost_usd=1.0,
                          total_input_tokens=5000, total_cached_tokens=0,
                          last_prompt_tokens=10001)
        tips = get_recommendations(m, max_tips=10)
        assert "all-large-prompt" in [t.id for t in tips]


class TestTemplatePlaceholders:
    """R16-R18."""

    def test_r16_cost_placeholder_replaced(self):
        m = _zero_metrics(total_cost_usd=6.75, prompt_count=5,
                          total_input_tokens=5000, total_cached_tokens=0)
        tips = get_recommendations(m, max_tips=10)
        for t in tips:
            assert "${" not in t.action, f"Raw placeholder in: {t.action}"

    def test_r17_tokens_placeholder_replaced(self):
        m = _zero_metrics(prompt_count=5, total_cost_usd=1.0,
                          total_input_tokens=5000, total_cached_tokens=0,
                          last_prompt_tokens=12345)
        tips = get_recommendations(m, max_tips=10)
        for t in tips:
            assert "${tokens}" not in t.action

    def test_r18_pct_placeholder_replaced(self):
        m = _zero_metrics(prompt_count=5, total_cost_usd=1.0,
                          total_input_tokens=20000, total_cached_tokens=500,
                          agent="claude", model="claude-sonnet-4-6")
        tips = get_recommendations(m, max_tips=10)
        for t in tips:
            assert "${pct}" not in t.action


class TestGetInlineTip:
    """R19-R23."""

    def test_r19_returns_none_when_no_tips(self):
        assert get_inline_tip(_zero_metrics()) is None

    def test_r20_returns_string_when_tip_applies(self):
        m = _zero_metrics(total_cost_usd=6.0, prompt_count=5,
                          total_input_tokens=5000, total_cached_tokens=0)
        tip = get_inline_tip(m)
        assert tip is not None
        assert len(tip) > 0

    def test_r21_critical_tip_uses_red_circle(self):
        m = _zero_metrics(total_cost_usd=6.0, prompt_count=5,
                          total_input_tokens=5000, total_cached_tokens=0)
        tip = get_inline_tip(m)
        assert tip is not None
        assert tip.startswith("🔴")

    def test_r22_high_tip_uses_yellow_circle(self):
        m = _zero_metrics(agent="claude", model="claude-opus-4-6",
                          prompt_count=5, total_cost_usd=0.20,
                          total_input_tokens=5000, total_cached_tokens=0)
        tip = get_inline_tip(m)
        assert tip is not None
        assert tip.startswith("🟡")

    def test_r23_inline_tip_includes_savings(self):
        m = _zero_metrics(total_cost_usd=6.0, prompt_count=5,
                          total_input_tokens=5000, total_cached_tokens=0)
        tip = get_inline_tip(m)
        assert tip is not None
        assert "(" in tip  # savings estimate in parentheses


class TestNormalizeAgentName:
    """R24-R26."""

    def test_r24_claude_code_normalizes(self):
        m = _zero_metrics(agent="claude-code", model="claude-opus-4-6",
                          prompt_count=5, total_cost_usd=0.20,
                          total_input_tokens=5000, total_cached_tokens=0)
        tips = get_recommendations(m, max_tips=10)
        claude_ids = [t.id for t in tips if t.id.startswith("claude-")]
        assert len(claude_ids) > 0  # claude tips fire

    def test_r25_openai_codex_normalizes(self):
        assert normalize_agent_name("openai-codex") == "codex"

    def test_r26_cursor_normalizes_to_chatgpt(self):
        assert normalize_agent_name("cursor") == "chatgpt"


class TestFormatRecommendations:
    """R27-R30."""

    def test_r27_empty_returns_empty_string(self):
        assert format_recommendations([]) == ""

    def test_r28_contains_title(self):
        m = _zero_metrics(total_cost_usd=6.0, prompt_count=5,
                          total_input_tokens=5000, total_cached_tokens=0)
        tips = get_recommendations(m)
        output = format_recommendations(tips)
        assert "Recommendations" in output

    def test_r29_contains_savings(self):
        m = _zero_metrics(total_cost_usd=6.0, prompt_count=5,
                          total_input_tokens=5000, total_cached_tokens=0)
        tips = get_recommendations(m)
        output = format_recommendations(tips)
        assert "Savings:" in output

    def test_r30_has_border_lines(self):
        m = _zero_metrics(total_cost_usd=6.0, prompt_count=5,
                          total_input_tokens=5000, total_cached_tokens=0)
        tips = get_recommendations(m)
        output = format_recommendations(tips)
        assert "┌" in output
        assert "└" in output
