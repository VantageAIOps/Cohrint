"""Tests for cohrint_agent.inventory scanners (claude, gemini, codex)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from cohrint_agent.inventory import Resource, scan


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Redirect the inventory scanners' HOME to a tmp dir."""
    home = tmp_path / "home"
    home.mkdir()
    # _home() uses pwd.getpwuid — patch at the module level instead.
    for mod in ("cohrint_agent.inventory.claude",
                "cohrint_agent.inventory.gemini",
                "cohrint_agent.inventory.codex"):
        monkeypatch.setattr(f"{mod}._home", lambda h=home: h)
    return home


@pytest.fixture
def fake_cwd(tmp_path, monkeypatch):
    cwd = tmp_path / "project"
    cwd.mkdir()
    for mod in ("cohrint_agent.inventory.claude",
                "cohrint_agent.inventory.gemini",
                "cohrint_agent.inventory.codex"):
        monkeypatch.setattr(f"{mod}._cwd", lambda c=cwd: c)
    return cwd


# ─────────── Claude ───────────

class TestClaudeInventory:
    def test_mcp_list_global(self, fake_home, fake_cwd):
        (fake_home / ".claude.json").write_text(json.dumps({
            "mcpServers": {
                "weather": {"command": "npx", "args": ["-y", "weather-mcp"]},
                "remote":  {"url": "https://mcp.example.com"},
            }
        }))
        resources = scan("mcp", backend="claude")
        names = {r.name for r in resources}
        assert names == {"weather", "remote"}
        weather = next(r for r in resources if r.name == "weather")
        assert weather.scope == "global"
        assert weather.backend == "claude"
        assert "weather-mcp" in weather.detail.get("args", "")

    def test_mcp_project_scope(self, fake_home, fake_cwd):
        (fake_cwd / ".claude.json").write_text(json.dumps({
            "mcpServers": {"localsrv": {"command": "./bin/srv"}}
        }))
        resources = scan("mcp", backend="claude")
        localsrv = next(r for r in resources if r.name == "localsrv")
        assert localsrv.scope == "project"

    def test_missing_files_empty_result(self, fake_home, fake_cwd):
        assert scan("mcp", backend="claude") == []
        assert scan("skill", backend="claude") == []
        assert scan("agent", backend="claude") == []
        assert scan("hook", backend="claude") == []

    def test_malformed_json_no_crash(self, fake_home, fake_cwd):
        (fake_home / ".claude.json").write_text("{not valid json")
        assert scan("mcp", backend="claude") == []

    def test_skills_dir(self, fake_home, fake_cwd):
        skills_dir = fake_home / ".claude" / "skills"
        weather = skills_dir / "weather"
        weather.mkdir(parents=True)
        (weather / "SKILL.md").write_text("""---
name: weather
description: Get weather data.
---
""")
        resources = scan("skill", backend="claude")
        assert len(resources) == 1
        assert resources[0].name == "weather"
        assert "weather data" in resources[0].detail.get("description", "").lower()

    def test_agents_files(self, fake_home, fake_cwd):
        agents_dir = fake_home / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "reviewer.md").write_text("# Reviewer")
        (agents_dir / "not_md.txt").write_text("ignored")
        resources = scan("agent", backend="claude")
        names = {r.name for r in resources}
        assert names == {"reviewer"}

    def test_hooks_parsed(self, fake_home, fake_cwd):
        (fake_home / ".claude").mkdir()
        (fake_home / ".claude" / "settings.json").write_text(json.dumps({
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "Write|Edit",
                        "hooks": [{"type": "command", "command": "prettier --write"}],
                    }
                ]
            }
        }))
        resources = scan("hook", backend="claude")
        assert len(resources) == 1
        assert resources[0].detail["event"] == "PostToolUse"
        assert resources[0].detail["matcher"] == "Write|Edit"

    def test_permissions_parsed(self, fake_home, fake_cwd):
        (fake_home / ".claude").mkdir()
        (fake_home / ".claude" / "settings.json").write_text(json.dumps({
            "permissions": {"allow": ["Bash(npm *)"], "deny": ["Bash(rm *)"]}
        }))
        resources = scan("permission", backend="claude")
        kinds = {r.detail["kind"] for r in resources}
        assert kinds == {"allow", "deny"}

    def test_plugins_enabled_map(self, fake_home, fake_cwd):
        (fake_home / ".claude").mkdir()
        (fake_home / ".claude" / "settings.json").write_text(json.dumps({
            "enabledPlugins": {"foo@market": True, "bar@market": False}
        }))
        resources = scan("plugin", backend="claude")
        enabled = {r.name: r.enabled for r in resources}
        assert enabled == {"foo@market": True, "bar@market": False}


