"""
Test Suite 35 — Recommendation Engine (TDD)
Tests for cohrint-cli recommendation engine:
  getRecommendations, getInlineTip, formatRecommendations, normalizeAgentName
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from helpers.output import section, chk

CLI_DIR = Path(__file__).parent.parent.parent.parent / "cohrint-cli"
HARNESS = CLI_DIR / "test-recommendations.mjs"

if not HARNESS.exists():
    pytest.skip(f"Recommendation harness not found: {HARNESS}", allow_module_level=True)


def rec(cmd: str, metrics: dict, extra: dict | None = None, timeout: int = 10) -> dict:
    """Run test-recommendations.mjs via node and return parsed JSON."""
    payload = {"metrics": metrics}
    if extra:
        payload.update(extra)
    result = subprocess.run(
        ["node", str(HARNESS), cmd, json.dumps(payload)],
        capture_output=True, text=True, timeout=timeout,
        cwd=str(CLI_DIR),
    )
    try:
        return json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        return {"error": result.stderr or result.stdout}


# ── Baseline metrics ─────────────────────────────────────────────────────────

ZERO = dict(
    promptCount=0, totalCostUsd=0, totalInputTokens=0,
    totalOutputTokens=0, totalCachedTokens=0,
)

def claude_base(**overrides):
    return {**ZERO, "agent": "claude", "model": "claude-sonnet-4-6", **overrides}

def gemini_base(**overrides):
    return {**ZERO, "agent": "gemini", "model": "gemini-2.0-flash", **overrides}


# ── Section A: getRecommendations — filtering and limits ─────────────────────

class TestGetRecommendations:

    def test_r01_returns_empty_when_no_conditions_met(self):
        section("A — getRecommendations filtering and limits")
        r = rec("recommendations", ZERO)
        chk("R.01 no tips when conditions not met", r.get("count", -1) == 0)
        assert r.get("count") == 0

    def test_r02_respects_maxTips_default_of_3(self):
        """High cost + high avg + large prompt + cache low = many conditions met; default cap is 3."""
        metrics = claude_base(
            promptCount=10,
            totalCostUsd=10.0,
            totalInputTokens=100_000,
            totalCachedTokens=0,
            totalOutputTokens=5_000,
            lastPromptTokens=15_000,
        )
        r = rec("recommendations", metrics)
        chk("R.02 default maxTips=3 limits output", r.get("count", 0) <= 3)
        assert r.get("count", 0) <= 3

    def test_r03_respects_explicit_maxTips(self):
        metrics = claude_base(
            promptCount=10, totalCostUsd=10.0,
            totalInputTokens=100_000, totalCachedTokens=0,
            totalOutputTokens=5_000, lastPromptTokens=15_000,
        )
        r = rec("recommendations", metrics, {"maxTips": 1})
        chk("R.03 explicit maxTips=1 returns at most 1", r.get("count", 0) <= 1)
        assert r.get("count", 0) <= 1

    def test_r04_agent_tips_filtered_to_matching_agent(self):
        """Claude-specific tips must not appear for gemini agent."""
        metrics = gemini_base(
            promptCount=10, totalCostUsd=10.0,
            totalInputTokens=5_000, totalCachedTokens=0,
        )
        r = rec("recommendations", metrics)
        tip_ids = r.get("ids", [])
        claude_only = [t for t in tip_ids if t.startswith("claude-")]
        chk("R.04 no claude-specific tips for gemini agent", len(claude_only) == 0)
        assert len(claude_only) == 0

    def test_r05_gemini_tips_filtered_to_gemini_agent(self):
        """Gemini-specific tips must not appear for claude agent."""
        metrics = claude_base(
            promptCount=10, totalCostUsd=0.50,
            totalInputTokens=5_000, totalCachedTokens=0,
        )
        r = rec("recommendations", metrics)
        tip_ids = r.get("ids", [])
        gemini_only = [t for t in tip_ids if t.startswith("gemini-")]
        chk("R.05 no gemini-specific tips for claude agent", len(gemini_only) == 0)
        assert len(gemini_only) == 0

    def test_r06_universal_tips_appear_for_any_agent(self):
        """all-high-cost-alert must fire for any agent when cost > 5.00."""
        metrics = gemini_base(
            promptCount=5, totalCostUsd=6.00,
            totalInputTokens=5_000, totalCachedTokens=0,
        )
        r = rec("recommendations", metrics, {"maxTips": 10})
        tip_ids = r.get("ids", [])
        chk("R.06 all-high-cost-alert fires for gemini at high cost",
            "all-high-cost-alert" in tip_ids)
        assert "all-high-cost-alert" in tip_ids

    def test_r07_priority_order_critical_before_high(self):
        """Critical tips must appear before high-priority tips."""
        metrics = claude_base(
            promptCount=10, totalCostUsd=6.00,
            totalInputTokens=100_000, totalCachedTokens=0,
            totalOutputTokens=5_000, lastPromptTokens=15_000,
            model="claude-opus-4-6",
        )
        r = rec("recommendations", metrics, {"maxTips": 10})
        priorities = r.get("priorities", [])
        chk("R.07 at least one tip returned", len(priorities) > 0)
        for i in range(len(priorities) - 1):
            order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            ok_order = order.get(priorities[i], 99) <= order.get(priorities[i+1], 99)
            chk(f"R.07 priority[{i}]={priorities[i]} <= priority[{i+1}]={priorities[i+1]}", ok_order)
            assert ok_order

    def test_r08_unknown_agent_gets_universal_tips_only(self):
        """Unknown agent must only receive 'all' tips, not agent-specific ones."""
        metrics = {**ZERO, "agent": "unknown-tool", "promptCount": 5,
                   "totalCostUsd": 6.00, "totalInputTokens": 5_000, "totalCachedTokens": 0}
        r = rec("recommendations", metrics, {"maxTips": 10})
        tip_ids = r.get("ids", [])
        specific = [t for t in tip_ids if not t.startswith("all-")]
        chk("R.08 unknown agent receives only universal tips", len(specific) == 0)
        assert len(specific) == 0


# ── Section B: Specific condition triggers ───────────────────────────────────

class TestConditionTriggers:

    def test_r09_claude_use_sonnet_fires_for_opus_cheap_prompts(self):
        section("B — Condition triggers")
        metrics = claude_base(
            model="claude-opus-4-6",
            promptCount=5,
            totalCostUsd=0.40,   # avgCostPerPrompt = 0.08 < 0.10
            totalInputTokens=5_000, totalCachedTokens=0,
        )
        r = rec("recommendations", metrics, {"maxTips": 10})
        chk("R.09 claude-use-sonnet fires for opus with cheap prompts",
            "claude-use-sonnet" in r.get("ids", []))
        assert "claude-use-sonnet" in r.get("ids", [])

    def test_r10_claude_use_sonnet_does_not_fire_for_expensive_opus(self):
        """If avgCostPerPrompt >= 0.10, sonnet tip should NOT fire (complex task, keep opus)."""
        metrics = claude_base(
            model="claude-opus-4-6",
            promptCount=5,
            totalCostUsd=1.00,   # avgCostPerPrompt = 0.20 >= 0.10
            totalInputTokens=5_000, totalCachedTokens=0,
        )
        r = rec("recommendations", metrics, {"maxTips": 10})
        chk("R.10 claude-use-sonnet does NOT fire for expensive opus prompts",
            "claude-use-sonnet" not in r.get("ids", []))
        assert "claude-use-sonnet" not in r.get("ids", [])

    def test_r11_high_cost_alert_fires_above_5_dollars(self):
        metrics = claude_base(
            promptCount=5, totalCostUsd=5.01,
            totalInputTokens=5_000, totalCachedTokens=0,
        )
        r = rec("recommendations", metrics, {"maxTips": 10})
        chk("R.11 all-high-cost-alert fires when totalCostUsd > 5.00",
            "all-high-cost-alert" in r.get("ids", []))
        assert "all-high-cost-alert" in r.get("ids", [])

    def test_r12_high_cost_alert_does_not_fire_below_5_dollars(self):
        metrics = claude_base(
            promptCount=5, totalCostUsd=4.99,
            totalInputTokens=5_000, totalCachedTokens=0,
        )
        r = rec("recommendations", metrics, {"maxTips": 10})
        chk("R.12 all-high-cost-alert does NOT fire at $4.99",
            "all-high-cost-alert" not in r.get("ids", []))
        assert "all-high-cost-alert" not in r.get("ids", [])

    def test_r13_claude_compact_fires_at_50k_tokens_5_prompts(self):
        metrics = claude_base(
            promptCount=6,
            totalCostUsd=0.50,
            totalInputTokens=51_000,
            totalCachedTokens=0,
        )
        r = rec("recommendations", metrics, {"maxTips": 10})
        chk("R.13 claude-compact fires at >50k tokens, >5 prompts",
            "claude-compact" in r.get("ids", []))
        assert "claude-compact" in r.get("ids", [])

    def test_r14_gemini_use_flash_fires_for_pro_model(self):
        metrics = gemini_base(
            model="gemini-1.5-pro",
            promptCount=3, totalCostUsd=0.10,
            totalInputTokens=5_000, totalCachedTokens=0,
        )
        r = rec("recommendations", metrics, {"maxTips": 10})
        chk("R.14 gemini-use-flash fires when model is pro",
            "gemini-use-flash" in r.get("ids", []))
        assert "gemini-use-flash" in r.get("ids", [])

    def test_r15_all_large_prompt_fires_above_10k_tokens(self):
        metrics = claude_base(
            promptCount=2, totalCostUsd=0.10,
            totalInputTokens=20_000, totalCachedTokens=0,
            lastPromptTokens=10_001,
        )
        r = rec("recommendations", metrics, {"maxTips": 10})
        chk("R.15 all-large-prompt fires when lastPromptTokens > 10000",
            "all-large-prompt" in r.get("ids", []))
        assert "all-large-prompt" in r.get("ids", [])


# ── Section C: Template substitution ─────────────────────────────────────────

class TestTemplateSubstitution:

    def test_r16_cost_placeholder_replaced(self):
        section("C — Template substitution")
        metrics = claude_base(
            promptCount=5, totalCostUsd=6.75,
            totalInputTokens=5_000, totalCachedTokens=0,
        )
        r = rec("recommendations", metrics, {"maxTips": 10})
        actions = r.get("actions", [])
        cost_action = next((a for a in actions if "all-high-cost-alert" in r.get("ids", []) and "6.75" in a), None)
        # Check at least one action contains the formatted cost (not the raw ${cost} template)
        raw_templates = [a for a in actions if "${" in a]
        chk("R.16 no raw ${...} templates in output actions", len(raw_templates) == 0,
            f"found raw templates: {raw_templates}")
        assert len(raw_templates) == 0

    def test_r17_tokens_placeholder_replaced(self):
        metrics = claude_base(
            promptCount=2, totalCostUsd=0.10,
            totalInputTokens=20_000, totalCachedTokens=0,
            lastPromptTokens=12_345,
        )
        r = rec("recommendations", metrics, {"maxTips": 10})
        actions = r.get("actions", [])
        raw_templates = [a for a in actions if "${" in a]
        chk("R.17 no raw ${tokens} in output actions", len(raw_templates) == 0)
        assert len(raw_templates) == 0

    def test_r18_pct_placeholder_replaced(self):
        metrics = claude_base(
            promptCount=5, totalCostUsd=0.20,
            totalInputTokens=20_000, totalCachedTokens=500,
        )
        r = rec("recommendations", metrics, {"maxTips": 10})
        actions = r.get("actions", [])
        raw_templates = [a for a in actions if "${" in a]
        chk("R.18 no raw ${pct} in output actions", len(raw_templates) == 0)
        assert len(raw_templates) == 0


# ── Section D: getInlineTip ───────────────────────────────────────────────────

class TestGetInlineTip:

    def test_r19_returns_null_when_no_tips(self):
        section("D — getInlineTip")
        r = rec("inline_tip", ZERO)
        chk("R.19 getInlineTip returns null when no conditions met",
            r.get("tip") is None)
        assert r.get("tip") is None

    def test_r20_returns_string_when_tip_applies(self):
        metrics = claude_base(
            promptCount=5, totalCostUsd=6.00,
            totalInputTokens=5_000, totalCachedTokens=0,
        )
        r = rec("inline_tip", metrics)
        tip = r.get("tip")
        chk("R.20 getInlineTip returns non-empty string when tip applies",
            isinstance(tip, str) and len(tip) > 0)
        assert isinstance(tip, str) and len(tip) > 0

    def test_r21_critical_tip_uses_red_circle(self):
        """all-high-cost-alert is critical → must use 🔴."""
        metrics = claude_base(
            promptCount=5, totalCostUsd=6.00,
            totalInputTokens=5_000, totalCachedTokens=0,
        )
        r = rec("inline_tip", metrics)
        tip = r.get("tip", "")
        chk("R.21 critical tip uses 🔴 icon", tip.startswith("🔴"), f"got: {tip[:30]}")
        assert tip.startswith("🔴")

    def test_r22_high_tip_uses_yellow_circle(self):
        """claude-use-sonnet is high priority → must use 🟡."""
        metrics = claude_base(
            model="claude-opus-4-6",
            promptCount=5,
            totalCostUsd=0.40,
            totalInputTokens=5_000, totalCachedTokens=0,
        )
        r = rec("inline_tip", metrics)
        tip = r.get("tip", "")
        # Only fires if critical doesn't override it — ensure no critical condition
        # high-cost-alert fires at >5.00, avgCostPerPrompt >0.20 — neither applies here
        chk("R.22 high tip uses 🟡 icon", tip.startswith("🟡"), f"got: {tip[:40]}")
        assert tip.startswith("🟡")

    def test_r23_inline_tip_includes_title_and_action(self):
        metrics = claude_base(
            promptCount=5, totalCostUsd=6.00,
            totalInputTokens=5_000, totalCachedTokens=0,
        )
        r = rec("inline_tip", metrics)
        tip = r.get("tip", "")
        chk("R.23 inline tip contains savings estimate in parens",
            "(" in tip and ")" in tip)
        assert "(" in tip and ")" in tip


# ── Section E: normalizeAgentName ─────────────────────────────────────────────

class TestNormalizeAgentName:

    def test_r24_claude_normalizes(self):
        section("E — normalizeAgentName (via getRecommendations)")
        # "claude" prefix match → claude tips fire
        metrics = {**ZERO, "agent": "claude-code", "model": "claude-opus-4-6",
                   "promptCount": 5, "totalCostUsd": 0.40,
                   "totalInputTokens": 5_000, "totalCachedTokens": 0}
        r = rec("recommendations", metrics, {"maxTips": 10})
        chk("R.24 'claude-code' agent normalizes to claude (claude tips fire)",
            "claude-use-sonnet" in r.get("ids", []))
        assert "claude-use-sonnet" in r.get("ids", [])

    def test_r25_openai_normalizes_to_codex(self):
        metrics = {**ZERO, "agent": "openai-codex", "model": "gpt-4o",
                   "promptCount": 3, "totalCostUsd": 0.10,
                   "totalInputTokens": 5_000, "totalCachedTokens": 0}
        r = rec("recommendations", metrics, {"maxTips": 10})
        tip_ids = r.get("ids", [])
        chk("R.25 'openai-codex' agent normalizes to codex (no gemini/claude tips)",
            not any(t.startswith("gemini-") or t.startswith("claude-") for t in tip_ids))
        assert not any(t.startswith("gemini-") or t.startswith("claude-") for t in tip_ids)

    def test_r26_cursor_normalizes_to_chatgpt(self):
        metrics = {**ZERO, "agent": "cursor", "model": "gpt-4o",
                   "promptCount": 5, "totalCostUsd": 0.60,
                   "totalInputTokens": 5_000, "totalCachedTokens": 0}
        r = rec("recommendations", metrics, {"maxTips": 10})
        tip_ids = r.get("ids", [])
        chk("R.26 'cursor' agent normalizes to chatgpt",
            any(t.startswith("cursor-") for t in tip_ids))
        assert any(t.startswith("cursor-") for t in tip_ids)


# ── Section F: formatRecommendations ─────────────────────────────────────────

class TestFormatRecommendations:

    def test_r27_empty_tips_returns_empty_string(self):
        section("F — formatRecommendations")
        r = rec("format", ZERO)
        chk("R.27 formatRecommendations([]) returns empty string",
            r.get("output", "x") == "")
        assert r.get("output") == ""

    def test_r28_formatted_output_contains_title(self):
        metrics = claude_base(
            promptCount=5, totalCostUsd=6.00,
            totalInputTokens=5_000, totalCachedTokens=0,
        )
        r = rec("format", metrics)
        output = r.get("output", "")
        chk("R.28 formatted output contains 'Live Recommendations' header",
            "Live Recommendations" in output)
        assert "Live Recommendations" in output

    def test_r29_formatted_output_contains_savings_estimate(self):
        metrics = claude_base(
            promptCount=5, totalCostUsd=6.00,
            totalInputTokens=5_000, totalCachedTokens=0,
        )
        r = rec("format", metrics)
        output = r.get("output", "")
        chk("R.29 formatted output contains 'Savings:' label",
            "Savings:" in output)
        assert "Savings:" in output

    def test_r30_formatted_output_has_border_lines(self):
        metrics = claude_base(
            promptCount=5, totalCostUsd=6.00,
            totalInputTokens=5_000, totalCachedTokens=0,
        )
        r = rec("format", metrics)
        output = r.get("output", "")
        chk("R.30 formatted output has top border (┌)",
            "┌" in output)
        chk("R.30 formatted output has bottom border (└)",
            "└" in output)
        assert "┌" in output and "└" in output
