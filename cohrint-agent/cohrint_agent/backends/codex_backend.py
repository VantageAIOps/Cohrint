"""Codex CLI backend — routes through `codex -p` subprocess."""
from __future__ import annotations

import shutil
import subprocess

from .base import Backend, BackendCapabilities, BackendResult, AgentProcess
from ..pricing import calculate_cost
from ..process_safety import clamp_argv, safe_child_env

_CHARS_PER_TOKEN = 4


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


class CodexBackend(Backend):
    name = "codex"
    capabilities = BackendCapabilities(
        supports_process=True,
        supports_streaming=False,
        token_count="estimated",
        tool_format="openai",
    )

    def __init__(self, model: str = "gpt-4o") -> None:
        self._model = model

    def send(self, prompt: str, history: list[dict], cwd: str) -> BackendResult:
        context = "\n".join(f"{m['role'].upper()}: {m['text']}" for m in history)
        full_prompt = clamp_argv(f"{context}\nUSER: {prompt}" if context else prompt)

        # A prompt beginning with "-" can be parsed as a flag by the child
        # CLI's argparse. Route through stdin instead so user input is never
        # interpreted as an option (T-SAFETY.argv_dash_injection).
        argv_unsafe = full_prompt.startswith("-")
        # text=False + manual decode: `text=True` uses locale encoding and
        # raises UnicodeDecodeError on a bad byte, crashing the turn
        # (T-SAFETY.subproc_utf8_replace).
        result = subprocess.run(
            ["codex"] if argv_unsafe else ["codex", "-p", full_prompt],
            input=full_prompt.encode("utf-8") if argv_unsafe else None,
            capture_output=True,
            cwd=cwd,
            timeout=120,
            env=safe_child_env(),
        )
        stdout_s = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
        stderr_s = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
        output = stdout_s.strip()

        # Surface non-zero exit codes — otherwise an auth failure or rate
        # limit lands silently in stderr and the user sees an empty turn
        # (T-SAFETY.exit_code_surfaced).
        if result.returncode != 0:
            err_snip = stderr_s.strip()[:400] or "(no stderr)"
            output = (
                f"[codex exited {result.returncode}] {err_snip}"
                if not output
                else f"{output}\n\n[codex exited {result.returncode}] {err_snip}"
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
        if not shutil.which("codex"):
            return None
        proc = subprocess.Popen(
            ["codex"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=safe_child_env(),
        )
        return AgentProcess(proc)
