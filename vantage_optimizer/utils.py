"""
Utility functions for token counting and cost calculation.
"""

import re
from typing import Dict, Any, Optional


class TokenCounter:
    """
    Utility class for counting tokens and estimating costs.
    """

    # Rough token estimation (words * 1.3 for subwords)
    TOKEN_FACTOR = 1.3

    # Cost per 1000 tokens (approximate, update as needed)
    COSTS = {
        "gpt-3.5-turbo": {"input": 0.0015, "output": 0.002},
        "gpt-4": {"input": 0.03, "output": 0.06},
        "claude-3-sonnet": {"input": 0.015, "output": 0.075},
        "gemini-pro": {"input": 0.0005, "output": 0.0015}
    }

    @staticmethod
    def count_tokens(text: str) -> int:
        """
        Estimate token count for text.

        Args:
            text: Input text

        Returns:
            Estimated token count
        """
        if not text:
            return 0

        # Simple word-based estimation
        words = len(text.split())
        return int(words * TokenCounter.TOKEN_FACTOR)

    @staticmethod
    def estimate_cost(model: str,
                     input_tokens: int,
                     output_tokens: int) -> Dict[str, float]:
        """
        Estimate API cost for a call.

        Args:
            model: Model name
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens

        Returns:
            Dict with input_cost, output_cost, total_cost
        """
        if model not in TokenCounter.COSTS:
            # Default costs
            costs = {"input": 0.01, "output": 0.02}
        else:
            costs = TokenCounter.COSTS[model]

        input_cost = (input_tokens / 1000) * costs["input"]
        output_cost = (output_tokens / 1000) * costs["output"]
        total_cost = input_cost + output_cost

        return {
            "input_cost": round(input_cost, 6),
            "output_cost": round(output_cost, 6),
            "total_cost": round(total_cost, 6)
        }

    @staticmethod
    def calculate_savings(original_tokens: int,
                         compressed_tokens: int,
                         model: str) -> Dict[str, Any]:
        """
        Calculate token and cost savings from compression.

        Args:
            original_tokens: Original token count
            compressed_tokens: Compressed token count
            model: Model name for cost calculation

        Returns:
            Dict with savings metrics
        """
        token_saving = original_tokens - compressed_tokens
        compression_ratio = compressed_tokens / original_tokens if original_tokens > 0 else 1.0

        # Estimate cost savings (assuming same output tokens)
        original_cost = TokenCounter.estimate_cost(model, original_tokens, 100)["total_cost"]
        compressed_cost = TokenCounter.estimate_cost(model, compressed_tokens, 100)["total_cost"]
        cost_saving = original_cost - compressed_cost

        return {
            "token_saving": token_saving,
            "compression_ratio": round(compression_ratio, 3),
            "cost_saving_percent": round((token_saving / original_tokens) * 100, 2) if original_tokens > 0 else 0,
            "estimated_cost_saving": round(cost_saving, 6)
        }


def clean_text(text: str) -> str:
    """
    Clean text for better compression.

    Args:
        text: Input text

    Returns:
        Cleaned text
    """
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text.strip())

    # Remove common filler phrases
    fillers = [
        r'\bplease\b', r'\bcould you\b', r'\bi would like\b',
        r'\bcan you\b', r'\bwould you mind\b'
    ]

    for filler in fillers:
        text = re.sub(filler, '', text, flags=re.IGNORECASE)

    return text.strip()
