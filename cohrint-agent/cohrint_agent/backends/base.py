"""Backend ABC + shared data structures."""
from __future__ import annotations

import select
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal


@dataclass
class BackendCapabilities:
    supports_process: bool
    supports_streaming: bool
    token_count: Literal["exact", "estimated", "free_tier"]
    tool_format: Literal["anthropic", "openai", "google"]


@dataclass
class BackendResult:
    output_text: str
    input_tokens: int
    output_tokens: int
    estimated: bool
    model: str = "unknown"
    exit_code: int = 0
    cost_usd: float = 0.0
    cache_read_tokens: int = 0


class AgentProcess:
    """Wraps a persistent subprocess for a CLI backend."""

    def __init__(self, proc) -> None:
        self._proc = proc

    def is_alive(self) -> bool:
        return self._proc.poll() is None

    def ping(self, timeout_s: float = 5.0) -> bool:
        """Returns True if process is alive and stdout is readable."""
        if not self.is_alive():
            return False
        try:
            self._proc.stdin.write(b"\n")
            self._proc.stdin.flush()
            ready, _, _ = select.select([self._proc.stdout], [], [], timeout_s)
            return bool(ready)
        except Exception:
            return False

    def send_stdin(self, text: str) -> str:
        """Write to stdin, collect stdout until idle."""
        # errors="replace" on both ends so an isolated surrogate in the
        # prompt, or a non-UTF-8 byte in a subprocess's CP-1252 output
        # (Windows, or a binary file excerpt), doesn't abort the whole
        # turn and silently lose the result (T-SAFETY.subprocess_encoding).
        self._proc.stdin.write(text.encode("utf-8", errors="replace") + b"\n")
        self._proc.stdin.flush()
        lines = []
        while True:
            ready, _, _ = select.select([self._proc.stdout], [], [], 2.0)
            if not ready:
                break
            line = self._proc.stdout.readline()
            if not line:
                break
            lines.append(line.decode("utf-8", errors="replace"))
        return "".join(lines)

    def terminate(self) -> None:
        try:
            self._proc.terminate()
        except Exception:
            pass


class Backend(ABC):
    name: str
    capabilities: BackendCapabilities

    @abstractmethod
    def send(self, prompt: str, history: list[dict], cwd: str) -> BackendResult:
        """Send prompt with history context."""
        ...

    def start_process(self) -> AgentProcess | None:
        """Start a persistent subprocess. Returns None if not supported."""
        return None
