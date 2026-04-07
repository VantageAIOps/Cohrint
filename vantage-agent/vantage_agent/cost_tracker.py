"""
cost_tracker.py — Track real token usage and costs from Anthropic API responses.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Pricing per million tokens (USD) — updated April 2025
MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_write": 3.75},
    "claude-opus-4-6": {"input": 15.0, "output": 75.0, "cache_read": 1.50, "cache_write": 18.75},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0, "cache_read": 0.08, "cache_write": 1.0},
    # Fallback
    "default": {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_write": 3.75},
}


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

    def record_usage(self, usage: Any) -> TurnUsage:
        """Record usage from an Anthropic API response message.usage object."""
        pricing = MODEL_PRICING.get(self.model, MODEL_PRICING["default"])

        inp = getattr(usage, "input_tokens", 0) or 0
        out = getattr(usage, "output_tokens", 0) or 0
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0

        cost = (
            (inp / 1_000_000) * pricing["input"]
            + (out / 1_000_000) * pricing["output"]
            + (cache_read / 1_000_000) * pricing["cache_read"]
            + (cache_write / 1_000_000) * pricing["cache_write"]
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
