"""
Prompt compression utilities using LLMLingua and other techniques.
"""

import logging
from typing import Dict, Any, Optional, Union

logger = logging.getLogger(__name__)


class PromptCompressor:
    """
    Compresses prompts to reduce token consumption while preserving meaning.

    Uses LLMLingua for advanced compression with configurable rates.
    Falls back to simple compression if LLMLingua is not available.
    """

    def __init__(self,
                 model_name: str = "microsoft/DialoGPT-small",
                 device: str = "cpu",
                 compression_rate: float = 0.5):
        """
        Initialize the prompt compressor.

        Args:
            model_name: Model to use for compression (if LLMLingua available)
            device: Device to run compression on ('cpu' or 'cuda')
            compression_rate: Target compression rate (0.0-1.0)
        """
        self.compression_rate = compression_rate
        self.model_name = model_name
        self.device = device
        self._compressor = None
        self._llmlingua_available = self._check_llmlingua()

    def _check_llmlingua(self) -> bool:
        """Check if LLMLingua is available."""
        try:
            import llmlingua
            return True
        except ImportError:
            return False

    def _get_compressor(self):
        """Lazy initialization of LLMLingua compressor."""
        if self._compressor is None and self._llmlingua_available:
            try:
                from llmlingua import PromptCompressor as LLMLinguaCompressor
                self._compressor = LLMLinguaCompressor(
                    model_name=self.model_name
                    # device parameter not supported in current version
                )
            except Exception as e:
                logger.warning(f"Failed to initialize LLMLingua compressor: {e}")
                self._llmlingua_available = False
        return self._compressor

    def compress(self,
                prompt: str,
                rate: Optional[float] = None,
                instruction: str = "",
                **kwargs) -> Dict[str, Any]:
        """
        Compress a prompt to reduce token count.

        Args:
            prompt: The prompt to compress
            rate: Compression rate override (0.0-1.0)
            instruction: Optional instruction for compression
            **kwargs: Additional arguments for compressor

        Returns:
            Dict with compressed_prompt, original_tokens, compressed_tokens, ratio
        """
        compressor = self._get_compressor()
        if compressor:
            return self._compress_with_llmlingua(compressor, prompt, rate, instruction, **kwargs)
        else:
            return SimpleCompressor.compress(prompt)


    def _compress_with_llmlingua(self,
                                compressor,
                                prompt: str,
                                rate: Optional[float] = None,
                                instruction: str = "",
                                **kwargs) -> Dict[str, Any]:
        """Compress using LLMLingua."""
        compression_rate = rate or self.compression_rate

        try:
            compressed = compressor.compress_prompt(
                prompt,
                rate=compression_rate,
                instruction=instruction,
                **kwargs
            )

            original_tokens = len(prompt.split())
            compressed_tokens = len(compressed["compressed_prompt"].split())

            return {
                "compressed_prompt": compressed["compressed_prompt"],
                "original_tokens": original_tokens,
                "compressed_tokens": compressed_tokens,
                "ratio": compressed_tokens / original_tokens if original_tokens > 0 else 1.0,
                "saving": original_tokens - compressed_tokens
            }
        except Exception as e:
            logger.error(f"LLMLingua compression failed: {e}")
            return SimpleCompressor.compress(prompt)


class SimpleCompressor:
    """
    Simple compression using basic text processing techniques.
    Always available as fallback.
    """

    @staticmethod
    def compress(prompt: str) -> Dict[str, Any]:
        """
        Simple compression: remove extra whitespace, redundant phrases.
        """
        # Basic cleaning
        compressed = ' '.join(prompt.split())  # Remove extra whitespace

        # Remove common redundant phrases (basic example)
        redundancies = [
            "Please", "Could you", "I would like you to",
            "Can you", "Would you mind", "Let me know if"
        ]

        for phrase in redundancies:
            compressed = compressed.replace(phrase, "")

        original_tokens = len(prompt.split())
        compressed_tokens = len(compressed.split())

        return {
            "compressed_prompt": compressed,
            "original_tokens": original_tokens,
            "compressed_tokens": compressed_tokens,
            "ratio": compressed_tokens / original_tokens if original_tokens > 0 else 1.0,
            "saving": original_tokens - compressed_tokens
        }
