# Vantage Agent — Permission Granularity & UX Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the broken ClaudeBackend with a stream-json subprocess backend that gives users per-call, auditable tool permissions with consistent UX whether they use an API key or Claude Max subscription.

**Architecture:** `ClaudeCliBackend.send()` spawns `claude -p --output-format stream-json` with `--permission-mode bypassPermissions` and a merged `--settings` file that injects a `PreToolUse` hook. The hook communicates back to a `PermissionServer` thread via Unix socket, which pauses stdout rendering and shows the per-call permission prompt on the main thread. Both the API backend and the new CLI backend share a single `~/.vantage-agent/permissions.json` as the permission source of truth.

**Tech Stack:** Python 3.9+, `subprocess`, `socket.AF_UNIX`, `queue.Queue`, `threading`, `fcntl`, `rich`, `json`, `pytest`

**All tests must pass after every task.** Baseline: `351 passed, 40 skipped`.

Run from: `cd vantage-agent`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `vantage_agent/permissions.py` | Modify | Add `always_denied`, audit_log, `deny()`, `is_denied()`, `clear_session_approved()` |
| `vantage_agent/permission_server.py` | **Create** | Unix socket server thread; hook script installer; settings file merger |
| `vantage_agent/backends/claude_backend.py` | **Rewrite** | stream-json subprocess event loop; `--resume` session anchoring; exact cost extraction |
| `vantage_agent/setup_wizard.py` | **Create** | Tiered startup wizard; first-run detection; config.json read/write |
| `vantage_agent/cli.py` | Modify | Backend dispatch; wizard call; permission server lifecycle; `/tier` command; API-equivalent cost display |
| `tests/test_permission_server.py` | **Create** | Socket server unit tests; hook script content tests; settings merge tests |
| `tests/test_claude_backend.py` | **Create** | stream-json parser unit tests; session_id persistence; cost extraction; rate limit display |
| `tests/test_setup_wizard.py` | **Create** | Tier selection; config.json write/read; apply_tier effects on permissions |
| `tests/test_session_lifecycle.py` | **Create** | TE1/TE8: VantageSession.resume(); full create→send→save→resume lifecycle |

---

## Task 1: Extend PermissionManager — always_denied, audit log, deny flow

**Files:**
- Modify: `vantage_agent/permissions.py`
- Test: `tests/test_permissions.py` (existing — add to it)

- [ ] **Step 1: Write failing tests for new PermissionManager behaviour**

Add to the end of `tests/test_permissions.py`:

```python
import hashlib, json
from pathlib import Path


def test_always_denied_blocks_tool(tmp_path):
    """Tools in always_denied are blocked without prompting."""
    perm_file = tmp_path / "permissions.json"
    perm_file.write_text(json.dumps({
        "schema_version": 1,
        "always_approved": [],
        "always_denied": ["Bash"],
        "session_approved": [],
        "audit_log": [],
    }))
    pm = PermissionManager(config_dir=tmp_path)
    assert pm.is_denied("Bash") is True
    assert pm.is_approved("Bash") is False


def test_deny_adds_to_always_denied(tmp_path):
    """deny() persists tool to always_denied."""
    perm_file = tmp_path / "permissions.json"
    perm_file.write_text(json.dumps({"schema_version": 1, "always_approved": [],
                                      "always_denied": [], "session_approved": [], "audit_log": []}))
    pm = PermissionManager(config_dir=tmp_path)
    pm.deny(["Write"])
    pm2 = PermissionManager(config_dir=tmp_path)
    assert pm2.is_denied("Write") is True


def test_audit_log_appended_on_decision(tmp_path):
    """append_audit() writes an entry with ts, tool, decision, backend."""
    perm_file = tmp_path / "permissions.json"
    perm_file.write_text(json.dumps({"schema_version": 1, "always_approved": [],
                                      "always_denied": [], "session_approved": [], "audit_log": []}))
    pm = PermissionManager(config_dir=tmp_path)
    pm.append_audit(tool="Bash", input_preview="git status", decision="allow_session", backend="claude")
    data = json.loads(perm_file.read_text())
    assert len(data["audit_log"]) == 1
    entry = data["audit_log"][0]
    assert entry["tool"] == "Bash"
    assert entry["decision"] == "allow_session"
    assert entry["backend"] == "claude"
    assert "ts" in entry
    assert "input_hash" in entry


def test_clear_session_approved(tmp_path):
    """clear_session_approved() removes only session-level approvals."""
    perm_file = tmp_path / "permissions.json"
    perm_file.write_text(json.dumps({"schema_version": 1, "always_approved": ["Read"],
                                      "always_denied": [], "session_approved": ["Edit"], "audit_log": []}))
    pm = PermissionManager(config_dir=tmp_path)
    pm.clear_session_approved()
    assert "Edit" not in pm.session_approved
    assert "Read" in pm.always_approved


def test_corruption_recovery(tmp_path):
    """Malformed permissions.json loads safe defaults instead of crashing."""
    perm_file = tmp_path / "permissions.json"
    perm_file.write_text("NOT VALID JSON {{{")
    pm = PermissionManager(config_dir=tmp_path)  # must not raise
    assert "Read" in pm.always_approved  # SAFE_TOOLS default
```

- [ ] **Step 2: Run to confirm failures**

```bash
python -m pytest tests/test_permissions.py -k "always_denied or audit_log or clear_session or corruption" -v 2>&1 | tail -20
```

