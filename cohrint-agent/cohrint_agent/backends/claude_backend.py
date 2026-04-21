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
from ..process_safety import clamp_argv, safe_child_env
from ..pricing import calculate_cost
from ..sanitize import scrub_for_terminal, scrub_token

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
        from ..process_safety import safe_config_dir
        self._config_dir = config_dir or safe_config_dir()
        self._permission_server = permission_server
        self._claude_session_id: str | None = None
        self._settings_path: Path | None = None

    def _build_command(self, prompt: str, cwd: str) -> list[str]:
        # clamp_argv blocks the local-DoS case where a 1 MiB prompt would
        # exceed Linux MAX_ARG_STRLEN (128 KiB) and make execve refuse to
        # spawn the agent. Over-long prompts are truncated, not rejected —
        # the tail loss is preferable to a silent failure.
        # Pin the claude binary to an absolute path resolved once at
        # init time so a later PATH flip or a writable ~/.local/bin
        # trojan can't win (T-SAFETY.backend_path_pin, scan 22).
        from ..process_safety import resolve_backend_binary
        claude_bin = resolve_backend_binary("claude") or "claude"
        cmd = [
            claude_bin, "-p", clamp_argv(prompt),
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
        """Install hook script and build merged settings file for this session.

        Settings and socket live under ``<config_dir>/run/`` (mode 0700) so a
        local attacker can't plant a symlink there to hijack the file write or
        socket bind. Previously these lived in ``/tmp/cohrint-<PID>-*`` which
        is both guessable and world-writable (T-SAFETY.tmp_path).
        """
        from ..permission_server import build_session_settings_file, install_hook_script
        install_hook_script(self._config_dir)
        run_dir = self._config_dir / "run"
        run_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.chmod(run_dir, 0o700)
        except OSError:
            pass
        socket_path = str(run_dir / f"perm-{pid}.sock")
        self._settings_path = run_dir / f"{pid}-settings.json"
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
        # Bound the stdout queue so a run-away child (prompt-injected flood
        # of base64 output) cannot grow memory in the reader thread before
        # main-thread consumption catches up (T-BOUNDS.stdout_queue).
        stdout_queue: queue.Queue[bytes | None] = queue.Queue(maxsize=4096)
        perm_req_queue = (
            self._permission_server.perm_request_queue
            if self._permission_server else None
        )
        perm_resp_queue = (
            self._permission_server.perm_response_queue
            if self._permission_server else None
        )

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=cwd,
            env=safe_child_env(),
        )

        # Thread A: read stdout into queue
        def _read_stdout() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                try:
                    # Drop lines rather than block indefinitely when the
                    # queue fills — main thread has terminal I/O priority.
                    stdout_queue.put(line, timeout=1.0)
                except queue.Full:
                    continue
            try:
                stdout_queue.put(None, timeout=1.0)  # sentinel
            except queue.Full:
                pass

        state: dict[str, Any] = {
            "text": "",
            "result": None,
            "rate_limit_resets_at": None,
        }
        reader: threading.Thread | None = None
        # Wrap the full read/parse loop so any exception (thread start
        # failure, KeyboardInterrupt, parse bug) still reaps the child
        # subprocess — otherwise a crashed main thread leaves an orphan
        # that eventually hangs on a full pipe buffer (T-CONCUR.subproc).
        try:
            reader = threading.Thread(target=_read_stdout, daemon=True)
            reader.start()

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
                    # errors="replace" so a single non-UTF-8 byte on an
                    # earlier line doesn't silently discard the *entire*
                    # stream-json event sequence (the final ``result``
                    # event carries session_id + cost — losing it breaks
                    # --resume on the next turn).
                    event = json.loads(line.decode("utf-8", errors="replace").strip())
                    _parse_stream_event(event, state, render=True)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass

            if reader is not None:
                reader.join()
            proc.wait()
        finally:
            # Belt-and-suspenders cleanup: if we exited the loop via an
            # exception, kill the child so it doesn't outlive us. wait()
            # is idempotent if the normal path already reaped it.
            if proc.poll() is None:
                try:
                    proc.kill()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=2.0)
                except Exception:
                    pass
            # Cleanup temp settings file on every path — leaking these
            # into /tmp across many sessions is a privacy smell.
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

        # Validate session_id before persisting — it will be re-injected as
        # an argv element on the next --resume call. A prompt-injected model
        # response could otherwise smuggle "--other-flag" or a path-traversal
        # string into the subprocess command line (T-SAFETY.session_id_argv).
        from ..session_store import is_valid_session_id
        if session_id and is_valid_session_id(session_id):
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
        # Validate: must be a finite number and within a plausible window
        # (now → now + 1h). Guards against model/MITM-supplied garbage (NaN,
        # negative, seconds-vs-ms confusion) poisoning state or rendering
        # "resets in 277h" to the user (T-SAFETY.resets_at).
        now = datetime.now(timezone.utc).timestamp()
        valid = (
            isinstance(resets_at, (int, float))
            and resets_at == resets_at  # NaN filter
            and now < resets_at < now + 3600
        )
        if valid:
            state["rate_limit_resets_at"] = resets_at
            if render and console:
                secs = max(0, int(resets_at - now))
                mins, s = divmod(secs, 60)
                console.print(
                    f"  [yellow]⏱ Rate limited — resets in {mins}m {s:02d}s[/yellow]"
                )


def _show_permission_prompt(perm_req: dict, console: Any) -> str:
    """Show per-call permission prompt. Called on main thread (owns terminal).

    tool_name / tool_input arrive from the Claude Code hook payload, which
    originates in a model response — the scrub is mandatory (T-SAFETY.12) so
    an injected OSC-52 payload cannot hijack the permission dialog.
    """
    from rich.prompt import Prompt
    tool_name = perm_req.get("tool_name", "?")
    tool_input = perm_req.get("tool_input", {})
    safe_name = scrub_token(tool_name)

    console.print()
    console.print(f"  [yellow bold]⚠ Claude wants to use [white]{safe_name}[/white][/yellow bold]")

    if tool_name == "Bash":
        cmd = scrub_for_terminal(tool_input.get("command", ""), max_len=200)
        console.print(f"    [dim]$[/dim] {cmd}")
    elif tool_name in ("Write", "Edit"):
        console.print(f"    [dim]File:[/dim] {scrub_for_terminal(tool_input.get('file_path', ''))}")
    elif tool_name == "Read":
        console.print(f"    [dim]Read:[/dim] {scrub_for_terminal(tool_input.get('file_path', ''))}")
    else:
        for k, v in list(tool_input.items())[:2]:
            console.print(f"    [dim]{scrub_token(str(k))}:[/dim] {scrub_for_terminal(str(v), max_len=80)}")

    console.print("    [dim][y]es once  [a]lways  [n]o once  [N]ever[/dim]")

    answer = Prompt.ask("  [dim]Allow?[/dim]", choices=["y", "a", "n", "N"], default="y")

    decision_map = {"y": "allow_session", "a": "allow_always", "n": "deny_session", "N": "deny_always"}
    return decision_map.get(answer, "allow_session")


# Keep old name as alias so existing code that imports ClaudeBackend still works
ClaudeBackend = ClaudeCliBackend
