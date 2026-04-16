"""
Vantage AI Optimizer - Prompt compression and context management utilities.

Provides tools to compress prompts, manage conversation context, and reduce
token usage while maintaining response quality for LLM integrations.
"""

__version__ = "0.1.0"

from .compressor import PromptCompressor, SimpleCompressor
from .context_manager import ContextManager
from .utils import TokenCounter, clean_text

__all__ = [
    "PromptCompressor",
    "SimpleCompressor",
    "ContextManager",
    "TokenCounter",
    "clean_text",
]
