"""Tests for SetupWizard: tier selection, config.json, apply_tier."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from cohrint_agent.permissions import PermissionManager
from cohrint_agent.setup_wizard import (
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
