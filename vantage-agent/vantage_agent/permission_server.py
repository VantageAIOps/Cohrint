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
                "VANTAGE_CONFIG_DIR": _cfg,
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
CONFIG_DIR="${VANTAGE_CONFIG_DIR:-$HOME/.vantage-agent}"
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
cfg = os.path.join(os.environ.get('VANTAGE_CONFIG_DIR', os.path.expanduser('~/.vantage-agent')), 'config.json')
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
