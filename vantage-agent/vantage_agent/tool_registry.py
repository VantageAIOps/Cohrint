"""
tool_registry.py — Translate Anthropic tool definitions to OpenAI / Google format.

Anthropic format (source of truth) lives in tools.py.
"""
from __future__ import annotations

from typing import Literal

from .tools import TOOL_DEFINITIONS  # Anthropic-format list[dict]


def _to_openai(tool: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
        },
    }


def _to_google(tool: dict) -> dict:
    return {
        "name": tool["name"],
        "description": tool.get("description", ""),
        "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
    }


class ToolRegistry:
    @staticmethod
    def for_format(fmt: Literal["anthropic", "openai", "google"]) -> list[dict]:
        """Return tool definitions in the requested format."""
        if fmt == "anthropic":
            return list(TOOL_DEFINITIONS)
        if fmt == "openai":
            return [_to_openai(t) for t in TOOL_DEFINITIONS]
        if fmt == "google":
            return [_to_google(t) for t in TOOL_DEFINITIONS]
        raise ValueError(f"Unknown tool format: {fmt!r}")
