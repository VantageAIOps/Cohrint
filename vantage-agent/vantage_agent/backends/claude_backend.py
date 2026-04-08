"""Claude Code CLI backend — routes through `claude -p` subprocess."""
from __future__ import annotations

import shutil
import subprocess

from .base import Backend, BackendCapabilities, BackendResult, AgentProcess
from ..pricing import calculate_cost

_CHARS_PER_TOKEN = 4


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


class ClaudeBackend(Backend):
    name = "claude"
    capabilities = BackendCapabilities(
        supports_process=True,
        supports_streaming=False,
        token_count="estimated",
        tool_format="anthropic",
    )

    def __init__(self, model: str = "claude-sonnet-4-6") -> None:
        self._model = model

    def send(self, prompt: str, history: list[dict], cwd: str) -> BackendResult:
        context = "\n".join(f"{m['role'].upper()}: {m['text']}" for m in history)
        full_prompt = f"{context}\nUSER: {prompt}" if context else prompt

        result = subprocess.run(
            ["claude", "-p", full_prompt],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=120,
        )
        output = result.stdout.strip()
        inp = _estimate_tokens(full_prompt)
        out = _estimate_tokens(output)
        cost = calculate_cost(self._model, inp, out)
        return BackendResult(
            output_text=output,
            input_tokens=inp,
            output_tokens=out,
            estimated=True,
            model=self._model,
            exit_code=result.returncode,
            cost_usd=cost,
        )

    def start_process(self) -> AgentProcess | None:
        if not shutil.which("claude"):
            return None
        proc = subprocess.Popen(
            ["claude"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        return AgentProcess(proc)
