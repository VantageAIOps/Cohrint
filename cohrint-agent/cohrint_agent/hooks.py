"""
hooks.py — Pre/post hook pipeline for CohrintSession.

All hooks are pure functions: HookContext in → HookContext out.
They never touch CohrintSession internals directly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from rich.console import Console

from .classifier import classify_input
from .optimizer import optimize_prompt

_console = Console()

BUDGET_WARN_THRESHOLD = 0.80  # warn at 80%


class BudgetExceededError(Exception):
    """Raised by check_budget_hook when api backend exceeds budget."""


@dataclass
class CostSummary:
    total_cost_usd: float = 0.0
    prompt_count: int = 0
    budget_usd: float = 0.0  # 0 = no budget set


@dataclass
class HookContext:
    prompt: str
    history: list[dict]
    backend_name: str                        # "api" | "claude" | "codex" | "gemini"
    backend_token_count: str                 # "exact" | "estimated" | "free_tier"
    session_id: str
    result: object | None                    # BackendResult after send, None before
    cost_so_far: CostSummary
    prompt_type: str = "unknown"             # set by classify_input_hook


# ---------------------------------------------------------------------------
# Pre-send hooks
# ---------------------------------------------------------------------------

def classify_input_hook(ctx: HookContext) -> HookContext:
    """Classify prompt type. Sets ctx.prompt_type."""
    ctx.prompt_type = classify_input(ctx.prompt, agent=ctx.backend_name)
    return ctx


def optimize_prompt_hook(ctx: HookContext) -> HookContext:
    """Compress prompt if type == 'prompt'. Idempotency-checked: skip if < 2% savings."""
    if ctx.prompt_type != "prompt":
        return ctx
    result = optimize_prompt(ctx.prompt)
    optimized = result.optimized if hasattr(result, "optimized") else str(result)
    original_len = len(ctx.prompt)
    savings_pct = (original_len - len(optimized)) / original_len if original_len > 0 else 0
    if savings_pct >= 0.02:
        ctx.prompt = optimized
    return ctx


def check_budget_hook(ctx: HookContext) -> HookContext:
    """
    Enforce budget.
    - API backend: raise BudgetExceededError if over budget.
    - CLI backends: print warning only (can't hard-stop a subprocess).
    - At 80%: print warning regardless of backend.
    """
    if ctx.cost_so_far.budget_usd <= 0:
        return ctx

    fraction = ctx.cost_so_far.total_cost_usd / ctx.cost_so_far.budget_usd

    if fraction >= 1.0:
        if ctx.backend_name == "api":
            raise BudgetExceededError(
                f"Budget exceeded: ${ctx.cost_so_far.total_cost_usd:.4f} / "
                f"${ctx.cost_so_far.budget_usd:.2f}"
            )
        else:
            _console.print(
                f"  [yellow]⚠ Budget exceeded "
                f"(${ctx.cost_so_far.total_cost_usd:.4f} / ${ctx.cost_so_far.budget_usd:.2f}) "
                f"— cannot hard-stop {ctx.backend_name} backend[/yellow]"
            )
    elif fraction >= BUDGET_WARN_THRESHOLD:
        pct = int(fraction * 100)
        _console.print(
            f"  [yellow]⚠ Budget warning: {pct}% consumed "
            f"(${ctx.cost_so_far.total_cost_usd:.4f} / ${ctx.cost_so_far.budget_usd:.2f})[/yellow]"
        )
    return ctx


PRE_HOOKS = [classify_input_hook, optimize_prompt_hook, check_budget_hook]


# ---------------------------------------------------------------------------
# Hook runners
# ---------------------------------------------------------------------------

def run_pre_hooks(ctx: HookContext) -> HookContext:
    for hook in PRE_HOOKS:
        ctx = hook(ctx)
    return ctx


def run_post_hooks(ctx: HookContext) -> HookContext:
    """Post-send hooks run after backend returns."""
    from .anomaly import check_cost_anomaly_structured

    if ctx.result is not None:
        result = ctx.result
        cost_usd = getattr(result, "cost_usd", 0.0)
        anomaly = check_cost_anomaly_structured(
            current_cost=cost_usd,
            prior_total=ctx.cost_so_far.total_cost_usd,
            prior_count=ctx.cost_so_far.prompt_count,
        )
        if anomaly.detected:
            _console.print(
                f"  [yellow]⚠ Anomaly: this prompt cost ${anomaly.current_cost:.4f} "
                f"— {anomaly.ratio:.1f}x your session average[/yellow]"
            )
    return ctx
