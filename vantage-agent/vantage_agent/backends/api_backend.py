"""Direct Anthropic API backend — exact token counts, per-token billing."""
from __future__ import annotations

import anthropic

from .base import Backend, BackendCapabilities, BackendResult
from ..pricing import calculate_cost


class ApiBackend(Backend):
    name = "api"
    capabilities = BackendCapabilities(
        supports_process=False,
        supports_streaming=False,
        token_count="exact",
        tool_format="anthropic",
    )

    def __init__(self, api_key: str = "", model: str = "claude-sonnet-4-6") -> None:
        import os
        self._client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY", ""))
        self._model = model

    def send(self, prompt: str, history: list[dict], cwd: str) -> BackendResult:
        messages = [
            {"role": m["role"], "content": m["text"]}
            for m in history
        ] + [{"role": "user", "content": prompt}]

        response = self._client.messages.create(
            model=self._model,
            max_tokens=8096,
            messages=messages,
        )
        output = "".join(
            block.text for block in response.content if hasattr(block, "text")
        )
        inp = response.usage.input_tokens
        out = response.usage.output_tokens
        cost = calculate_cost(self._model, inp, out)
        return BackendResult(
            output_text=output,
            input_tokens=inp,
            output_tokens=out,
            estimated=False,
            model=self._model,
            cost_usd=cost,
        )
