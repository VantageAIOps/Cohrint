"""
Tests for vantage_agent.permissions — per-tool permission management.

Tests permission state, persistence, and approval logic.
Uses monkeypatch for user input simulation (unavoidable for interactive prompts).
"""
import json
import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from vantage_agent.permissions import PermissionManager
from vantage_agent.tools import SAFE_TOOLS


@pytest.fixture
def clean_perms(tmp_path):
    """Create a PermissionManager with isolated state dir."""
    return PermissionManager(config_dir=tmp_path)


class TestPermissionDefaults:
    def test_safe_tools_approved_by_default(self, clean_perms):
        for tool in SAFE_TOOLS:
            assert clean_perms.is_approved(tool)

    def test_bash_not_approved_by_default(self, clean_perms):
        assert not clean_perms.is_approved("Bash")

    def test_write_not_approved_by_default(self, clean_perms):
        assert not clean_perms.is_approved("Write")

    def test_edit_not_approved_by_default(self, clean_perms):
        assert not clean_perms.is_approved("Edit")


class TestApprove:
    def test_approve_single_tool_session(self, clean_perms):
        clean_perms.approve(["Bash"], always=False)
        assert clean_perms.is_approved("Bash")

    def test_approve_multiple_tools(self, clean_perms):
        clean_perms.approve(["Bash", "Write", "Edit"], always=False)
        assert clean_perms.is_approved("Bash")
        assert clean_perms.is_approved("Write")
        assert clean_perms.is_approved("Edit")

    def test_approve_always_persists(self, clean_perms, tmp_path):
        perm_file = tmp_path / "permissions.json"
        clean_perms.approve(["Bash"], always=True)
        assert perm_file.exists()
        data = json.loads(perm_file.read_text())
        assert "Bash" in data["always_approved"]

    def test_session_approve_does_not_persist(self, clean_perms, tmp_path):
        perm_file = tmp_path / "permissions.json"
        clean_perms.approve(["Bash"], always=False)
        if perm_file.exists():
            data = json.loads(perm_file.read_text())
            assert "Bash" not in data.get("always_approved", [])


class TestReset:
    def test_reset_clears_session_tools(self, clean_perms):
        clean_perms.approve(["Bash", "Write"], always=False)
        clean_perms.reset()
        assert not clean_perms.is_approved("Bash")
        assert not clean_perms.is_approved("Write")

    def test_reset_keeps_safe_tools(self, clean_perms):
        clean_perms.reset()
        for tool in SAFE_TOOLS:
            assert clean_perms.is_approved(tool)

    def test_reset_clears_always_approved(self, clean_perms):
        clean_perms.approve(["Bash"], always=True)
        clean_perms.reset()
        assert not clean_perms.is_approved("Bash")


class TestPersistence:
    def test_load_from_persisted_state(self, tmp_path):
        perm_file = tmp_path / "permissions.json"
        perm_file.write_text(json.dumps({"always_approved": ["Bash", "Write"]}))

        pm = PermissionManager(config_dir=tmp_path)
        assert pm.is_approved("Bash")
        assert pm.is_approved("Write")

    def test_corrupt_file_falls_back_to_defaults(self, tmp_path):
        perm_file = tmp_path / "permissions.json"
        perm_file.write_text("not json")

        pm = PermissionManager(config_dir=tmp_path)
        assert pm.is_approved("Read")
        assert not pm.is_approved("Bash")


class TestStatus:
    def test_status_returns_correct_sets(self, clean_perms):
        clean_perms.approve(["Bash"], always=True)
        clean_perms.approve(["Write"], always=False)
        session, always = clean_perms.status()
        assert "Bash" in session
        assert "Write" in session
        assert "Bash" in always
        assert "Write" not in always


class TestCheckPermission:
    """Test the interactive check_permission flow using input simulation."""

    def test_approved_tool_returns_true_without_prompt(self, clean_perms):
        # Read is in SAFE_TOOLS — should not prompt
        assert clean_perms.check_permission("Read", {"file_path": "/tmp/test"})

    def test_deny_returns_false(self, clean_perms):
        with patch("vantage_agent.permissions.Prompt.ask", return_value="n"):
            result = clean_perms.check_permission("Bash", {"command": "rm -rf /"})
        assert not result
        assert not clean_perms.is_approved("Bash")

    def test_yes_once_approves_for_session(self, clean_perms):
        with patch("vantage_agent.permissions.Prompt.ask", return_value="y"):
            result = clean_perms.check_permission("Bash", {"command": "echo hi"})
        assert result
        assert clean_perms.is_approved("Bash")

    def test_always_approves_permanently(self, clean_perms):
        with patch("vantage_agent.permissions.Prompt.ask", return_value="a"):
            result = clean_perms.check_permission("Write", {"file_path": "/tmp/f", "content": "x"})
        assert result
        assert "Write" in clean_perms.always_approved


# ---------------------------------------------------------------------------
# New tests for Task 1: always_denied, audit log, deny(), clear_session_approved
# ---------------------------------------------------------------------------

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
