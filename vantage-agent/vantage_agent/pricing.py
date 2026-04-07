from __future__ import annotations

from dataclasses import dataclass

MODEL_PRICES: dict[str, dict[str, float]] = {
    "gpt-4o":               {"input": 2.50,  "output": 10.00, "cache": 1.25},
    "gpt-4o-mini":          {"input": 0.15,  "output": 0.60,  "cache": 0.075},
    "o1":                   {"input": 15.00, "output": 60.00, "cache": 7.50},
    "o3-mini":              {"input": 1.10,  "output": 4.40,  "cache": 0.55},
    "gpt-3.5-turbo":        {"input": 0.50,  "output": 1.50,  "cache": 0.25},
    "claude-opus-4-6":      {"input": 15.00, "output": 75.00, "cache": 1.50},
    "claude-sonnet-4-6":    {"input": 3.00,  "output": 15.00, "cache": 0.30},
    "claude-haiku-4-5":     {"input": 0.80,  "output": 4.00,  "cache": 0.08},
    "gemini-2.0-flash":     {"input": 0.10,  "output": 0.40,  "cache": 0.025},
    "gemini-1.5-pro":       {"input": 1.25,  "output": 5.00,  "cache": 0.31},
    "gemini-1.5-flash":     {"input": 0.075, "output": 0.30,  "cache": 0.018},
    "llama-3.3-70b":        {"input": 0.23,  "output": 0.40,  "cache": 0.0},
    "mistral-large-latest": {"input": 2.00,  "output": 6.00,  "cache": 0.0},
    "deepseek-chat":        {"input": 0.27,  "output": 1.10,  "cache": 0.0},
    "grok-2":               {"input": 2.00,  "output": 10.00, "cache": 0.0},
}

_MILLION = 1_000_000


def _resolve_model(model: str) -> str | None:
    """Return the canonical model key for `model`, or None if unknown."""
    if model in MODEL_PRICES:
        return model
    # Prefix match — e.g. "gpt-4o-2024-11-20" → "gpt-4o"
    for key in MODEL_PRICES:
        if model.startswith(key):
            return key
    return None


def calculate_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int = 0,
) -> float:
    """Return total cost in USD. Prices are per 1 million tokens.

    cached_tokens are billed at the cache rate instead of the input rate.
    Unknown models return 0.
    """
    key = _resolve_model(model)
    if key is None:
        return 0.0

    prices = MODEL_PRICES[key]
    non_cached_input = max(prompt_tokens - cached_tokens, 0)

    cost = (
        non_cached_input * prices["input"] / _MILLION
        + cached_tokens * prices["cache"] / _MILLION
        + completion_tokens * prices["output"] / _MILLION
    )
    return cost


@dataclass
class CheapestResult:
    model: str
    cost: float
    savings: float
    savings_percent: float


def find_cheapest(
    current_model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> CheapestResult | None:
    """Return the cheapest alternative model (excluding current_model).

    Returns None if current_model is unknown or no alternatives exist.
    """
    if _resolve_model(current_model) is None:
        return None

    current_cost = calculate_cost(current_model, prompt_tokens, completion_tokens)

    best_model: str | None = None
    best_cost = float("inf")

    for key in MODEL_PRICES:
        if key == _resolve_model(current_model):
            continue
        cost = calculate_cost(key, prompt_tokens, completion_tokens)
        if cost < best_cost:
            best_cost = cost
            best_model = key

    if best_model is None or best_cost >= current_cost:
        return None

    savings = current_cost - best_cost
    savings_percent = (savings / current_cost * 100) if current_cost > 0 else 0.0

    return CheapestResult(
        model=best_model,
        cost=best_cost,
        savings=savings,
        savings_percent=savings_percent,
    )
