"""
Configuration for the Vantage AI Optimizer module.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class OptimizerConfig:
    """
    Configuration for prompt compression and optimization behavior.

    Attributes:
        enabled: Whether the optimizer is active. When False, prompts pass through unchanged.
        compression_rate: Target compression ratio (0.0-1.0). Lower values mean more aggressive compression.
        min_prompt_tokens: Minimum estimated token count before compression is applied.
                          Prompts shorter than this are skipped to avoid degrading short inputs.
        device: Device for model inference ('cpu' or 'cuda').
    """

    enabled: bool = False
    compression_rate: float = 0.5
    min_prompt_tokens: int = 100
    device: str = "cpu"


# Module-level singleton
_config: Optional[OptimizerConfig] = None


def get_config() -> OptimizerConfig:
    """
    Return the module-level OptimizerConfig singleton, creating it on first access.
    """
    global _config
    if _config is None:
        _config = OptimizerConfig()
    return _config


def set_config(config: OptimizerConfig) -> None:
    """
    Replace the module-level OptimizerConfig singleton.

    Args:
        config: New configuration to use.
    """
    global _config
    _config = config
