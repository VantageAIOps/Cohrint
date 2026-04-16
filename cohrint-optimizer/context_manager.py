"""
Context management for conversation history optimization.
"""

import logging
from typing import List, Dict, Any, Optional
from collections import deque

logger = logging.getLogger(__name__)


class ContextManager:
    """
    Manages conversation context to optimize token usage.

    Implements strategies like:
    - Message pruning (remove old messages)
    - Summarization of conversation history
    - Context window management
    """

    def __init__(self,
                 max_tokens: int = 4000,
                 max_messages: int = 50,
                 summary_threshold: int = 20):
        """
        Initialize context manager.

        Args:
            max_tokens: Maximum tokens to keep in context
            max_messages: Maximum number of messages to keep
            summary_threshold: Number of messages before triggering summarization
        """
        self.max_tokens = max_tokens
        self.max_messages = max_messages
        self.summary_threshold = summary_threshold
        self.messages = deque(maxlen=max_messages)
        self.token_counter = None  # Will be set by LLMWrapper

    def add_message(self, role: str, content: str):
        """
        Add a message to the conversation context.

        Args:
            role: Message role ('user', 'assistant', 'system')
            content: Message content
        """
        self.messages.append({
            "role": role,
            "content": content,
            "tokens": len(content.split()) if self.token_counter else 0
        })

    def get_context(self, current_prompt: str = "") -> List[Dict[str, str]]:
        """
        Get optimized context for the current conversation.

        Args:
            current_prompt: Current prompt being processed

        Returns:
            List of messages in context
        """
        if len(self.messages) <= self.summary_threshold:
            return list(self.messages)

        # Implement summarization strategy
        return self._summarize_context()

    def _summarize_context(self) -> List[Dict[str, str]]:
        """
        Summarize older messages to reduce context size.
        """
        # Simple strategy: keep recent messages, summarize older ones
        recent_count = min(10, len(self.messages) // 2)
        recent_messages = list(self.messages)[-recent_count:]

        # Create a summary of older messages
        older_messages = list(self.messages)[:-recent_count]
        if older_messages:
            summary_content = self._create_summary(older_messages)
            summary_message = {
                "role": "system",
                "content": f"Previous conversation summary: {summary_content}",
                "tokens": len(summary_content.split())
            }
            return [summary_message] + recent_messages

        return recent_messages

    def _create_summary(self, messages: List[Dict[str, Any]]) -> str:
        """
        Create a summary of conversation messages.
        """
        # Basic summarization - in production, use LLM for better summaries
        topics = []
        user_queries = []
        assistant_responses = []

        for msg in messages:
            if msg["role"] == "user":
                user_queries.append(msg["content"][:100] + "..." if len(msg["content"]) > 100 else msg["content"])
            elif msg["role"] == "assistant":
                assistant_responses.append(msg["content"][:100] + "..." if len(msg["content"]) > 100 else msg["content"])

        summary = f"Conversation had {len(user_queries)} user queries and {len(assistant_responses)} responses. "
        if user_queries:
            summary += f"Key topics: {'; '.join(user_queries[:3])}"

        return summary

    def clear_context(self):
        """Clear all conversation context."""
        self.messages.clear()

    def get_stats(self) -> Dict[str, Any]:
        """Get context statistics."""
        total_tokens = sum(msg.get("tokens", 0) for msg in self.messages)
        return {
            "total_messages": len(self.messages),
            "total_tokens": total_tokens,
            "max_tokens": self.max_tokens,
            "max_messages": self.max_messages
        }
