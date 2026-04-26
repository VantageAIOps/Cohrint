"""Tests for Phase 4 — init + settings/hooks/permissions writers."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cohrint_agent import writers
from cohrint_agent.commands import init_cmd, hooks, permissions, settings_cmd


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    cwd = tmp_path / "proj"
    home.mkdir()
    cwd.mkdir()
    monkeypatch.setattr(writers, "_home", lambda: home)
    monkeypatch.setattr(writers, "_cwd", lambda: cwd)
    monkeypatch.chdir(cwd)
    return home, cwd


# ─────────────────────────── settings.set ───────────────────────────────

class TestSetSetting:
    def test_flat_key(self, fake_env):
        home, _ = fake_env
        r = writers.set_setting("model", "claude-opus-4-6")
        assert r.ok
        data = json.loads((home / ".claude" / "settings.json").read_text())
        assert data["model"] == "claude-opus-4-6"

    def test_nested_dotted_key(self, fake_env):
        home, _ = fake_env
        writers.set_setting("permissions.defaultMode", "acceptEdits")
        data = json.loads((home / ".claude" / "settings.json").read_text())
        assert data["permissions"]["defaultMode"] == "acceptEdits"

    def test_bool_coercion(self, fake_env):
        home, _ = fake_env
        writers.set_setting("alwaysThinkingEnabled", "true")
        data = json.loads((home / ".claude" / "settings.json").read_text())
        assert data["alwaysThinkingEnabled"] is True

    def test_int_coercion(self, fake_env):
        home, _ = fake_env
        writers.set_setting("cleanupPeriodDays", "14")
        data = json.loads((home / ".claude" / "settings.json").read_text())
        assert data["cleanupPeriodDays"] == 14

    def test_preserves_other_keys(self, fake_env):
        home, _ = fake_env
        settings = home / ".claude" / "settings.json"
        settings.parent.mkdir()
        settings.write_text(json.dumps({"model": "x", "extra": {"deep": 1}}))
        writers.set_setting("theme", "dark")
        data = json.loads(settings.read_text())
        assert data == {"model": "x", "extra": {"deep": 1}, "theme": "dark"}


# ─────────────────────────── hooks ──────────────────────────────────────

class TestHooks:
    def test_add_creates_structure(self, fake_env):
        home, _ = fake_env
        r = writers.add_hook("PostToolUse", "Write|Edit", "prettier --write")
        assert r.ok
        data = json.loads((home / ".claude" / "settings.json").read_text())
        groups = data["hooks"]["PostToolUse"]
        assert groups[0]["matcher"] == "Write|Edit"
        assert groups[0]["hooks"][0]["command"] == "prettier --write"

    def test_add_same_matcher_appends(self, fake_env):
        home, _ = fake_env
        writers.add_hook("PostToolUse", "Write", "a")
        writers.add_hook("PostToolUse", "Write", "b")
        data = json.loads((home / ".claude" / "settings.json").read_text())
        groups = data["hooks"]["PostToolUse"]
        assert len(groups) == 1
        assert len(groups[0]["hooks"]) == 2

    def test_add_different_matcher_new_group(self, fake_env):
        home, _ = fake_env
        writers.add_hook("PostToolUse", "Write", "a")
        writers.add_hook("PostToolUse", "Edit", "b")
        data = json.loads((home / ".claude" / "settings.json").read_text())
        assert len(data["hooks"]["PostToolUse"]) == 2

    def test_invalid_event_rejected(self, fake_env):
        r = writers.add_hook("BogusEvent", "*", "x")
        assert not r.ok
        assert "unknown event" in r.message

    def test_remove_drops_matcher(self, fake_env):
        home, _ = fake_env
        writers.add_hook("PostToolUse", "Write", "keep")
        writers.add_hook("PostToolUse", "Edit", "drop")
        r = writers.remove_hook("PostToolUse", "Edit")
        assert r.ok
        data = json.loads((home / ".claude" / "settings.json").read_text())
        assert len(data["hooks"]["PostToolUse"]) == 1
        assert data["hooks"]["PostToolUse"][0]["matcher"] == "Write"

    def test_remove_cleans_up_empty_event(self, fake_env):
        home, _ = fake_env
        writers.add_hook("PostToolUse", "Write", "x")
        writers.remove_hook("PostToolUse", "Write")
        data = json.loads((home / ".claude" / "settings.json").read_text())
        assert "PostToolUse" not in data.get("hooks", {})


# ─────────────────────────── permissions ────────────────────────────────

class TestPermissions:
    def test_allow(self, fake_env):
        home, _ = fake_env
        r = writers.add_permission("allow", "Bash(npm *)")
        assert r.ok
        data = json.loads((home / ".claude" / "settings.json").read_text())
        assert "Bash(npm *)" in data["permissions"]["allow"]

    def test_deny(self, fake_env):
        home, _ = fake_env
        writers.add_permission("deny", "Bash(rm -rf *)")
        data = json.loads((home / ".claude" / "settings.json").read_text())
        assert "Bash(rm -rf *)" in data["permissions"]["deny"]

    def test_reject_bad_kind(self, fake_env):
        r = writers.add_permission("maybe", "x")
        assert not r.ok

    def test_dedup(self, fake_env):
        writers.add_permission("allow", "X")
        r = writers.add_permission("allow", "X")
        assert not r.ok
        assert "already" in r.message

    def test_remove(self, fake_env):
        home, _ = fake_env
        writers.add_permission("allow", "A")
        writers.add_permission("allow", "B")
        writers.remove_permission("allow", "A")
        data = json.loads((home / ".claude" / "settings.json").read_text())
        assert data["permissions"]["allow"] == ["B"]


# ─────────────────────────── init ───────────────────────────────────────

class TestInit:
    def test_creates_claude_md_if_missing(self, fake_env):
        _, cwd = fake_env
        r = writers.init_project()
        assert r.ok
        md = (cwd / "CLAUDE.md").read_text()
        assert "<!-- cohrint:begin -->" in md
        assert "<!-- cohrint:end -->" in md
        assert (cwd / ".claude" / "settings.local.json").exists()

    def test_appends_block_preserving_prior_content(self, fake_env):
        _, cwd = fake_env
        original = "# Project rules\n\nDon't eat the cookies.\n"
        (cwd / "CLAUDE.md").write_text(original)
        writers.init_project()
        md = (cwd / "CLAUDE.md").read_text()
        assert "Don't eat the cookies." in md
        assert "<!-- cohrint:begin -->" in md

    def test_refuses_re_run_without_force(self, fake_env):
        _, cwd = fake_env
        writers.init_project()
        r = writers.init_project()
        assert not r.ok
        assert "already" in r.message or "--force" in r.message

    def test_force_replaces_block_only(self, fake_env):
        _, cwd = fake_env
        (cwd / "CLAUDE.md").write_text("HEADER\n")
        writers.init_project()
        # user edits CLAUDE.md between runs
        md = (cwd / "CLAUDE.md").read_text()
        (cwd / "CLAUDE.md").write_text(md + "\nUSER EDIT BELOW\n")
        writers.init_project(force=True)
        final = (cwd / "CLAUDE.md").read_text()
        assert "HEADER" in final
        assert "USER EDIT BELOW" in final
        assert final.count("<!-- cohrint:begin -->") == 1

    def test_updates_gitignore_if_present(self, fake_env):
        _, cwd = fake_env
        (cwd / ".gitignore").write_text("node_modules/\n")
        writers.init_project()
        gi = (cwd / ".gitignore").read_text()
        assert ".claude/settings.local.json" in gi

    def test_skips_gitignore_if_absent(self, fake_env):
        _, cwd = fake_env
        writers.init_project()
        assert not (cwd / ".gitignore").exists()


# ─────────────────────────── commands integration ───────────────────────

class TestCommandsIntegration:
    def test_init_cmd_help(self, capsys):
        rc = init_cmd.run(["--help"])
        assert rc == 0
        assert "init" in capsys.readouterr().out.lower()

    def test_hooks_add_cmd(self, fake_env, capsys):
        home, _ = fake_env
        rc = hooks.run(["add", "PostToolUse", "Write", "echo hi"])
        assert rc == 0
        data = json.loads((home / ".claude" / "settings.json").read_text())
        assert data["hooks"]["PostToolUse"][0]["matcher"] == "Write"

    def test_hooks_add_rejects_bad_event(self, fake_env, capsys):
        # argparse choices= raises SystemExit(2) on invalid choice
        with pytest.raises(SystemExit) as exc:
            hooks.run(["add", "NotAnEvent", "*", "x"])
        assert exc.value.code == 2

    def test_permissions_allow_cmd(self, fake_env, capsys):
        home, _ = fake_env
        rc = permissions.run(["allow", "Bash(git *)"])
        assert rc == 0
        data = json.loads((home / ".claude" / "settings.json").read_text())
        assert "Bash(git *)" in data["permissions"]["allow"]

    def test_settings_set_cmd(self, fake_env, capsys):
        home, _ = fake_env
        rc = settings_cmd.run(["set", "model", "claude-opus-4-6"])
        assert rc == 0
        data = json.loads((home / ".claude" / "settings.json").read_text())
        assert data["model"] == "claude-opus-4-6"
