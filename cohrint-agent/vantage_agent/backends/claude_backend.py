"""
claude_backend.py — Claude Code CLI backend via stream-json subprocess.

Replaces the broken single-shot subprocess approach with:
  - claude -p <prompt> --output-format stream-json --verbose
  - --permission-mode bypassPermissions (hooks still fire — verified)
  - --no-session-persistence (prevents CC double-saving; hooks still fire)
  - --resume <session_id> for native conversation history
  - PreToolUse hook ↔ PermissionServer for per-call user approval

Cost is extracted from the `result` event (exact tokens from Claude Code's
usage field). Labelled as API-equivalent since Max users pay $0 actual.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .base import Backend, BackendCapabilities, BackendResult
from ..pricing import calculate_cost

if TYPE_CHECKING:
    from ..permission_server import PermissionServer


class ClaudeCliBackend(Backend):
    name = "claude"
    capabilities = BackendCapabilities(
        supports_process=False,
        supports_streaming=False,
        token_count="exact",
        tool_format="anthropic",
    )

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        config_dir: Path | None = None,
        permission_server: "PermissionServer | None" = None,
    ) -> None:
        self._model = model
        self._config_dir = config_dir or Path(
            os.environ.get("VANTAGE_CONFIG_DIR", Path.home() / ".vantage-agent")
        )
        self._permission_server = permission_server
        self._claude_session_id: str | None = None
        self._settings_path: Path | None = None

    def _build_command(self, prompt: str, cwd: str) -> list[str]:
        cmd = [
            "claude", "-p", prompt,
            "--output-format", "stream-json",
            "--verbose",
            "--permission-mode", "bypassPermissions",
            "--model", self._model,
        ]
        if self._claude_session_id:
            cmd += ["--resume", self._claude_session_id]
        if self._settings_path and self._settings_path.exists():
            cmd += ["--settings", str(self._settings_path)]
        return cmd

    def prepare_session_settings(self, pid: int) -> None:
        """Install hook script and build merged settings file for this session."""
        from ..permission_server import build_session_settings_file, install_hook_script
        install_hook_script(self._config_dir)
        socket_path = f"/tmp/vantage-perm-{pid}.sock"
        self._settings_path = Path(f"/tmp/vantage-{pid}-settings.json")
        build_session_settings_file(
            socket_path=socket_path,
            output_path=self._settings_path,
            config_dir=self._config_dir,
        )

    def send(self, prompt: str, history: list[dict], cwd: str) -> BackendResult:
        """
        Spawn claude subprocess, parse stream-json events.
        History is handled natively via --resume session_id.
        Blocks until claude exits, streaming text to terminal in real-time.
        """
        from rich.console import Console
        console = Console()

        cmd = self._build_command(prompt, cwd)
        stdout_queue: queue.Queue[bytes | None] = queue.Queue()
        perm_req_queue = (
            self._permission_server.perm_request_queue
            if self._permission_server else None
        )
        perm_resp_queue = (
            self._permission_server.perm_response_queue
            if self._permission_server else None
        )

        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=cwd
        )

        # Thread A: read stdout into queue
        def _read_stdout() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                stdout_queue.put(line)
            stdout_queue.put(None)  # sentinel

        reader = threading.Thread(target=_read_stdout, daemon=True)
        reader.start()

        state: dict[str, Any] = {
            "text": "",
            "result": None,
            "rate_limit_resets_at": None,
        }

        # Event loop: main thread owns terminal I/O
        while True:
            # Check for permission requests (when hook fires, subprocess is paused)
            if perm_req_queue is not None:
                try:
                    perm_req = perm_req_queue.get_nowait()
                    decision = _show_permission_prompt(perm_req, console)
                    assert perm_resp_queue is not None
                    perm_resp_queue.put(decision)
                except queue.Empty:
                    pass

            # Read next stdout line
            try:
                line = stdout_queue.get(timeout=0.05)
            except queue.Empty:
                continue

            if line is None:
                break

            try:
                event = json.loads(line.decode().strip())
                _parse_stream_event(event, state, render=True)
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

        reader.join()
        proc.wait()

        # Cleanup temp settings file
        if self._settings_path and self._settings_path.exists():
            try:
                self._settings_path.unlink()
            except Exception:
                pass

        result = state.get("result") or {}
        input_tokens = result.get("input_tokens", 0)
        output_tokens = result.get("output_tokens", 0)
        cost_usd = result.get("total_cost_usd", 0.0)
        session_id = result.get("session_id")

        if session_id:
            self._claude_session_id = session_id

        return BackendResult(
            output_text=state["text"],
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated=False,  # exact from CC usage field
            model=self._model,
            exit_code=proc.returncode or 0,
            cost_usd=cost_usd,
        )


def _parse_stream_event(event: dict, state: dict, render: bool = True) -> None:
    """
    Mutate state based on one stream-json event line.
    Renders text to terminal when render=True.
    """
    from rich.console import Console
    console = Console() if render else None
    event_type = event.get("type", "")

    if event_type == "assistant":
        msg = event.get("message", {})
        for block in msg.get("content", []):
            if isinstance(block, dict):
                if block.get("type") == "text":
                    text = block.get("text", "")
                    state["text"] += text
                    if render and console and text:
                        console.print(text, end="", highlight=False)
                elif block.get("type") == "tool_use" and render and console:
                    console.print(
                        f"\n  [dim]→ Using {block.get('name', '?')}...[/dim]"
                    )

    elif event_type == "result":
        usage = event.get("usage", {})
        state["result"] = {
            "total_cost_usd": event.get("total_cost_usd", 0.0),
            "session_id": event.get("session_id"),
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "num_turns": event.get("num_turns", 1),
        }
        if render and console:
            cost = event.get("total_cost_usd", 0.0)
            inp = usage.get("input_tokens", 0)
            out = usage.get("output_tokens", 0)
            console.print(
                f"\n  [dim]↳ {inp + out:,} tokens · "
                f"API-equivalent: ${cost:.4f}  "
                f"[Max subscription: $0.00 actual][/dim]"
            )

    elif event_type == "rate_limit_event":
        info = event.get("rate_limit_info", {})
        resets_at = info.get("resetsAt")
        state["rate_limit_resets_at"] = resets_at
        if render and console and resets_at:
            now = datetime.now(timezone.utc).timestamp()
            secs = max(0, int(resets_at - now))
            mins, s = divmod(secs, 60)
            console.print(
                f"  [yellow]⏱ Rate limited — resets in {mins}m {s:02d}s[/yellow]"
            )


def _show_permission_prompt(perm_req: dict, console: Any) -> str:
    """Show per-call permission prompt. Called on main thread (owns terminal)."""
    from rich.prompt import Prompt
    tool_name = perm_req.get("tool_name", "?")
    tool_input = perm_req.get("tool_input", {})

    console.print()
    console.print(f"  [yellow bold]⚠ Claude wants to use [white]{tool_name}[/white][/yellow bold]")

    if tool_name == "Bash":
        console.print(f"    [dim]$[/dim] {tool_input.get('command', '')[:200]}")
    elif tool_name in ("Write", "Edit"):
        console.print(f"    [dim]File:[/dim] {tool_input.get('file_path', '')}")
    elif tool_name == "Read":
        console.print(f"    [dim]Read:[/dim] {tool_input.get('file_path', '')}")
    else:
        for k, v in list(tool_input.items())[:2]:
            console.print(f"    [dim]{k}:[/dim] {str(v)[:80]}")

    console.print("    [dim][y]es once  [a]lways  [n]o once  [N]ever[/dim]")

    answer = Prompt.ask("  [dim]Allow?[/dim]", choices=["y", "a", "n", "N"], default="y")

    decision_map = {"y": "allow_session", "a": "allow_always", "n": "deny_session", "N": "deny_always"}
    return decision_map.get(answer, "allow_session")


# Keep old name as alias so existing code that imports ClaudeBackend still works
ClaudeBackend = ClaudeCliBackend
