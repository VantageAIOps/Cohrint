"""Integration tests for each verb's `run()` entrypoint."""
from __future__ import annotations

import json
from unittest import mock

import pytest

from cohrint_agent.commands import agents, hooks, mcp, models, permissions, plugins
from cohrint_agent.commands import settings_cmd, skills
from cohrint_agent.commands import exec_cmd


@pytest.fixture
def clean_inventory(monkeypatch):
    """Point every scanner at empty dirs so `list` commands show no rows."""
    empty = []
    monkeypatch.setattr("cohrint_agent.inventory.claude.list_mcps", lambda: empty)
    monkeypatch.setattr("cohrint_agent.inventory.claude.list_skills", lambda: empty)
    monkeypatch.setattr("cohrint_agent.inventory.claude.list_agents", lambda: empty)
    monkeypatch.setattr("cohrint_agent.inventory.claude.list_hooks", lambda: empty)
    monkeypatch.setattr("cohrint_agent.inventory.claude.list_permissions", lambda: empty)
    monkeypatch.setattr("cohrint_agent.inventory.claude.list_plugins", lambda: empty)
    monkeypatch.setattr("cohrint_agent.inventory.gemini.list_mcps", lambda: empty)
    monkeypatch.setattr("cohrint_agent.inventory.codex.list_mcps", lambda: empty)
    monkeypatch.setattr("cohrint_agent.inventory.codex.list_agents", lambda: empty)
    monkeypatch.setattr("cohrint_agent.inventory.codex.list_skills", lambda: empty)


class TestModels:
    def test_supported_renders(self, capsys):
        rc = models.run([])
        assert rc == 0
        out = capsys.readouterr().out
        assert "claude-opus-4-6" in out
        assert "gpt-4o" in out
        assert "gemini" in out

    def test_unsupported_flag(self, capsys):
        rc = models.run(["--unsupported"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "gpt-5" in out or "Routable" in out

    def test_info_known(self, capsys):
        rc = models.run(["info", "claude-opus-4-6"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "claude-opus-4-6" in out
        assert "$15" in out  # input price

    def test_info_unknown(self, capsys):
        rc = models.run(["info", "nonexistent-model-xyz"])
        assert rc == 2
        assert "No pricing data" in capsys.readouterr().out

    def test_info_prefix_match(self, capsys):
        # Date-suffixed model should resolve via prefix match (pricing._resolve_model)
        rc = models.run(["info", "claude-opus-4-6-20260101"])
        assert rc == 0


class TestListVerbs:
    @pytest.mark.parametrize("mod,verb", [
        (mcp, "mcp"),
        (plugins, "plugins"),
        (skills, "skills"),
        (agents, "agents"),
        (hooks, "hooks"),
        (permissions, "permissions"),
    ])
    def test_empty_help(self, mod, verb, capsys):
        rc = mod.run([])
        assert rc == 0
        assert verb in capsys.readouterr().out.lower()

    @pytest.mark.parametrize("mod,verb", [
        (mcp, "mcp"),
        (plugins, "plugins"),
        (skills, "skills"),
        (agents, "agents"),
        (hooks, "hooks"),
        (permissions, "permissions"),
    ])
    def test_list_empty(self, mod, verb, clean_inventory, capsys):
        rc = mod.run(["list"])
        assert rc == 0

    @pytest.mark.parametrize("mod", [mcp, plugins, skills, agents, hooks, permissions])
    def test_unknown_subcommand(self, mod, capsys):
        rc = mod.run(["nosuchsub"])
        assert rc == 2

    def test_mcp_list_json(self, clean_inventory, capsys):
        rc = mcp.run(["list", "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        # JSON output should be parseable
        parsed = json.loads(out)
        assert parsed == []

    def test_mcp_list_backend_flag(self, clean_inventory, capsys):
        rc = mcp.run(["list", "--backend", "claude"])
        assert rc == 0


class TestSettings:
    def test_show_help(self, capsys):
        rc = settings_cmd.run([])
        assert rc == 0
        assert "settings" in capsys.readouterr().out.lower()

    def test_show_missing(self, monkeypatch, tmp_path, capsys):
        # Point all scopes at empty dir
        monkeypatch.setattr(settings_cmd, "_home", lambda: tmp_path / "nohome")
        monkeypatch.chdir(tmp_path)
        rc = settings_cmd.run(["show"])
        assert rc == 0
        assert "No settings" in capsys.readouterr().out

    def test_show_merged(self, monkeypatch, tmp_path, capsys):
        home = tmp_path / "home"
        claude_dir = home / ".claude"
        claude_dir.mkdir(parents=True)
        (claude_dir / "settings.json").write_text(json.dumps({"model": "claude-opus-4-6"}))
        project = tmp_path / "proj"
        (project / ".claude").mkdir(parents=True)
        (project / ".claude" / "settings.json").write_text(json.dumps({"editorMode": "vim"}))
        monkeypatch.setattr(settings_cmd, "_home", lambda: home)
        monkeypatch.chdir(project)
        rc = settings_cmd.run(["show"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "claude-opus-4-6" in out
        assert "vim" in out

    def test_unknown_subcommand(self, capsys):
        rc = settings_cmd.run(["bogus"])
        assert rc == 2


class TestExecCmd:
    def test_help(self, capsys):
        rc = exec_cmd.run([])
        assert rc == 0
        assert "exec" in capsys.readouterr().out.lower()

    def test_unknown_backend(self, capsys):
        rc = exec_cmd.run(["bogusback"])
        assert rc == 2
        assert "unknown backend" in capsys.readouterr().err

    def test_missing_binary(self, monkeypatch, capsys):
        monkeypatch.setattr(
            "cohrint_agent.delegate.resolve_backend_binary",
            lambda _name: None,
        )
        rc = exec_cmd.run(["claude", "mcp", "list"])
        assert rc == 127