# ─────────── Gemini ───────────

class TestGeminiInventory:
    def test_gemini_mcp(self, fake_home, fake_cwd):
        (fake_home / ".gemini").mkdir()
        (fake_home / ".gemini" / "settings.json").write_text(json.dumps({
            "mcpServers": {"foo": {"command": "./run"}}
        }))
        resources = scan("mcp", backend="gemini")
        assert len(resources) == 1
        assert resources[0].backend == "gemini"

    def test_gemini_no_skills_agents_plugins(self, fake_home, fake_cwd):
        assert scan("skill", backend="gemini") == []
        assert scan("agent", backend="gemini") == []
        assert scan("plugin", backend="gemini") == []


# ─────────── Codex (TOML) ───────────

class TestCodexInventory:
    def test_codex_home_override(self, fake_home, fake_cwd, monkeypatch, tmp_path):
        alt = tmp_path / "alt_codex"
        alt.mkdir()
        (alt / "config.toml").write_text('[mcp_servers.foo]\ncommand = "./run"\n')
        monkeypatch.setenv("CODEX_HOME", str(alt))
        resources = scan("mcp", backend="codex")
        names = {r.name for r in resources}
        assert "foo" in names

    def test_codex_agents_md_sections(self, fake_home, fake_cwd):
        codex_dir = fake_home / ".codex"
        codex_dir.mkdir()
        (codex_dir / "AGENTS.md").write_text("""# Global

## Reviewer
Reviews code.

## Debugger
Finds bugs.
""")
        resources = scan("agent", backend="codex")
        names = {r.name for r in resources}
        assert names == {"Reviewer", "Debugger"}

    def test_codex_agents_md_no_sections(self, fake_home, fake_cwd):
        codex_dir = fake_home / ".codex"
        codex_dir.mkdir()
        (codex_dir / "AGENTS.md").write_text("Flat instructions, no headers.")
        resources = scan("agent", backend="codex")
        assert len(resources) == 1
        assert resources[0].name == "AGENTS.md"

    def test_codex_rules_as_skills(self, fake_home, fake_cwd):
        rules = fake_home / ".codex" / "rules"
        rules.mkdir(parents=True)
        (rules / "formatting.md").write_text("rule")
        resources = scan("skill", backend="codex")
        names = {r.name for r in resources}
        assert "formatting" in names

    def test_codex_plugins_always_empty(self, fake_home, fake_cwd):
        assert scan("plugin", backend="codex") == []

    def test_codex_malformed_toml_no_crash(self, fake_home, fake_cwd):
        codex_dir = fake_home / ".codex"
        codex_dir.mkdir()
        (codex_dir / "config.toml").write_text("not [valid toml")
        assert scan("mcp", backend="codex") == []


# ─────────── unified scan ───────────

class TestUnifiedScan:
    def test_scan_all_merges_backends(self, fake_home, fake_cwd):
        (fake_home / ".claude.json").write_text(json.dumps({
            "mcpServers": {"claude_mcp": {"command": "x"}}
        }))
        (fake_home / ".gemini").mkdir()
        (fake_home / ".gemini" / "settings.json").write_text(json.dumps({
            "mcpServers": {"gemini_mcp": {"command": "y"}}
        }))
        resources = scan("mcp", backend="all")
        names = {r.name for r in resources}
        assert "claude_mcp" in names
        assert "gemini_mcp" in names

    def test_scan_result_is_resource_instances(self, fake_home, fake_cwd):
        (fake_home / ".claude.json").write_text(json.dumps({
            "mcpServers": {"foo": {"command": "x"}}
        }))
        resources = scan("mcp", backend="claude")
        for r in resources:
            assert isinstance(r, Resource)
