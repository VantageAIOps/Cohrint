"""
cost_tracker.py — Track real token usage and costs from Anthropic API responses.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .pricing import MODEL_PRICES as MODEL_PRICING  # single source of truth


@dataclass
class TurnUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class SessionCost:
    model: str = "claude-sonnet-4-6"
    turns: list[TurnUsage] = field(default_factory=list)
    total_input: int = 0
    total_output: int = 0
    total_cache_read: int = 0
    total_cache_write: int = 0
    total_cost_usd: float = 0.0
    prompt_count: int = 0
    # Optimizer-reported savings across the session. Used by /summary (T-SUMMARY.1).
    total_saved_tokens: int = 0
    total_saved_usd: float = 0.0

    def record_optimization(self, saved_tokens: int, saved_usd: float) -> None:
        """Accumulate token + dollar savings from prompt optimization."""
        if saved_tokens <= 0:
            return
        self.total_saved_tokens += int(saved_tokens)
        self.total_saved_usd += max(0.0, float(saved_usd))

    def record_usage(self, usage: Any) -> TurnUsage:
        """Record usage from an Anthropic API response message.usage object."""
        pricing = MODEL_PRICING.get(self.model, MODEL_PRICING.get("claude-sonnet-4-6", {
            "input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_write": 3.75
        }))

        # Clamp to >= 0 so a buggy backend returning -1 cannot decrement
        # the session total (T-COST.nonneg). `or 0` protects against None,
        # not against negatives — `-1 or 0` evaluates to -1.
        inp = max(0, getattr(usage, "input_tokens", 0) or 0)
        out = max(0, getattr(usage, "output_tokens", 0) or 0)
        cache_read = max(0, getattr(usage, "cache_read_input_tokens", 0) or 0)
        cache_write = max(0, getattr(usage, "cache_creation_input_tokens", 0) or 0)

        cost = (
            (inp / 1_000_000) * pricing["input"]
            + (out / 1_000_000) * pricing["output"]
            + (cache_read / 1_000_000) * pricing.get("cache_read", pricing.get("cache", 0))
            + (cache_write / 1_000_000) * pricing.get("cache_write", 0)
        )

        turn = TurnUsage(
            input_tokens=inp,
            output_tokens=out,
            cache_read_tokens=cache_read,
            cache_creation_tokens=cache_write,
            cost_usd=cost,
        )
        self.turns.append(turn)
        self.total_input += inp
        self.total_output += out
        self.total_cache_read += cache_read
        self.total_cache_write += cache_write
        self.total_cost_usd += cost
        return turn

    def record_prompt(self) -> None:
        self.prompt_count += 1

    def record_usage_raw(
        self,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        cache_read_tokens: int = 0,
    ) -> TurnUsage:
        """Record pre-computed token counts (used by ClaudeCliBackend with exact counts)."""
        # Clamp to non-negative so a malformed CC `result` event can't
        # decrement the accumulator (T-COST.nonneg). A negative cost
        # poisons both the session total and every budget check.
        input_tokens = max(0, int(input_tokens))
        output_tokens = max(0, int(output_tokens))
        cache_read_tokens = max(0, int(cache_read_tokens))
        cost_usd = max(0.0, float(cost_usd))
        turn = TurnUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cost_usd=cost_usd,
        )
        self.turns.append(turn)
        self.total_input += input_tokens
        self.total_output += output_tokens
        self.total_cache_read += cache_read_tokens
        self.total_cost_usd += cost_usd
        self.prompt_count += 1
        return turn
