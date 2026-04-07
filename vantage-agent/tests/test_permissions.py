"""
Tests for vantage_agent.permissions — per-tool permission management.

Tests permission state, persistence, and approval logic.
Uses monkeypatch for user input simulation (unavoidable for interactive prompts).
"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from vantage_agent.permissions import PermissionManager, _PERM_FILE, _STATE_DIR
from vantage_agent.tools import SAFE_TOOLS


@pytest.fixture
def clean_perms(tmp_path, monkeypatch):
    """Create a PermissionManager with isolated state dir."""
    state_dir = tmp_path / ".vantage-agent"
    perm_file = state_dir / "permissions.json"
    monkeypatch.setattr("vantage_agent.permissions._STATE_DIR", state_dir)
    monkeypatch.setattr("vantage_agent.permissions._PERM_FILE", perm_file)
    return PermissionManager()


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
        perm_file = tmp_path / ".vantage-agent" / "permissions.json"
        clean_perms.approve(["Bash"], always=True)
        assert perm_file.exists()
        data = json.loads(perm_file.read_text())
        assert "Bash" in data["always_approved"]

    def test_session_approve_does_not_persist(self, clean_perms, tmp_path):
        perm_file = tmp_path / ".vantage-agent" / "permissions.json"
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
    def test_load_from_persisted_state(self, tmp_path, monkeypatch):
        state_dir = tmp_path / ".vantage-agent"
        state_dir.mkdir()
        perm_file = state_dir / "permissions.json"
        perm_file.write_text(json.dumps({"always_approved": ["Bash", "Write"]}))
        monkeypatch.setattr("vantage_agent.permissions._STATE_DIR", state_dir)
        monkeypatch.setattr("vantage_agent.permissions._PERM_FILE", perm_file)

        pm = PermissionManager()
        assert pm.is_approved("Bash")
        assert pm.is_approved("Write")

    def test_corrupt_file_falls_back_to_defaults(self, tmp_path, monkeypatch):
        state_dir = tmp_path / ".vantage-agent"
        state_dir.mkdir()
        perm_file = state_dir / "permissions.json"
        perm_file.write_text("not json")
        monkeypatch.setattr("vantage_agent.permissions._STATE_DIR", state_dir)
        monkeypatch.setattr("vantage_agent.permissions._PERM_FILE", perm_file)

        pm = PermissionManager()
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
