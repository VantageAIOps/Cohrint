"""Tests for PermissionServer: socket, hook script, settings merger."""
from __future__ import annotations

import json
import os
import socket
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
    assert "COHRINT_SOCKET" in content
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
    assert hooks[0]["hooks"][0]["env"]["COHRINT_SOCKET"] == sock_path


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
    assert hooks[1]["hooks"][0]["env"]["COHRINT_SOCKET"] == sock_path


def test_permission_server_allow_response(tmp_path):
    """PermissionServer receives a hook request and returns 'allow_session'."""
    perm_file = tmp_path / "permissions.json"
    perm_file.write_text(json.dumps({
        "schema_version": 1, "always_approved": [], "always_denied": [],
        "session_approved": [], "audit_log": [],
    }))
    pm = PermissionManager(config_dir=tmp_path)
    # Unix socket path must be short (104-char limit on macOS)
    sock_path = f"/tmp/vantage-test-allow-{os.getpid()}.sock"

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
    sock_path = f"/tmp/vantage-test-deny-{os.getpid()}.sock"
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
