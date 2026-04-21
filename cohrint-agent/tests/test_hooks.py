"""Tests for the pre/post hook pipeline."""
from __future__ import annotations

import pytest

from cohrint_agent.hooks import (
    HookContext,
    CostSummary,
    classify_input_hook,
    optimize_prompt_hook,
    check_budget_hook,
    BudgetExceededError,
)
from cohrint_agent.anomaly import check_cost_anomaly_structured


def _ctx(prompt: str = "hello world how are you doing today", budget_usd: float = 10.0) -> HookContext:
    return HookContext(
        prompt=prompt,
        history=[],
        backend_name="api",
        backend_token_count="exact",
        session_id="test-session",
        result=None,
        cost_so_far=CostSummary(total_cost_usd=0.0, prompt_count=0, budget_usd=budget_usd),
    )


def test_classifier_gates_optimizer_for_short_answers():
    """Short answers must NOT be passed through optimizer."""
    ctx = _ctx(prompt="yes")
    ctx2 = classify_input_hook(ctx)
    assert ctx2.prompt_type == "short-answer"
    ctx3 = optimize_prompt_hook(ctx2)
    assert ctx3.prompt == "yes"  # unchanged


def test_optimizer_runs_for_prompt_type():
    """Long natural language prompts classified as 'prompt' get optimized."""
    long = "i would appreciate it if you could please refactor this entire function for me in detail"
    ctx = _ctx(prompt=long)
    ctx2 = classify_input_hook(ctx)
    assert ctx2.prompt_type == "prompt"
    ctx3 = optimize_prompt_hook(ctx2)
    assert len(ctx3.prompt) < len(long)


def test_already_optimized_not_re_optimized():
    """If optimizer output ≈ input (< 2% savings), skip re-optimization."""
    clean = "Refactor this function to reduce cyclomatic complexity."
    ctx = _ctx(prompt=clean)
    ctx2 = classify_input_hook(ctx)
    ctx3 = optimize_prompt_hook(ctx2)
    ctx4 = optimize_prompt_hook(ctx3)
    assert ctx4.prompt == ctx3.prompt


def test_budget_warns_at_80_percent(capsys):
    """At 80%+ budget consumed, a warning is printed but execution continues."""
    ctx = _ctx(budget_usd=1.0)
    ctx.cost_so_far.total_cost_usd = 0.81  # 81%
    result = check_budget_hook(ctx)  # must NOT raise
    assert result is not None


def test_budget_blocks_api_send_when_exceeded():
    """When budget exceeded on api backend, BudgetExceededError is raised."""
    ctx = _ctx(budget_usd=1.0)
    ctx.cost_so_far.total_cost_usd = 1.01
    ctx.backend_name = "api"
    with pytest.raises(BudgetExceededError):
        check_budget_hook(ctx)


def test_budget_does_not_hard_stop_cli_backend():
    """CLI backends get a warning but NOT a hard stop."""
    ctx = _ctx(budget_usd=1.0)
    ctx.cost_so_far.total_cost_usd = 1.01
    ctx.backend_name = "claude"
    check_budget_hook(ctx)  # must not raise


def test_anomaly_returns_structured_result_not_side_effect():
    """check_cost_anomaly_structured must return AnomalyResult, not print directly."""
    result = check_cost_anomaly_structured(
        current_cost=0.10,
        prior_total=0.02,   # avg = 0.01
        prior_count=2,
    )
    assert hasattr(result, "detected")
    assert hasattr(result, "ratio")
    assert result.detected is True
    assert result.ratio >= 3.0
