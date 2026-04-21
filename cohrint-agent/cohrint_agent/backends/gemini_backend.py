"""Gemini CLI backend — routes through `gemini -p` subprocess."""
from __future__ import annotations

import shutil
import subprocess

from .base import Backend, BackendCapabilities, BackendResult, AgentProcess
from ..pricing import calculate_cost
from ..process_safety import clamp_argv, safe_child_env

_CHARS_PER_TOKEN = 4


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


class GeminiBackend(Backend):
    name = "gemini"
    capabilities = BackendCapabilities(
        supports_process=True,
        supports_streaming=False,
        token_count="estimated",
        tool_format="google",
    )

    def __init__(self, model: str = "gemini-2.0-flash") -> None:
        self._model = model

    def send(self, prompt: str, history: list[dict], cwd: str) -> BackendResult:
        context = "\n".join(f"{m['role'].upper()}: {m['text']}" for m in history)
        full_prompt = clamp_argv(f"{context}\nUSER: {prompt}" if context else prompt)

        # Dash-leading prompt → route via stdin so argparse can't treat it
        # as a flag (T-SAFETY.argv_dash_injection).
        argv_unsafe = full_prompt.startswith("-")
        # text=False + manual decode for utf-8 errors="replace" resilience
        # (T-SAFETY.subproc_utf8_replace).
        result = subprocess.run(
            ["gemini"] if argv_unsafe else ["gemini", "-p", full_prompt],
            input=full_prompt.encode("utf-8") if argv_unsafe else None,
            capture_output=True,
            cwd=cwd,
            timeout=120,
            env=safe_child_env(),
        )
        stdout_s = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
        stderr_s = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
        output = stdout_s.strip()

        if result.returncode != 0:
            err_snip = stderr_s.strip()[:400] or "(no stderr)"
            output = (
                f"[gemini exited {result.returncode}] {err_snip}"
                if not output
                else f"{output}\n\n[gemini exited {result.returncode}] {err_snip}"
            )

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
        if not shutil.which("gemini"):
            return None
        proc = subprocess.Popen(
            ["gemini"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=safe_child_env(),
        )
        return AgentProcess(proc)
