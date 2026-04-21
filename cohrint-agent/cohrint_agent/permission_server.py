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
        # AF_UNIX socket files inherit the process umask. Under a cleared
        # umask (common in Docker / CI) the socket would land world-RW,
        # letting any local UID connect and inject "allow" responses or
        # read tool_input content (T-SAFETY.sock_umask).
        old_umask = os.umask(0o177)
        try:
            self._server_sock.bind(self.socket_path)
        finally:
            os.umask(old_umask)
        # Belt-and-suspenders: tighten the socket file explicitly even if
        # the umask path above was somehow bypassed.
        try:
            os.chmod(self.socket_path, 0o600)
        except OSError:
            pass
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

    # Absolute ceiling on the hook payload. Claude Code hook payloads are
    # typically <4 KiB; 64 KiB is generous but blocks a rogue socket peer
    # from growing the buffer to OOM (T-SAFETY.recv_bound).
    _MAX_RECV_BYTES = 64 * 1024

    def _handle_connection(self, conn: socket.socket) -> None:
        try:
            data = b""
            conn.settimeout(5.0)
            while b"\n" not in data:
                if len(data) >= self._MAX_RECV_BYTES:
                    # Peer is sending a runaway payload — refuse.
                    conn.sendall(b"deny\n")
                    return
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            # errors="replace" so a locale-mismatched byte or a non-ASCII
            # filename in tool_input doesn't silently 500 the socket and
            # surface as a mysterious "denied" without any user prompt.
            tool_data = json.loads(data.decode("utf-8", errors="replace").strip())
            self.perm_request_queue.put(tool_data)
            # Block until main thread provides decision. On timeout we MUST
            # fail closed — auto-approving because the user didn't answer
            # within 120 s turns a hung terminal into a silent permission
            # escalation (T-SAFETY.fail_closed).
            try:
                decision = self.perm_response_queue.get(timeout=120.0)
            except Exception:
                # Timed out. A subsequent main-thread response for this
                # request could otherwise sit in the queue and be consumed
                # by the NEXT tool call as if it were that call's answer,
                # silently authorising or denying an unrelated operation
                # (T-SAFETY.drain_stale_responses).
                import queue as _q
                while True:
                    try:
                        self.perm_response_queue.get_nowait()
                    except _q.Empty:
                        break
                raise
            conn.sendall((decision + "\n").encode())
        except Exception:
            try:
                conn.sendall(b"deny\n")
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
    """Write ~/.cohrint-agent/perm-hook.sh and make it executable.

    Uses tmp + os.replace so a pre-planted symlink at ``perm-hook.sh``
    can't redirect the write to an arbitrary file like ``~/.bashrc``
    (T-SAFETY.hook_script_symlink). os.replace on the same fs is atomic
    and does not follow the destination symlink on Linux/macOS.
    """
    config_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(config_dir, 0o700)
    except OSError:
        pass
    hook_path = config_dir / "perm-hook.sh"
    tmp_path = config_dir / "perm-hook.sh.tmp"
    # Create tmp fresh with O_EXCL so even the tmp path can't be pre-planted
    # by an attacker in the same user context.
    try:
        tmp_path.unlink()
    except FileNotFoundError:
        pass
    fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o755)
    with os.fdopen(fd, "w") as f:
        f.write(_HOOK_SCRIPT)
    os.replace(tmp_path, hook_path)
    return hook_path


def build_session_settings_file(
    socket_path: str,
    output_path: Path,
    user_settings_path: Path | None = None,
    config_dir: Path | None = None,
) -> Path:
    """
    Merge user's ~/.claude/settings.json with the cohrint PreToolUse hook.
    Writes merged settings to output_path. --settings REPLACES user settings,
    so we must carry all existing settings forward.
    """
    _cfg = str(config_dir or Path.home() / ".cohrint-agent")

    # Load user settings (fail gracefully)
    user_settings: dict = {}
    candidate = user_settings_path or Path.home() / ".claude" / "settings.json"
    if candidate.exists():
        try:
            user_settings = json.loads(candidate.read_text())
        except Exception:
            pass

    cohrint_hook = {
        "matcher": ".*",
        "hooks": [{
            "type": "command",
            "command": str(Path(_cfg) / "perm-hook.sh"),
            "env": {
                "COHRINT_SOCKET": socket_path,
                "COHRINT_CONFIG_DIR": _cfg,
            },
        }],
    }

    existing_pre_hooks = user_settings.get("hooks", {}).get("PreToolUse", [])
    merged = {**user_settings}
    merged["hooks"] = {
        **user_settings.get("hooks", {}),
        "PreToolUse": existing_pre_hooks + [cohrint_hook],
    }

    output_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(output_path.parent, 0o700)
    except OSError:
        pass
    # tmp + atomic replace so a symlink pre-planted at ``output_path``
    # can't redirect this JSON write outside the run/ dir
    # (T-SAFETY.settings_symlink).
    tmp_out = output_path.with_suffix(output_path.suffix + ".tmp")
    try:
        tmp_out.unlink()
    except FileNotFoundError:
        pass
    fd = os.open(str(tmp_out), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(merged, f, indent=2)
    os.replace(tmp_out, output_path)
    return output_path


_HOOK_SCRIPT = r"""#!/bin/bash
# cohrint-agent PreToolUse permission hook
# Receives tool info on stdin as JSON from Claude Code.
# Exits 0 = allow, 2 = block (stdout message goes to model as tool_result).

SOCKET_PATH="${COHRINT_SOCKET:-}"
CONFIG_DIR="${COHRINT_CONFIG_DIR:-$HOME/.cohrint-agent}"
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
        TOOL=$(python3 -c "import sys,json,re;\
t=json.loads(sys.argv[1]).get('tool_name','tool');\
print(re.sub(r'[^A-Za-z0-9_.-]','',t)[:64] or 'tool')" "$INPUT" 2>/dev/null)
        echo "[Cohrint] $TOOL is in your always-denied list."
        exit 2
        ;;
esac

# Need interactive prompt: connect to cohrint-agent socket
if [ -z "$SOCKET_PATH" ] || [ ! -S "$SOCKET_PATH" ]; then
    # No socket available — apply fail policy
    POLICY=$(python3 -c "
import json, os
cfg = os.path.join(os.environ.get('COHRINT_CONFIG_DIR', os.path.expanduser('~/.cohrint-agent')), 'config.json')
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
    # Fail closed. Printing "allow" on socket failure lets a crashed
    # permission server silently escalate privilege for every tool call.
    print("deny")
PYEOF
)

case "$RESPONSE" in
    allow*) exit 0 ;;
    deny*)
        TOOL=$(python3 -c "import sys,json,re;\
t=json.loads(sys.argv[1]).get('tool_name','tool');\
print(re.sub(r'[^A-Za-z0-9_.-]','',t)[:64] or 'tool')" "$INPUT" 2>/dev/null)
        echo "[Cohrint] $TOOL denied. Use /allow $TOOL to approve, or try a read-only approach."
        exit 2
        ;;
    *) exit 0 ;;
esac
"""
