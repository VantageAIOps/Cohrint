"""Tests for Backend implementations, auto-detect logic, and ToolRegistry."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from vantage_agent.backends import create_backend, auto_detect_backend
from vantage_agent.backends.base import BackendCapabilities, BackendResult


def test_auto_detect_api_key_returns_api():
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test", "VANTAGE_BACKEND": ""}):
        name = auto_detect_backend()
    assert name == "api"


def test_auto_detect_claude_binary_returns_claude():
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "", "VANTAGE_BACKEND": ""}):
        with patch("shutil.which", side_effect=lambda b: "/usr/bin/claude" if b == "claude" else None):
            name = auto_detect_backend()
    assert name == "claude"


def test_auto_detect_no_binaries_raises_error():
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "", "VANTAGE_BACKEND": ""}):
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="No backend found"):
                auto_detect_backend()


def test_explicit_env_var_overrides_autodetect():
    with patch.dict(os.environ, {"VANTAGE_BACKEND": "gemini", "ANTHROPIC_API_KEY": "sk-test"}):
        name = auto_detect_backend()
    assert name == "gemini"


def test_backend_capabilities_declared():
    """Every backend must declare all 4 capability fields."""
    for name in ("api", "claude", "codex", "gemini"):
        backend = create_backend(name)
        caps = backend.capabilities
        assert isinstance(caps.supports_process, bool)
        assert caps.token_count in ("exact", "estimated", "free_tier")
        assert caps.tool_format in ("anthropic", "openai", "google")


def test_api_backend_not_supports_process():
    backend = create_backend("api")
    assert backend.capabilities.supports_process is False
    assert backend.capabilities.token_count == "exact"


def test_cli_backends_support_process():
    # claude backend was rewritten to stream-json: supports_process=False, token_count=exact
    claude_backend = create_backend("claude")
    assert claude_backend.capabilities.supports_process is False
    assert claude_backend.capabilities.token_count == "exact"
    # Other CLI backends still use process model
    for name in ("codex", "gemini"):
        backend = create_backend(name)
        assert backend.capabilities.supports_process is True
        assert backend.capabilities.token_count == "estimated"


def test_unknown_backend_raises():
    with pytest.raises(ValueError, match="Unknown backend"):
        create_backend("llama")


def test_tool_registry_translates_anthropic_to_openai():
    from vantage_agent.tool_registry import ToolRegistry
    tools = ToolRegistry.for_format("openai")
    assert len(tools) > 0
    for tool in tools:
        assert "function" in tool, f"OpenAI format missing 'function' key: {tool}"
        assert tool["type"] == "function"


def test_tool_registry_translates_anthropic_to_google():
    from vantage_agent.tool_registry import ToolRegistry
    tools = ToolRegistry.for_format("google")
    assert len(tools) > 0
    for tool in tools:
        assert "name" in tool
        assert "description" in tool


def test_tool_registry_anthropic_passthrough():
    from vantage_agent.tool_registry import ToolRegistry
    from vantage_agent.tools import TOOL_DEFINITIONS
    tools = ToolRegistry.for_format("anthropic")
    assert tools == list(TOOL_DEFINITIONS)