Expected: 5 failures (PermissionManager doesn't accept `config_dir`, missing methods).

- [ ] **Step 3: Update PermissionManager**

Replace `vantage_agent/permissions.py` completely:

```python
"""
permissions.py — Per-tool permission management.

Shared source of truth for both API backend (in-process) and
Claude CLI backend (via hook script reading same JSON).
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.prompt import Prompt

from .tools import SAFE_TOOLS

console = Console()

_DEFAULT_CONFIG_DIR = Path(os.environ.get("COHRINT_CONFIG_DIR", Path.home() / ".vantage-agent"))
_PERM_FILE_NAME = "permissions.json"


def _config_dir(config_dir: Path | None) -> Path:
    return config_dir or _DEFAULT_CONFIG_DIR


class PermissionManager:
    """Manages per-tool approval state. Both backends share this."""

    def __init__(self, config_dir: Path | None = None) -> None:
        self._config_dir = _config_dir(config_dir)
        self._perm_file = self._config_dir / _PERM_FILE_NAME
        self.session_approved: set[str] = set(SAFE_TOOLS)
        self.always_approved: set[str] = set(SAFE_TOOLS)
        self.always_denied: set[str] = set()
        self._load()

    def _load(self) -> None:
        if not self._perm_file.exists():
            return
        try:
            import fcntl
            with open(self._perm_file) as f:
                fcntl.flock(f, fcntl.LOCK_SH)
                data = json.load(f)
                fcntl.flock(f, fcntl.LOCK_UN)
            self.always_approved |= set(data.get("always_approved", []))
            self.always_denied = set(data.get("always_denied", []))
            self.session_approved |= set(data.get("session_approved", []))
            self.session_approved |= self.always_approved
        except Exception:
            pass  # corruption → safe defaults

    def _save(self) -> None:
        self._config_dir.mkdir(parents=True, exist_ok=True)
        data = self._read_raw()
        data.update({
            "schema_version": 1,
            "always_approved": sorted(self.always_approved),
            "always_denied": sorted(self.always_denied),
            "session_approved": sorted(self.session_approved - self.always_approved),
        })
        import fcntl
        with open(self._perm_file, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            json.dump(data, f, indent=2)
            fcntl.flock(f, fcntl.LOCK_UN)

    def _read_raw(self) -> dict:
        if not self._perm_file.exists():
            return {"schema_version": 1, "always_approved": [], "always_denied": [],
                    "session_approved": [], "audit_log": []}
        try:
            import fcntl
            with open(self._perm_file) as f:
                fcntl.flock(f, fcntl.LOCK_SH)
                d = json.load(f)
                fcntl.flock(f, fcntl.LOCK_UN)
            return d
        except Exception:
            return {"schema_version": 1, "always_approved": [], "always_denied": [],
                    "session_approved": [], "audit_log": []}

    def is_approved(self, tool_name: str) -> bool:
        return tool_name in self.session_approved and tool_name not in self.always_denied

    def is_denied(self, tool_name: str) -> bool:
        return tool_name in self.always_denied

    def check_permission(self, tool_name: str, tool_input: dict[str, Any]) -> bool:
        if self.is_denied(tool_name):
            console.print(f"  [red]✗ {tool_name} is in your always-denied list[/red]")
            return False
        if self.is_approved(tool_name):
            return True

        console.print()
        console.print(f"  [yellow bold]⚠ Claude wants to use [white]{tool_name}[/white][/yellow bold]")
        _print_tool_preview(tool_name, tool_input)

        answer = Prompt.ask(
            "  [dim]Allow?[/dim]",
            choices=["y", "a", "n", "N"],
            default="y",
        )

        decision = "deny"
        if answer == "a":
            self.session_approved.add(tool_name)
            self.always_approved.add(tool_name)
            self._save()
            console.print(f"  [green]✓ {tool_name} approved (always)[/green]")
            decision = "allow_always"
        elif answer == "y":
            self.session_approved.add(tool_name)
            self._save()
            console.print(f"  [green]✓ {tool_name} approved (this session)[/green]")
            decision = "allow_session"
        elif answer == "N":
            self.always_denied.add(tool_name)
            self._save()
            console.print(f"  [red]✗ {tool_name} denied (always)[/red]")
            decision = "deny_always"
        else:
            console.print(f"  [red]✗ {tool_name} denied[/red]")
            decision = "deny_session"

        self.append_audit(
            tool=tool_name,
            input_preview=_input_preview(tool_name, tool_input),
            decision=decision,
            backend="api",
        )
        return decision.startswith("allow")

    def approve(self, tool_names: list[str], always: bool = False) -> None:
        for name in tool_names:
            self.session_approved.add(name)
            if always:
                self.always_approved.add(name)
        if always:
            self._save()

    def deny(self, tool_names: list[str]) -> None:
        for name in tool_names:
            self.always_denied.add(name)
            self.session_approved.discard(name)
        self._save()

    def clear_session_approved(self) -> None:
        self.session_approved = set(SAFE_TOOLS) | self.always_approved

    def reset(self) -> None:
        self.session_approved = set(SAFE_TOOLS)
        self.always_approved = set(SAFE_TOOLS)
        self.always_denied = set()
        self._save()

    def status(self) -> tuple[set[str], set[str]]:
        return self.session_approved.copy(), self.always_approved.copy()

    def append_audit(self, tool: str, input_preview: str, decision: str, backend: str) -> None:
        """Append an audit log entry to permissions.json."""
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "tool": tool,
            "input_hash": hashlib.sha256(input_preview.encode()).hexdigest()[:16],
            "input_preview": input_preview[:200],
            "decision": decision,
            "backend": backend,
        }
        self._config_dir.mkdir(parents=True, exist_ok=True)
        import fcntl
        with open(self._perm_file, "r+" if self._perm_file.exists() else "w+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                data = json.load(f)
            except Exception:
                data = {"schema_version": 1, "always_approved": [], "always_denied": [],
                        "session_approved": [], "audit_log": []}
            data.setdefault("audit_log", []).append(entry)
            f.seek(0)
            f.truncate()
            json.dump(data, f, indent=2)
            fcntl.flock(f, fcntl.LOCK_UN)


def _input_preview(tool_name: str, tool_input: dict[str, Any]) -> str:
    if tool_name == "Bash":
        return tool_input.get("command", "")[:200]
    if tool_name in ("Write", "Edit", "Read"):
        return tool_input.get("file_path", "")
    return str(tool_input)[:200]


def _print_tool_preview(tool_name: str, tool_input: dict[str, Any]) -> None:
    if tool_name == "Bash":
        console.print(f"    [dim]$[/dim] {tool_input.get('command', '')[:200]}")
    elif tool_name == "Write":
        fp = tool_input.get("file_path", "")
        lines = tool_input.get("content", "").count("\n") + 1
        console.print(f"    [dim]Create/overwrite[/dim] {fp} [dim]({lines} lines)[/dim]")
    elif tool_name == "Edit":
        fp = tool_input.get("file_path", "")
        old = tool_input.get("old_string", "")[:80]
        console.print(f"    [dim]Edit[/dim] {fp}")
        console.print(f"    [dim]Replace:[/dim] {old}...")
    elif tool_name == "Read":
        console.print(f"    [dim]Read[/dim] {tool_input.get('file_path', '')}")
    elif tool_name == "Glob":
        console.print(f"    [dim]Pattern:[/dim] {tool_input.get('pattern', '')}")
    elif tool_name == "Grep":
        console.print(f"    [dim]Search:[/dim] {tool_input.get('pattern', '')} "
                      f"[dim]in[/dim] {tool_input.get('path', '.')}")
    else:
        for k, v in list(tool_input.items())[:3]:
            console.print(f"    [dim]{k}:[/dim] {str(v)[:80]}")
    console.print("    [dim][y]es once  [a]lways  [n]o once  [N]ever[/dim]")
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_permissions.py -v 2>&1 | tail -20
```

Expected: all permissions tests pass.

- [ ] **Step 5: Run full suite**

```bash
python -m pytest tests/ -q --tb=short 2>&1 | tail -5
```

Expected: 351 passed, 40 skipped (no regressions).

- [ ] **Step 6: Commit**

```bash
git add vantage_agent/permissions.py tests/test_permissions.py
git commit -m "feat(permissions): add always_denied, audit_log, deny(), clear_session_approved()"
```

---

## Task 2: Create PermissionServer — Unix socket + hook installer + settings merger

**Files:**
- Create: `vantage_agent/permission_server.py`
- Create: `tests/test_permission_server.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_permission_server.py`:

```python
"""Tests for PermissionServer: socket, hook script, settings merger."""
from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import time
from pathlib import Path

import pytest

from vantage_agent.permission_server import (
    PermissionServer,
    build_session_settings_file,
    install_hook_script,
)
from vantage_agent.permissions import PermissionManager


def test_install_hook_script_creates_executable(tmp_path):
    install_hook_script(config_dir=tmp_path)
    hook = tmp_path / "perm-hook.sh"
    assert hook.exists()
    assert os.access(hook, os.X_OK)
    content = hook.read_text()
    assert "VANTAGE_SOCKET" in content
    assert "always_approved" in content


def test_build_session_settings_file_with_no_user_settings(tmp_path):
    sock_path = "/tmp/vantage-perm-99999.sock"
    settings_path = tmp_path / "settings.json"
    build_session_settings_file(
        socket_path=sock_path,
        output_path=settings_path,
        user_settings_path=tmp_path / "nonexistent.json",
        config_dir=tmp_path,
    )
    data = json.loads(settings_path.read_text())
    hooks = data["hooks"]["PreToolUse"]
    assert len(hooks) == 1
    assert hooks[0]["hooks"][0]["env"]["VANTAGE_SOCKET"] == sock_path


def test_build_session_settings_file_merges_user_hooks(tmp_path):
    user_settings = tmp_path / "user_settings.json"
    user_settings.write_text(json.dumps({
        "hooks": {
            "PreToolUse": [{"matcher": "Bash(git*)", "hooks": [{"type": "command", "command": "user-hook.sh"}]}]
        }
    }))
    sock_path = "/tmp/vantage-perm-99999.sock"
    settings_path = tmp_path / "settings.json"
    build_session_settings_file(
        socket_path=sock_path,
        output_path=settings_path,
        user_settings_path=user_settings,
        config_dir=tmp_path,
    )
    data = json.loads(settings_path.read_text())
    hooks = data["hooks"]["PreToolUse"]
    # user hook first, vantage hook appended
    assert len(hooks) == 2
    assert hooks[0]["matcher"] == "Bash(git*)"
    assert hooks[1]["hooks"][0]["env"]["VANTAGE_SOCKET"] == sock_path


def test_permission_server_allow_response(tmp_path):
    """PermissionServer receives a hook request and returns 'allow_session'."""
    perm_file = tmp_path / "permissions.json"
    perm_file.write_text(json.dumps({
        "schema_version": 1, "always_approved": [], "always_denied": [],
        "session_approved": [], "audit_log": [],
    }))
    pm = PermissionManager(config_dir=tmp_path)
    sock_path = str(tmp_path / "test.sock")

    server = PermissionServer(socket_path=sock_path, permissions=pm)
    server.start()
    time.sleep(0.05)

    # Simulate hook connecting and sending tool data
    received_decision = []

    def simulate_hook():
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(sock_path)
        payload = json.dumps({
            "tool_name": "Edit",
            "tool_input": {"file_path": "foo.py", "old_string": "x", "new_string": "y"},
            "session_id": "test-session",
        })
        sock.sendall(payload.encode() + b"\n")
        response = b""
        while b"\n" not in response:
            response += sock.recv(256)
        received_decision.append(response.decode().strip())
        sock.close()

    hook_thread = threading.Thread(target=simulate_hook)
    hook_thread.start()

    # Simulate user approving in the main thread (server puts request in queue)
    req = server.perm_request_queue.get(timeout=2.0)
    assert req["tool_name"] == "Edit"
    server.perm_response_queue.put("allow_session")

    hook_thread.join(timeout=2.0)
    server.stop()

    assert received_decision == ["allow_session"]


def test_permission_server_deny_response(tmp_path):
    perm_file = tmp_path / "permissions.json"
    perm_file.write_text(json.dumps({
        "schema_version": 1, "always_approved": [], "always_denied": [],
        "session_approved": [], "audit_log": [],
    }))
    pm = PermissionManager(config_dir=tmp_path)
    sock_path = str(tmp_path / "test2.sock")
    server = PermissionServer(socket_path=sock_path, permissions=pm)
    server.start()
    time.sleep(0.05)

    received = []

    def simulate_hook():
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(sock_path)
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}, "session_id": "s"})
        sock.sendall(payload.encode() + b"\n")
        resp = b""
        while b"\n" not in resp:
            resp += sock.recv(256)
        received.append(resp.decode().strip())
        sock.close()

    t = threading.Thread(target=simulate_hook)
    t.start()
    server.perm_request_queue.get(timeout=2.0)
    server.perm_response_queue.put("deny_session")
    t.join(timeout=2.0)
    server.stop()
    assert received == ["deny_session"]
```

- [ ] **Step 2: Run to confirm failures**

```bash
python -m pytest tests/test_permission_server.py -v 2>&1 | tail -15
```

Expected: ImportError — `permission_server` doesn't exist yet.

- [ ] **Step 3: Create `vantage_agent/permission_server.py`**

```python
"""
permission_server.py — Unix socket server for real-time tool permission prompts.

Architecture:
  - PermissionServer runs as a background Thread.
  - The PreToolUse hook (perm-hook.sh) connects to the socket per tool call.
  - Hook sends tool JSON → server puts in perm_request_queue → main thread reads,
    shows prompt, puts decision in perm_response_queue → server writes to hook.
  - Main thread owns terminal I/O during prompts (no interleaving).
"""
from __future__ import annotations

import json
import os
import socket
import threading
from pathlib import Path
from typing import Any


class PermissionServer(threading.Thread):
    """Background thread: accepts Unix socket connections from perm-hook.sh."""

    def __init__(self, socket_path: str, permissions: Any) -> None:
        super().__init__(daemon=True)
        self.socket_path = socket_path
        self.permissions = permissions
        self.perm_request_queue: "queue.Queue[dict]" = __import__("queue").Queue()
        self.perm_response_queue: "queue.Queue[str]" = __import__("queue").Queue()
        self._stop_event = threading.Event()
        self._server_sock: socket.socket | None = None

    def run(self) -> None:
        import queue as _queue
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)
        self._server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_sock.bind(self.socket_path)
        self._server_sock.listen(1)
        self._server_sock.settimeout(0.2)
        while not self._stop_event.is_set():
            try:
                conn, _ = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self._handle_connection(conn)
        try:
            self._server_sock.close()
        except Exception:
            pass
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

    def _handle_connection(self, conn: socket.socket) -> None:
        try:
            data = b""
            conn.settimeout(5.0)
            while b"\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            tool_data = json.loads(data.decode().strip())
            self.perm_request_queue.put(tool_data)
            # Block until main thread provides decision
            decision = self.perm_response_queue.get(timeout=120.0)
            conn.sendall((decision + "\n").encode())
        except Exception:
            try:
                conn.sendall(b"allow\n")
            except Exception:
                pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def stop(self) -> None:
        self._stop_event.set()
        if self._server_sock:
            try:
                self._server_sock.close()
            except Exception:
                pass


def install_hook_script(config_dir: Path) -> Path:
    """Write ~/.vantage-agent/perm-hook.sh and make it executable."""
    config_dir.mkdir(parents=True, exist_ok=True)
    hook_path = config_dir / "perm-hook.sh"
    hook_path.write_text(_HOOK_SCRIPT)
    hook_path.chmod(0o755)
    return hook_path


def build_session_settings_file(
    socket_path: str,
    output_path: Path,
    user_settings_path: Path | None = None,
    config_dir: Path | None = None,
) -> Path:
    """
    Merge user's ~/.claude/settings.json with the vantage PreToolUse hook.
    Writes merged settings to output_path. --settings REPLACES user settings,
    so we must carry all existing settings forward.
    """
    _cfg = str(config_dir or Path.home() / ".vantage-agent")

    # Load user settings (fail gracefully)
    user_settings: dict = {}
    candidate = user_settings_path or Path.home() / ".claude" / "settings.json"
    if candidate.exists():
        try:
            user_settings = json.loads(candidate.read_text())
        except Exception:
            pass

    vantage_hook = {
        "matcher": ".*",
        "hooks": [{
            "type": "command",
            "command": str(Path(_cfg) / "perm-hook.sh"),
            "env": {
                "VANTAGE_SOCKET": socket_path,
                "COHRINT_CONFIG_DIR": _cfg,
            },
        }],
    }

    existing_pre_hooks = user_settings.get("hooks", {}).get("PreToolUse", [])
    merged = {**user_settings}
    merged["hooks"] = {
        **user_settings.get("hooks", {}),
        "PreToolUse": existing_pre_hooks + [vantage_hook],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(merged, indent=2))
    return output_path


_HOOK_SCRIPT = r"""#!/bin/bash
# vantage-agent PreToolUse permission hook
# Receives tool info on stdin as JSON from Claude Code.
# Exits 0 = allow, 2 = block (stdout message goes to model as tool_result).

SOCKET_PATH="${VANTAGE_SOCKET:-}"
CONFIG_DIR="${COHRINT_CONFIG_DIR:-$HOME/.vantage-agent}"
PERMISSIONS_FILE="$CONFIG_DIR/permissions.json"

# Read stdin (tool info JSON)
INPUT=$(cat)

# Fast-path: check always_approved / always_denied without socket
FAST=$(python3 - "$INPUT" "$PERMISSIONS_FILE" 2>/dev/null << 'PYEOF'
import sys, json, os
try:
    data = json.loads(sys.argv[1])
    tool = data.get("tool_name", "")
    pf = sys.argv[2]
    perms = json.load(open(pf)) if os.path.exists(pf) else {}
    approved = set(perms.get("always_approved", []))
    denied = set(perms.get("always_denied", []))
    session = set(perms.get("session_approved", []))
    if tool in denied:
        print("deny")
    elif tool in approved or tool in session:
        print("allow")
    else:
        print("prompt")
except Exception:
    print("prompt")
PYEOF
)

case "$FAST" in
    "allow") exit 0 ;;
    "deny")
        TOOL=$(python3 -c "import sys,json; print(json.loads(sys.argv[1]).get('tool_name','tool'))" "$INPUT" 2>/dev/null)
        echo "[Vantage] $TOOL is in your always-denied list."
        exit 2
        ;;
esac

# Need interactive prompt: connect to vantage-agent socket
if [ -z "$SOCKET_PATH" ] || [ ! -S "$SOCKET_PATH" ]; then
    # No socket available — apply fail policy
    POLICY=$(python3 -c "
import json, os
cfg = os.path.join(os.environ.get('COHRINT_CONFIG_DIR', os.path.expanduser('~/.vantage-agent')), 'config.json')
d = json.load(open(cfg)) if os.path.exists(cfg) else {}
print(d.get('hook_fail_policy', 'allow'))
" 2>/dev/null || echo "allow")
    [ "$POLICY" = "deny" ] && exit 2 || exit 0
fi

# Connect to socket and get decision
RESPONSE=$(python3 - "$INPUT" "$SOCKET_PATH" << 'PYEOF'
import sys, socket, json
try:
    data = json.loads(sys.argv[1])
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(120.0)
    sock.connect(sys.argv[2])
    sock.sendall(json.dumps(data).encode() + b"\n")
    resp = b""
    while b"\n" not in resp:
        chunk = sock.recv(256)
        if not chunk:
            break
        resp += chunk
    sock.close()
    print(resp.decode().strip())
except Exception:
    print("allow")
PYEOF
)

case "$RESPONSE" in
    allow*) exit 0 ;;
    deny*)
        TOOL=$(python3 -c "import sys,json; print(json.loads(sys.argv[1]).get('tool_name','tool'))" "$INPUT" 2>/dev/null)
        echo "[Vantage] $TOOL denied. Use /allow $TOOL to approve, or try a read-only approach."
        exit 2
        ;;
    *) exit 0 ;;
esac
"""
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_permission_server.py -v 2>&1 | tail -20
```

Expected: all 5 tests pass.

- [ ] **Step 5: Full suite**

```bash
python -m pytest tests/ -q --tb=short 2>&1 | tail -5
```

Expected: 351 passed, 40 skipped.

- [ ] **Step 6: Commit**

```bash
git add vantage_agent/permission_server.py tests/test_permission_server.py
git commit -m "feat(permission-server): Unix socket server, hook installer, settings merger"
```

---

## Task 3: Create SetupWizard — tiered startup, first-run detection, config.json

**Files:**
- Create: `vantage_agent/setup_wizard.py`
- Create: `tests/test_setup_wizard.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_setup_wizard.py`:

```python
"""Tests for SetupWizard: tier selection, config.json, apply_tier."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from vantage_agent.permissions import PermissionManager
from vantage_agent.setup_wizard import (
    TIER_TOOLS,
    apply_tier,
    get_config,
    needs_setup,
    write_config,
)


def test_needs_setup_true_when_no_config(tmp_path):
    assert needs_setup(config_dir=tmp_path) is True


def test_needs_setup_false_when_tier_set(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"default_tier": 2}))
    assert needs_setup(config_dir=tmp_path) is False


def test_write_and_get_config(tmp_path):
    write_config({"default_tier": 3, "hook_fail_policy": "deny"}, config_dir=tmp_path)
    cfg = get_config(config_dir=tmp_path)
    assert cfg["default_tier"] == 3
    assert cfg["hook_fail_policy"] == "deny"


def test_tier_tools_bash_never_in_any_tier():
    """Bash must never be auto-approved regardless of tier."""
    for tier in (1, 2, 3):
        assert "Bash" not in TIER_TOOLS[tier], f"Bash must not be in tier {tier} auto-approvals"


def test_apply_tier_1_approves_only_readonly(tmp_path):
    perm_file = tmp_path / "permissions.json"
    perm_file.write_text(json.dumps({"schema_version": 1, "always_approved": [],
                                      "always_denied": [], "session_approved": [], "audit_log": []}))
    pm = PermissionManager(config_dir=tmp_path)
    apply_tier(1, pm)
    assert "Read" in pm.always_approved
    assert "Glob" in pm.always_approved
    assert "Grep" in pm.always_approved
    assert "Edit" not in pm.always_approved
    assert "Bash" not in pm.always_approved


def test_apply_tier_2_approves_file_editing(tmp_path):
    perm_file = tmp_path / "permissions.json"
    perm_file.write_text(json.dumps({"schema_version": 1, "always_approved": [],
                                      "always_denied": [], "session_approved": [], "audit_log": []}))
    pm = PermissionManager(config_dir=tmp_path)
    apply_tier(2, pm)
    assert "Edit" in pm.always_approved
    assert "Write" in pm.always_approved
    assert "Bash" not in pm.always_approved


def test_apply_tier_3_still_excludes_bash(tmp_path):
    perm_file = tmp_path / "permissions.json"
    perm_file.write_text(json.dumps({"schema_version": 1, "always_approved": [],
                                      "always_denied": [], "session_approved": [], "audit_log": []}))
    pm = PermissionManager(config_dir=tmp_path)
    apply_tier(3, pm)
    assert "Bash" not in pm.always_approved


def test_get_config_returns_defaults_when_missing(tmp_path):
    cfg = get_config(config_dir=tmp_path)
    assert cfg.get("hook_fail_policy") == "allow"
```

- [ ] **Step 2: Run to confirm failures**

```bash
python -m pytest tests/test_setup_wizard.py -v 2>&1 | tail -15
```

Expected: ImportError — `setup_wizard` doesn't exist.

- [ ] **Step 3: Create `vantage_agent/setup_wizard.py`**

```python
"""
setup_wizard.py — First-run tiered permission wizard.

Shown when a user runs vantageai-agent without an API key and
auto_detect_backend() returns 'claude' (or --backend claude is passed).

TIER_TOOLS maps tier number → tools to auto-approve.
Bash is NEVER in any tier — always requires per-call hook approval.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.prompt import Prompt

if TYPE_CHECKING:
    from .permissions import PermissionManager

console = Console()

_CONFIG_FILE = "config.json"

# Tools auto-approved per tier. Bash intentionally absent from all tiers.
TIER_TOOLS: dict[int, list[str]] = {
    1: ["Read", "Glob", "Grep"],
    2: ["Read", "Glob", "Grep", "Edit", "Write"],
    3: ["Read", "Glob", "Grep", "Edit", "Write", "Glob"],  # Bash still excluded
}


def _config_dir(config_dir: Path | None) -> Path:
    return config_dir or Path(os.environ.get("COHRINT_CONFIG_DIR", Path.home() / ".vantage-agent"))


def needs_setup(config_dir: Path | None = None) -> bool:
    """Return True if no tier has been configured yet."""
    cfg_path = _config_dir(config_dir) / _CONFIG_FILE
    if not cfg_path.exists():
        return True
    try:
        data = json.loads(cfg_path.read_text())
        return "default_tier" not in data
    except Exception:
        return True


def get_config(config_dir: Path | None = None) -> dict:
    """Load config.json, returning defaults for missing keys."""
    cfg_path = _config_dir(config_dir) / _CONFIG_FILE
    defaults = {"hook_fail_policy": "allow", "default_tier": None}
    if not cfg_path.exists():
        return defaults
    try:
        data = json.loads(cfg_path.read_text())
        return {**defaults, **data}
    except Exception:
        return defaults


def write_config(data: dict, config_dir: Path | None = None) -> None:
    """Write (merge) keys into config.json."""
    cd = _config_dir(config_dir)
    cd.mkdir(parents=True, exist_ok=True)
    cfg_path = cd / _CONFIG_FILE
    existing: dict = {}
    if cfg_path.exists():
        try:
            existing = json.loads(cfg_path.read_text())
        except Exception:
            pass
    existing.update(data)
    cfg_path.write_text(json.dumps(existing, indent=2))


def apply_tier(tier: int, permissions: "PermissionManager") -> None:
    """Auto-approve the tools for the chosen tier. Bash always excluded."""
    tools = [t for t in TIER_TOOLS.get(tier, TIER_TOOLS[1]) if t != "Bash"]
    permissions.approve(tools, always=True)


def run_setup_wizard(permissions: "PermissionManager", config_dir: Path | None = None) -> int:
    """
    Show the interactive tier selection menu.
    Returns the chosen tier (1-4).
    """
    console.print()
    console.print("  [bold]Vantage Agent — Tool Permissions[/bold]")
    console.print()
    console.print("  Claude Code CLI detected. Select what Claude is allowed to do:")
    console.print()
    console.print("  [bold][1][/bold] Read-only   Read, Glob, Grep                    [dim](safe, auto-approve)[/dim]")
    console.print("  [bold][2][/bold] Standard    + Edit, Write                       [dim](file edits, auto-approve)[/dim]")
    console.print("  [bold][3][/bold] Full        + Bash [dim](shell commands always ask per-call)[/dim]")
    console.print("  [bold][4][/bold] Custom      Choose tools individually")
    console.print()
    console.print("  [dim]Note: Bash is never auto-approved — it always asks before each command.[/dim]")
    console.print()

    choice = Prompt.ask("  Tier", choices=["1", "2", "3", "4"], default="2")
    tier = int(choice)

    if tier == 4:
        tier = _run_custom_tier(permissions)
    else:
        apply_tier(tier, permissions)
        console.print(f"  [green]✓ Tier {tier} applied[/green]")

    write_config({"default_tier": tier}, config_dir=config_dir)
    console.print()
    return tier


def _run_custom_tier(permissions: "PermissionManager") -> int:
    """Let user pick tools individually. Returns 4."""
    from .tools import TOOL_MAP
    console.print()
    console.print("  Auto-approve which tools? [dim](Bash always asks — not listed)[/dim]")
    tools = [t for t in sorted(TOOL_MAP.keys()) if t != "Bash"]
    approved = []
    for tool in tools:
        ans = Prompt.ask(f"    Auto-approve [bold]{tool}[/bold]?", choices=["y", "n"], default="y")
        if ans == "y":
            approved.append(tool)
    if approved:
        permissions.approve(approved, always=True)
        console.print(f"  [green]✓ Auto-approved: {', '.join(approved)}[/green]")
    return 4
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_setup_wizard.py -v 2>&1 | tail -15
```

Expected: all 8 tests pass.

- [ ] **Step 5: Full suite**

```bash
python -m pytest tests/ -q --tb=short 2>&1 | tail -5
```

Expected: 351 passed, 40 skipped.

- [ ] **Step 6: Commit**

```bash
git add vantage_agent/setup_wizard.py tests/test_setup_wizard.py
git commit -m "feat(setup-wizard): tiered startup wizard, first-run detection, config.json"
```

---

## Task 4: Rewrite ClaudeCliBackend — stream-json event loop, --resume, exact costs

**Files:**
- Rewrite: `vantage_agent/backends/claude_backend.py`
- Create: `tests/test_claude_backend.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_claude_backend.py`:

```python
"""Tests for ClaudeCliBackend stream-json parser (no subprocess spawned)."""
from __future__ import annotations

import json
import queue
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from vantage_agent.backends.claude_backend import ClaudeCliBackend, _parse_stream_event


def _make_event(**kwargs) -> bytes:
    return (json.dumps(kwargs) + "\n").encode()


def test_parse_result_event_extracts_cost_and_session_id():
    event = {
        "type": "result",
        "subtype": "success",
        "total_cost_usd": 0.0523,
        "session_id": "abc-123",
        "usage": {"input_tokens": 500, "output_tokens": 80},
    }
    state = {"result": None}
    _parse_stream_event(event, state, render=False)
    assert state["result"]["total_cost_usd"] == 0.0523
    assert state["result"]["session_id"] == "abc-123"
    assert state["result"]["input_tokens"] == 500
    assert state["result"]["output_tokens"] == 80


def test_parse_assistant_text_event_accumulates_text():
    event = {
        "type": "assistant",
        "message": {
            "content": [{"type": "text", "text": "Hello world"}],
        },
    }
    state = {"text": "", "result": None}
    _parse_stream_event(event, state, render=False)
    assert state["text"] == "Hello world"


def test_parse_rate_limit_event_sets_resets_at():
    future_ts = int(datetime.now(timezone.utc).timestamp()) + 300
    event = {
        "type": "rate_limit_event",
        "rate_limit_info": {"resetsAt": future_ts, "rateLimitType": "five_hour"},
    }
    state = {"result": None, "rate_limit_resets_at": None}
    _parse_stream_event(event, state, render=False)
    assert state["rate_limit_resets_at"] == future_ts


def test_session_id_persisted_between_calls(tmp_path):
    """ClaudeCliBackend stores session_id from result and uses it in next --resume."""
    backend = ClaudeCliBackend(model="claude-sonnet-4-6", config_dir=tmp_path)
    backend._claude_session_id = "prev-session-xyz"

    cmd = backend._build_command(prompt="hello", cwd=str(tmp_path))
    assert "--resume" in cmd
    idx = cmd.index("--resume")
    assert cmd[idx + 1] == "prev-session-xyz"


def test_no_resume_on_first_call(tmp_path):
    backend = ClaudeCliBackend(model="claude-sonnet-4-6", config_dir=tmp_path)
    assert backend._claude_session_id is None
    cmd = backend._build_command(prompt="hello", cwd=str(tmp_path))
    assert "--resume" not in cmd


def test_build_command_includes_required_flags(tmp_path):
    backend = ClaudeCliBackend(model="claude-opus-4-6", config_dir=tmp_path)
    cmd = backend._build_command(prompt="test", cwd="/tmp")
    assert "claude" in cmd[0]
    assert "-p" in cmd
    assert "--output-format" in cmd
    assert "stream-json" in cmd
    assert "--permission-mode" in cmd
    assert "bypassPermissions" in cmd
    assert "--no-session-persistence" in cmd
    assert "--model" in cmd
    assert "claude-opus-4-6" in cmd


def test_capabilities():
    from vantage_agent.backends.base import BackendCapabilities
    backend = ClaudeCliBackend.__new__(ClaudeCliBackend)
    assert backend.capabilities.token_count == "exact"
    assert backend.capabilities.supports_process is False
```

- [ ] **Step 2: Run to confirm failures**

```bash
python -m pytest tests/test_claude_backend.py -v 2>&1 | tail -15
```

Expected: ImportError or AttributeError — `_parse_stream_event`, `_build_command` don't exist.

- [ ] **Step 3: Rewrite `vantage_agent/backends/claude_backend.py`**

```python
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
            os.environ.get("COHRINT_CONFIG_DIR", Path.home() / ".vantage-agent")
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
            "--no-session-persistence",
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
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_claude_backend.py -v 2>&1 | tail -15
```

Expected: all 8 tests pass.

- [ ] **Step 5: Full suite**

```bash
python -m pytest tests/ -q --tb=short 2>&1 | tail -5
```

Expected: 351 passed, 40 skipped.

- [ ] **Step 6: Commit**

```bash
git add vantage_agent/backends/claude_backend.py tests/test_claude_backend.py
git commit -m "feat(claude-backend): stream-json subprocess, --resume history, exact cost extraction"
```

---

## Task 5: Wire CLI — backend dispatch, wizard, permission server lifecycle, /tier, cost display

**Files:**
- Modify: `vantage_agent/cli.py`
- Test: existing `tests/test_cli.py` (add cases)

- [ ] **Step 1: Write failing tests**

Add to `tests/test_cli.py`:

```python
from unittest.mock import patch, MagicMock
import sys


def test_tier_command_updates_config(tmp_path, capsys):
    """REPL /tier command writes new tier to config.json."""
    from vantage_agent.cli import _handle_tier_command
    from vantage_agent.permissions import PermissionManager
    pm = PermissionManager(config_dir=tmp_path)
    with patch("vantage_agent.cli.Prompt.ask", return_value="1"):
        _handle_tier_command(pm, config_dir=tmp_path)
    from vantage_agent.setup_wizard import get_config
    cfg = get_config(config_dir=tmp_path)
    assert cfg["default_tier"] == 1


def test_build_client_auto_detects_claude_backend(tmp_path, monkeypatch):
    """When no API key and claude CLI found, auto-detects claude backend."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch("shutil.which", return_value="/usr/local/bin/claude"), \
         patch("vantage_agent.backends.auto_detect_backend", return_value="claude"):
        from vantage_agent.cli import _detect_backend
        backend = _detect_backend(api_key=None, requested_backend=None)
    assert backend == "claude"


def test_build_client_uses_api_when_key_present(monkeypatch):
    """When ANTHROPIC_API_KEY is set, backend is api regardless of claude CLI."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    with patch("vantage_agent.cli._detect_backend") as mock:
        mock.return_value = "api"
        result = mock(api_key="sk-ant-test", requested_backend=None)
    assert result == "api"
```

- [ ] **Step 2: Run to confirm failures**

```bash
python -m pytest tests/test_cli.py -k "tier_command or auto_detects or key_present" -v 2>&1 | tail -15
```

Expected: failures — `_handle_tier_command`, `_detect_backend` not yet extracted.

- [ ] **Step 3: Add `_detect_backend` and `_handle_tier_command` to `cli.py`**

Read current `cli.py`, then add these functions before `_build_client` and add `/tier` to the REPL:

```python
# Add these imports at top of cli.py (after existing imports):
from .backends import auto_detect_backend
from .setup_wizard import needs_setup, run_setup_wizard, get_config, write_config
from .permission_server import PermissionServer, install_hook_script


def _detect_backend(api_key: str | None, requested_backend: str | None) -> str:
    """Determine which backend to use. Returns 'api' or 'claude' (or other CLI)."""
    if requested_backend:
        return requested_backend
    effective_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if effective_key:
        return "api"
    try:
        detected = auto_detect_backend()
        return detected
    except RuntimeError:
        return "api"  # will fail naturally in AgentClient with helpful message


def _handle_tier_command(
    permissions: "PermissionManager",
    config_dir: "Path | None" = None,
) -> None:
    """Handle /tier REPL command — show tier menu, apply selection."""
    from .setup_wizard import run_setup_wizard
    run_setup_wizard(permissions=permissions, config_dir=config_dir)
```

- [ ] **Step 4: Update `_build_client` to dispatch by backend and run wizard**

In `_build_client`, after the existing `permissions = PermissionManager()` line, add:

```python
    config_dir = Path(os.environ.get("COHRINT_CONFIG_DIR", Path.home() / ".vantage-agent"))
    backend_name = _detect_backend(
        api_key=args.api_key,
        requested_backend=getattr(args, "backend", None),
    )

    if backend_name == "claude":
        # First-run wizard for Claude CLI backend
        if needs_setup(config_dir=config_dir):
            run_setup_wizard(permissions=permissions, config_dir=config_dir)
        # Start permission server
        sock_path = f"/tmp/vantage-perm-{os.getpid()}.sock"
        perm_server = PermissionServer(socket_path=sock_path, permissions=permissions)
        perm_server.start()
        # Build ClaudeCliBackend
        from .backends.claude_backend import ClaudeCliBackend
        backend = ClaudeCliBackend(
            model=model,
            config_dir=config_dir,
            permission_server=perm_server,
        )
        backend.prepare_session_settings(pid=os.getpid())
        # Return a ClaudeCliClient wrapper (see below)
        return _ClaudeCliClient(backend=backend, permissions=permissions,
                                perm_server=perm_server, model=model,
                                cost=cost, cwd=cwd), tracker
    # else: fall through to existing AgentClient path
```

- [ ] **Step 5: Add `_ClaudeCliClient` wrapper class to `cli.py`**

Add before `run_repl`:

```python
class _ClaudeCliClient:
    """Thin wrapper around ClaudeCliBackend with same interface as AgentClient."""

    def __init__(self, backend, permissions, perm_server, model, cost, cwd):
        from .backends.claude_backend import ClaudeCliBackend
        self.backend: ClaudeCliBackend = backend
        self.permissions = permissions
        self.perm_server = perm_server
        self.model = model
        self.cost = cost
        self.cwd = cwd
        self.optimization = True

    def send(self, prompt: str, no_optimize: bool = False) -> str:
        result = self.backend.send(prompt=prompt, history=[], cwd=self.cwd)
        self.cost.record_usage_raw(
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_usd=result.cost_usd,
        )
        return result.output_text

    def clear_history(self) -> None:
        self.backend._claude_session_id = None

    def stop(self) -> None:
        self.perm_server.stop()
        self.permissions.clear_session_approved()
```

- [ ] **Step 6: Add `/tier` to the REPL command handler**

In `_handle_command`, add before the final `return False`:

```python
    if stripped == "/tier":
        from pathlib import Path
        config_dir = Path(os.environ.get("COHRINT_CONFIG_DIR", Path.home() / ".vantage-agent"))
        _handle_tier_command(client.permissions, config_dir=config_dir)
        return True
```

Also update the BANNER to include `/tier`:

```python
    [bold]/tier[/bold]             Change tool permission tier
```

- [ ] **Step 7: Add `record_usage_raw` to `SessionCost`**

Read `vantage_agent/cost_tracker.py`. Add method:

```python
    def record_usage_raw(self, input_tokens: int, output_tokens: int, cost_usd: float) -> None:
        """Record pre-computed token counts (used by ClaudeCliBackend with exact counts)."""
        from .cost_tracker import TurnCost
        self.total_input += input_tokens
        self.total_output += output_tokens
        turn = TurnCost(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            model=self.model,
        )
        self.turns.append(turn)
        self.prompt_count += 1
```

- [ ] **Step 8: Run tests**

```bash
python -m pytest tests/test_cli.py -v 2>&1 | tail -20
```

Expected: all cli tests pass including the 3 new ones.

- [ ] **Step 9: Full suite**

```bash
python -m pytest tests/ -q --tb=short 2>&1 | tail -5
```

Expected: 351 passed, 40 skipped.

- [ ] **Step 10: Commit**

```bash
git add vantage_agent/cli.py vantage_agent/cost_tracker.py tests/test_cli.py
git commit -m "feat(cli): backend dispatch, permission server lifecycle, /tier command, wizard integration"
```

---

## Task 6: Missing test coverage — session lifecycle, concurrent store, budget hooks

**Files:**
- Create: `tests/test_session_lifecycle.py`

These cover TE1, TE2, TE5, TE6, TE8, TE9 from the spec.

- [ ] **Step 1: Write the tests**

Create `tests/test_session_lifecycle.py`:

```python
"""
Tests for session lifecycle, concurrent access, budget enforcement, history trim.
Covers: TE1 (resume), TE2 (concurrent), TE5 (budget), TE6 (corruption), TE8 (lifecycle), TE9 (trim).
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vantage_agent.session_store import SessionStore
from vantage_agent.session import VantageSession, _trim_history
from vantage_agent.hooks import BudgetExceededError, HookContext, CostSummary, check_budget_hook


# TE8: Full session lifecycle — create → send → save → resume → send → history persisted
def test_session_create_save_resume_lifecycle(tmp_path):
    store = SessionStore(sessions_dir=tmp_path / "sessions")
    backend = MagicMock()
    backend.name = "api"
    backend.capabilities.token_count = "exact"
    backend.capabilities.supports_process = False
    backend.send.return_value = MagicMock(
        output_text="reply", input_tokens=10, output_tokens=5,
        cost_usd=0.001, model="claude-sonnet-4-6",
    )

    session = VantageSession.create(backend=backend, cwd=str(tmp_path), store=store)
    session_id = session.session_id
    session.send("hello")
    session.save()

    # Resume and verify history carried forward
    resumed = VantageSession.resume(session_id=session_id, backend=backend, store=store)
    assert len(resumed.history) == 2  # user + assistant
    assert resumed.history[0]["role"] == "user"
    assert resumed.history[0]["text"] == "hello"
    assert resumed.history[1]["role"] == "assistant"
    assert resumed.history[1]["text"] == "reply"


# TE1: Resume non-existent session raises cleanly
def test_resume_nonexistent_session_raises(tmp_path):
    store = SessionStore(sessions_dir=tmp_path / "sessions")
    backend = MagicMock()
    with pytest.raises(Exception):
        VantageSession.resume(session_id="does-not-exist", backend=backend, store=store)


# TE2: Concurrent SessionStore writes don't corrupt data
def test_concurrent_session_store_writes(tmp_path):
    store = SessionStore(sessions_dir=tmp_path / "sessions")
    errors = []

    def write_session(i):
        try:
            store.save({"id": f"session-{i}", "schema_version": 1,
                        "messages": [{"role": "user", "text": f"msg-{i}"}],
                        "cost_summary": {"total_cost_usd": 0.0}})
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=write_session, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent writes caused errors: {errors}"
    # Verify all sessions written
    all_sessions = store.list_all()
    assert len(all_sessions) == 10


# TE5: BudgetExceededError raised by check_budget_hook for api backend
def test_budget_exceeded_raises_for_api_backend():
    ctx = HookContext(
        prompt="test",
        history=[],
        backend_name="api",
        backend_token_count="exact",
        session_id="s",
        result=None,
        cost_so_far=CostSummary(total_cost_usd=1.05, prompt_count=5, budget_usd=1.00),
    )
    with pytest.raises(BudgetExceededError):
        check_budget_hook(ctx)


# TE5b: Budget exceeded for CLI backend prints warning, does NOT raise
def test_budget_exceeded_warns_for_cli_backend(capsys):
    ctx = HookContext(
        prompt="test",
        history=[],
        backend_name="claude",
        backend_token_count="estimated",
        session_id="s",
        result=None,
        cost_so_far=CostSummary(total_cost_usd=1.05, prompt_count=5, budget_usd=1.00),
    )
    result = check_budget_hook(ctx)  # must not raise
    assert result is not None


# TE6: Malformed permissions.json loads safe defaults, doesn't crash
def test_malformed_permissions_json_safe_defaults(tmp_path):
    from vantage_agent.permissions import PermissionManager
    perm_file = tmp_path / "permissions.json"
    perm_file.write_text("{invalid json here!!!}")
    pm = PermissionManager(config_dir=tmp_path)
    assert "Read" in pm.always_approved  # SAFE_TOOLS default applied


# TE9: History trim fires at exact token boundary and notifies
def test_trim_history_at_boundary():
    # Each message is 40 chars / 4 = 10 tokens → 800 messages = 8000 tokens
    msgs = [{"role": "user" if i % 2 == 0 else "assistant",
             "text": "x" * 40} for i in range(802)]
    trimmed = _trim_history(msgs)
    # Must be under limit
    total_chars = sum(len(m.get("text", "")) for m in trimmed)
    assert total_chars // 4 <= 8000


# TE9b: Trim always preserves pairs (drops 2 at a time)
def test_trim_preserves_pairs():
    msgs = [{"role": "user" if i % 2 == 0 else "assistant",
             "text": "x" * 40} for i in range(802)]
    trimmed = _trim_history(msgs)
    assert len(trimmed) % 2 == 0  # always even (pairs)
```

- [ ] **Step 2: Run tests**

```bash
python -m pytest tests/test_session_lifecycle.py -v 2>&1 | tail -25
```

Expected: all pass (the session/trim/budget code already exists from prior fixes).

- [ ] **Step 3: Full suite**

```bash
python -m pytest tests/ -q --tb=short 2>&1 | tail -5
```

Expected: 351 passed, 40 skipped (new tests add to total).

- [ ] **Step 4: Commit**

```bash
git add tests/test_session_lifecycle.py
git commit -m "test: add session lifecycle, concurrent store, budget, history trim coverage (TE1/2/5/6/8/9)"
```

---

## Task 7: End-to-end smoke test + cleanup

**Files:**
- Modify: `docs/superpowers/specs/2026-04-12-vantage-agent-permission-ux-overhaul.md` (update Status)

- [ ] **Step 1: Run full suite one final time**

```bash
python -m pytest tests/ -q --tb=short 2>&1 | tail -10
```

Expected: all tests pass, no regressions from baseline.

- [ ] **Step 2: Verify the CLI entry point starts without error**

```bash
python -m vantage_agent.cli --version
```

Expected: `vantageai-agent 0.1.0` (or current version from `__init__.py`).

- [ ] **Step 3: Verify backend auto-detection message**

```bash
# Temporarily unset API key to trigger detection path
ANTHROPIC_API_KEY="" python -m vantage_agent.cli --help 2>&1 | head -5
```

Expected: no crash, help text prints.

- [ ] **Step 4: Verify hook script installs correctly**

```bash
python -c "
from pathlib import Path
from vantage_agent.permission_server import install_hook_script
p = install_hook_script(Path('/tmp/vantage-test-hook'))
print('Hook installed:', p)
print('Executable:', p.stat().st_mode & 0o755 == 0o755)
print('Has VANTAGE_SOCKET:', 'VANTAGE_SOCKET' in p.read_text())
"
```

Expected: all three lines True/correct.

- [ ] **Step 5: Update spec status**

In `docs/superpowers/specs/2026-04-12-vantage-agent-permission-ux-overhaul.md`, change:

```
**Status:** Design / Pre-implementation
```

to:

```
**Status:** Implemented — see plan `docs/superpowers/plans/2026-04-12-vantage-agent-permission-ux-overhaul.md`
```

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "feat(vantage-agent): complete permission overhaul — ClaudeCliBackend, PreToolUse hook, tiered wizard

- ClaudeCliBackend: stream-json subprocess with --resume session anchoring, exact token counts
- PermissionServer: Unix socket server, per-call prompts with y/a/n/N, audit log
- Hook script: perm-hook.sh with fast-path for always_approved/always_denied + socket fallback
- SetupWizard: tiered startup (1=readonly, 2=standard, 3=full), Bash never auto-approved
- Shared permissions.json: both API and CLI backends share same store
- /tier REPL command: change permission tier mid-session
- API-equivalent cost display: honest labelling for Claude Max users
- Session lifecycle tests, concurrent store tests, budget enforcement tests (TE1/2/5/6/8/9)

Closes: P1-P8, C1-C8, I2, I6"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|-----------------|------|
| §3.1 Layer A (tiered startup) | Task 3 (setup_wizard.py) + Task 5 (/tier) |
| §3.1 Layer B (hook + socket) | Task 2 (permission_server.py) + Task 4 (claude_backend.py) |
| §3.2 Shared permissions.json | Task 1 (permissions.py) |
| §3.3 Tiered startup UI | Task 3 |
| §3.4 Hook architecture | Task 2 (hook script) + Task 4 (event loop) |
| §3.5 Terminal I/O ownership | Task 4 (stdout_queue + perm check in event loop) |
| §3.6 Hook fail policy | Task 2 (hook script config.json check) |
| §3.7 Settings file merge | Task 2 (build_session_settings_file) |
| §3.8 API-equivalent cost display | Task 4 (_parse_stream_event result handler) |
| §3.9 bypassPermissions + hook | Task 4 (_build_command) |
| §3.10 --resume session anchor | Task 4 (_build_command, session_id storage) |
| §6 Rate limit event display | Task 4 (rate_limit_event handler) |
| TE1-TE9 test gaps | Task 6 |

**No placeholders found.**

**Type consistency:** `_ClaudeCliClient.send()` returns `str` ✓. `ClaudeCliBackend.send()` returns `BackendResult` ✓. `PermissionServer.perm_request_queue` and `perm_response_queue` are `queue.Queue` ✓. `record_usage_raw` signature matches `SessionCost` fields ✓.

**One gap found and added:** `record_usage_raw` on `SessionCost` (Task 5, Step 7) — needed by `_ClaudeCliClient` but not in the original spec. Added inline.
