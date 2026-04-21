"""
api_client.py — Anthropic API client with streaming + tool-use loop.

The core execution loop:
1. Send prompt → Anthropic API (streaming)
2. Stream text deltas to terminal in real-time
3. When tool_use block received → check permissions → execute → send result back
4. Repeat until Claude sends end_turn (no more tool calls)
"""
from __future__ import annotations

import json
import os
import time as _time
from typing import Any

import anthropic

from .cost_tracker import SessionCost
from .permissions import PermissionManager
from .renderer import (
    render_error,
    render_permission_denied,
    render_text_complete,
    render_text_delta,
    render_tool_result,
    render_tool_use_start,
    render_thinking,
)
from .anomaly import check_cost_anomaly
from .optimizer import optimize_prompt, count_tokens
from .tools import TOOL_DEFINITIONS, TOOL_MAP, execute_tool

DEFAULT_MODEL = "claude-sonnet-4-6"


def _prompt_for_api_key() -> str:
    """Interactively ask the user for their Anthropic API key and save it."""
    import shutil
    import sys
    if not sys.stdin.isatty():
        return ""
    has_claude_cli = shutil.which("claude") is not None
    if has_claude_cli:
        note = "Tip: you have the claude CLI installed. Use --backend claude to run without an API key (uses your Claude Max subscription)."
    else:
        note = "Note: A Claude.ai web subscription does NOT grant API access. You need a separate key from console.anthropic.com/settings/keys"
    print(
        "\n"
        "No Anthropic API key found.\n"
        f"{note}\n"
        "Get your API key at: https://console.anthropic.com/settings/keys\n"
    )
    try:
        key = input("Paste your API key (or press Enter to skip): ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""
    if not key:
        return ""
    save_path = os.path.expanduser("~/.cohrint-agent/api_key")
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    # Refuse to follow a pre-existing symlink at save_path — otherwise a
    # hostile process that planted a symlink could have the key written
    # to an attacker-controlled location with os.chmod only tightening
    # perms on the target, not the symlink (T-SAFETY.api_key_nofollow).
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(save_path, flags, 0o600)
    except OSError as exc:
        print(f"Refusing to write API key to {save_path}: {exc}\n")
        return ""
    try:
        with os.fdopen(fd, "w") as f:
            f.write(key)
    finally:
        try:
            os.chmod(save_path, 0o600)
        except OSError:
            pass
    print(f"Key saved to {save_path}\n")
    return key
DEFAULT_MAX_TOKENS = 16384
MAX_TURNS = 50  # Safety limit for tool-use loops


class AgentClient:
    """Manages a multi-turn conversation with Anthropic API + local tool execution."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        permissions: PermissionManager | None = None,
        cost: SessionCost | None = None,
        cwd: str | None = None,
        system_prompt: str | None = None,
        optimization: bool = True,
    ):
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            # Try common config locations
            for path in [
                os.path.expanduser("~/.cohrint-agent/api_key"),
                os.path.expanduser("~/.anthropic/api_key"),
                os.path.expanduser("~/.config/anthropic/api_key"),
            ]:
                if os.path.exists(path):
                    api_key = open(path).read().strip()
                    break
        if not api_key:
            api_key = _prompt_for_api_key()
        if not api_key:
            import shutil
            has_claude_cli = shutil.which("claude") is not None
            if has_claude_cli:
                cli_note = "Tip: you have the claude CLI installed. Use --backend claude to run without an API key (uses your Claude Max subscription)."
            else:
                cli_note = "Note: A Claude.ai web subscription does NOT grant API access. You need a separate key from console.anthropic.com/settings/keys"
            raise ValueError(
                "\n"
                "ANTHROPIC_API_KEY not set.\n\n"
                f"{cli_note}\n\n"
                "To fix this, either:\n"
                "  1. export ANTHROPIC_API_KEY=sk-ant-...\n"
                "  2. save your key to ~/.cohrint-agent/api_key\n"
                "  3. run: cohrint-agent --setup\n"
                "  4. use --backend claude if you have the claude CLI installed"
            )
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens
        self.permissions = permissions or PermissionManager()
        self.cost = cost or SessionCost(model=model)
        self.cwd = cwd or os.getcwd()
        self.messages: list[dict[str, Any]] = []
        self.system_prompt = system_prompt or self._default_system()
        self.optimization = optimization
        self._available_tools = self._build_tool_list()

    def _default_system(self) -> str:
        return (
            "You are an expert coding assistant. You have access to tools for "
            "reading, writing, and editing files, running shell commands, and "
            "searching codebases. Use tools when needed to accomplish tasks. "
            f"Working directory: {self.cwd}"
        )

    def _build_tool_list(self) -> list[dict[str, Any]]:
        """Return tool definitions for all known tools."""
        return TOOL_DEFINITIONS

    def send(self, user_prompt: str, no_optimize: bool = False) -> str:
        """
        Send a user prompt. Handles the full tool-use loop:
        prompt → stream response → execute tools → send results → repeat.

        Returns the final text response.
        """
        # Optimize prompt (skip for short/structured input)
        final_prompt = user_prompt
        if not no_optimize and self.optimization and len(user_prompt) > 20:
            result = optimize_prompt(user_prompt)
            if result.saved_tokens > 0:
                final_prompt = result.optimized
                # Aggregate session-wide savings for /summary (T-SUMMARY.1).
                from .pricing import MODEL_PRICES
                _pricing = MODEL_PRICES.get(self.cost.model, {"input": 3.0})
                saved_usd = (result.saved_tokens / 1_000_000) * _pricing.get("input", 3.0)
                self.cost.record_optimization(result.saved_tokens, saved_usd)
                from rich.console import Console
                Console().print(
                    f"  [dim]Optimized: {result.original_tokens} → {result.optimized_tokens} tokens "
                    f"(saved {result.saved_tokens}, -{result.saved_percent}%)[/dim]"
                )

        self.messages.append({"role": "user", "content": final_prompt})
        # Evict oldest turns once history grows past MAX_MESSAGE_HISTORY so
        # long REPL sessions cannot OOM the process (T-BOUNDS.messages).
        # Multi-turn semantics are preserved by dropping in role-pairs.
        self._trim_history()
        self.cost.record_prompt()

        final_text = ""
        turns = 0

        while turns < MAX_TURNS:
            turns += 1
            response_text, tool_calls, stop_reason = self._stream_response()
            final_text = response_text

            if not tool_calls or stop_reason == "end_turn":
                break

            # Process tool calls
            tool_results = self._process_tool_calls(tool_calls)

            # Send tool results back to the API
            # Build assistant message with the content blocks from this turn
            assistant_content = self._build_assistant_content(response_text, tool_calls)
            self.messages.append({"role": "assistant", "content": assistant_content})
            self.messages.append({"role": "user", "content": tool_results})

        return final_text

    def _stream_response(self) -> tuple[str, list[dict], str]:
        """
        Stream a response from the API.
        Returns (text, tool_calls, stop_reason).
        """
        text_parts: list[str] = []
        tool_calls: list[dict] = []
        current_tool: dict[str, Any] | None = None
        current_tool_input_json = ""
        stop_reason = "end_turn"

        with self._send_with_retry(
            model=self.model,
            max_tokens=self.max_tokens,
            system=self.system_prompt,
            messages=self.messages,
            tools=self._available_tools,
        ) as stream:
            for event in stream:
                event_type = event.type

                if event_type == "content_block_start":
                    block = event.content_block
                    if block.type == "tool_use":
                        current_tool = {
                            "id": block.id,
                            "name": block.name,
                            "input": {},
                        }
                        current_tool_input_json = ""
                    elif block.type == "thinking":
                        pass  # Will accumulate in deltas

                elif event_type == "content_block_delta":
                    delta = event.delta
                    if delta.type == "text_delta":
                        text_parts.append(delta.text)
                        render_text_delta(delta.text)
                    elif delta.type == "input_json_delta":
                        if current_tool is not None:
                            current_tool_input_json += delta.partial_json
                    elif delta.type == "thinking_delta":
                        pass  # Could render thinking here

                elif event_type == "content_block_stop":
                    if current_tool is not None:
                        # Parse accumulated JSON
                        try:
                            current_tool["input"] = json.loads(current_tool_input_json) if current_tool_input_json else {}
                        except json.JSONDecodeError:
                            current_tool["input"] = {}
                        tool_calls.append(current_tool)
                        current_tool = None
                        current_tool_input_json = ""

                elif event_type == "message_stop":
                    pass

                elif event_type == "message_delta":
                    if hasattr(event, "delta") and hasattr(event.delta, "stop_reason"):
                        stop_reason = event.delta.stop_reason or "end_turn"

            # Get usage from the final message (single source of truth)
            final_msg = stream.get_final_message()
            if final_msg:
                if hasattr(final_msg, "usage"):
                    self.cost.record_usage(final_msg.usage)
                stop_reason = final_msg.stop_reason or stop_reason

        full_text = "".join(text_parts)
        if full_text:
            render_text_complete(full_text)

        return full_text, tool_calls, stop_reason

    def _process_tool_calls(self, tool_calls: list[dict]) -> list[dict]:
        """Execute tool calls with permission checks. Returns tool_result content blocks."""
        results: list[dict] = []

        for tc in tool_calls:
            tool_name = tc["name"]
            tool_input = tc["input"]
            tool_id = tc["id"]

            render_tool_use_start(tool_name, tool_input)

            # Check permission
            if not self.permissions.check_permission(tool_name, tool_input):
                render_permission_denied(tool_name)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": f"[Permission denied] The user did not approve use of {tool_name}. Please try a different approach or ask the user to approve this tool with /allow {tool_name}.",
                    "is_error": True,
                })
                continue

            # Execute the tool
            try:
                output = execute_tool(tool_name, tool_input, self.cwd)
                is_error = False
            except Exception as e:
                # str(e) on FileNotFoundError / PermissionError includes
                # the full filesystem path, which then flows into the
                # session-stored tool_result and back into the LLM's
                # context. Return only the exception type name to keep
                # user paths private (T-PRIVACY.tool_exception_path).
                output = f"Tool execution error: {type(e).__name__}"
                is_error = True

            render_tool_result(tool_name, output, is_error=is_error)

            results.append({
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": output,
                "is_error": is_error,
            })

        return results

    def _build_assistant_content(
        self, text: str, tool_calls: list[dict]
    ) -> list[dict]:
        """Build the assistant message content blocks for the conversation history."""
        content: list[dict] = []
        if text:
            content.append({"type": "text", "text": text})
        for tc in tool_calls:
            content.append({
                "type": "tool_use",
                "id": tc["id"],
                "name": tc["name"],
                "input": tc["input"],
            })
        return content

    def _send_with_retry(self, *args, max_retries: int = 3, **kwargs):
        """Send with exponential backoff on RateLimitError."""
        for attempt in range(max_retries + 1):
            try:
                return self.client.messages.stream(*args, **kwargs)
            except anthropic.RateLimitError:
                if attempt == max_retries:
                    raise
                wait = (2 ** attempt) + 0.5  # 0.5, 1.5, 4.5 seconds
                _time.sleep(wait)
            except anthropic.APIStatusError as e:
                if e.status_code == 529 and attempt < max_retries:  # overloaded
                    _time.sleep(2 ** attempt)
                    continue
                raise

    def clear_history(self) -> None:
        """Reset conversation history."""
        self.messages = []

    # Max turns retained in-memory across a REPL session. Each "turn" is a
    # user→assistant→tool_result triplet; at ~8 KiB per turn this caps the
    # accumulator at ~1.6 MiB of heap for the messages list. Oldest turns
    # are evicted first; the most recent prompt is always kept.
    MAX_MESSAGE_HISTORY = 200

    def _trim_history(self) -> None:
        excess = len(self.messages) - self.MAX_MESSAGE_HISTORY
        if excess <= 0:
            return
        # Anthropic requires the first message to be from user — always
        # drop complete pairs from the front to preserve role alternation.
        drop = excess if excess % 2 == 0 else excess + 1
        self.messages = self.messages[drop:]
