"""Backend factory and auto-detection logic."""
from __future__ import annotations

import os
import shutil

from .base import Backend
from .api_backend import ApiBackend
from .claude_backend import ClaudeBackend
from .codex_backend import CodexBackend
from .gemini_backend import GeminiBackend

_REGISTRY: dict[str, type[Backend]] = {
    "api": ApiBackend,
    "claude": ClaudeBackend,
    "codex": CodexBackend,
    "gemini": GeminiBackend,
}


def auto_detect_backend() -> str:
    """
    Detect which backend to use. Priority:
    1. VANTAGE_BACKEND env var
    2. ANTHROPIC_API_KEY → "api"
    3. `claude` binary → "claude"
    4. `codex` binary → "codex"
    5. `gemini` binary → "gemini"
    6. Raise RuntimeError
    """
    env = os.environ.get("VANTAGE_BACKEND", "").strip()
    if env and env in _REGISTRY:
        return env

    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return "api"

    for name in ("claude", "codex", "gemini"):
        if shutil.which(name):
            return name

    raise RuntimeError(
        "No backend found. Set ANTHROPIC_API_KEY, install claude/codex/gemini CLI, "
        "or set VANTAGE_BACKEND env var."
    )


def create_backend(name: str, **kwargs) -> Backend:
    """Instantiate a backend by name."""
    if name not in _REGISTRY:
        raise ValueError(f"Unknown backend {name!r}. Available: {list(_REGISTRY)}")
    return _REGISTRY[name](**kwargs)
