"""Tests for cohrint_agent.writers — config-mutation side of the CLI."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from cohrint_agent import writers


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    """Redirect writer HOME + cwd to tmp dirs. Returns (home, cwd)."""
    home = tmp_path / "home"
    cwd = tmp_path / "proj"
    home.mkdir()
    cwd.mkdir()
    monkeypatch.setattr(writers, "_home", lambda: home)
    monkeypatch.setattr(writers, "_cwd", lambda: cwd)
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))
    return home, cwd


# ─────────────────────────────── MCP ────────────────────────────────────

class TestMcpClaude:
    def test_add_creates_file(self, fake_env):
        home, _ = fake_env
        r = writers.add_mcp("weather", backend="claude", command="npx", args=["-y", "weather"])
        assert r.ok
        data = json.loads((home / ".claude.json").read_text())
        assert data["mcpServers"]["weather"]["command"] == "npx"
        assert data["mcpServers"]["weather"]["args"] == ["-y", "weather"]

    def test_add_merges_into_existing(self, fake_env):
        home, _ = fake_env
        (home / ".claude.json").write_text(json.dumps({
            "otherKey": "keepme",
            "mcpServers": {"existing": {"command": "x"}},
        }))
        writers.add_mcp("new", backend="claude", command="y")
        data = json.loads((home / ".claude.json").read_text())
        assert data["otherKey"] == "keepme"
        assert set(data["mcpServers"]) == {"existing", "new"}

    def test_add_requires_command_or_url(self, fake_env):
        r = writers.add_mcp("blank", backend="claude")
        assert not r.ok
        assert "required" in r.message

    def test_remove_deletes(self, fake_env):
        home, _ = fake_env
        (home / ".claude.json").write_text(json.dumps({
            "mcpServers": {"foo": {"command": "x"}, "bar": {"command": "y"}},
        }))
        r = writers.remove_mcp("foo", backend="claude")
        assert r.ok
        data = json.loads((home / ".claude.json").read_text())
        assert "foo" not in data["mcpServers"]
        assert "bar" in data["mcpServers"]

    def test_remove_missing_is_error(self, fake_env):
        r = writers.remove_mcp("ghost", backend="claude")
        assert not r.ok
        assert "not found" in r.message


class TestMcpGemini:
    def test_add_writes_gemini_settings(self, fake_env):
        home, _ = fake_env
        r = writers.add_mcp("foo", backend="gemini", command="./run")
        assert r.ok
        data = json.loads((home / ".gemini" / "settings.json").read_text())
        assert data["mcpServers"]["foo"]["command"] == "./run"

    def test_remove_gemini(self, fake_env):
        home, _ = fake_env
        target = home / ".gemini" / "settings.json"
        target.parent.mkdir()
        target.write_text(json.dumps({"mcpServers": {"x": {"command": "q"}}}))
        assert writers.remove_mcp("x", backend="gemini").ok


class TestMcpCodex:
    def test_add_appends_toml_block(self, fake_env, tmp_path):
        home, _ = fake_env
        r = writers.add_mcp("srv", backend="codex", command="./srv", args=["--port", "3000"])
        assert r.ok
        toml = (home / ".codex" / "config.toml").read_text()
        assert "[mcp_servers.srv]" in toml
        assert '"--port"' in toml
        assert '"3000"' in toml

    def test_remove_strips_section(self, fake_env):
        home, _ = fake_env
        (home / ".codex").mkdir()
        (home / ".codex" / "config.toml").write_text(
            '[mcp_servers.keep]\ncommand = "a"\n\n[mcp_servers.drop]\ncommand = "b"\n\n[other]\nx = 1\n'
        )
        r = writers.remove_mcp("drop", backend="codex")
        assert r.ok
        toml = (home / ".codex" / "config.toml").read_text()
        assert "mcp_servers.keep" in toml
        assert "mcp_servers.drop" not in toml
        assert "[other]" in toml  # untouched


# ─────────────────────────────── plugins ────────────────────────────────

class TestPlugins:
    def test_enable_creates_settings(self, fake_env):
        home, _ = fake_env
        r = writers.toggle_plugin("foo@mkt", enabled=True)
        assert r.ok
        data = json.loads((home / ".claude" / "settings.json").read_text())
        assert data["enabledPlugins"]["foo@mkt"] is True

    def test_disable_updates_existing(self, fake_env):
        home, _ = fake_env
        settings = home / ".claude" / "settings.json"
        settings.parent.mkdir()
        settings.write_text(json.dumps({"enabledPlugins": {"foo@mkt": True, "bar": True}}))
        writers.toggle_plugin("foo@mkt", enabled=False)
        data = json.loads(settings.read_text())
        assert data["enabledPlugins"]["foo@mkt"] is False
        assert data["enabledPlugins"]["bar"] is True


# ─────────────────────────────── skills ─────────────────────────────────

class TestSkills:
    def test_add_claude_skill_copies_dir(self, fake_env, tmp_path):
        home, _ = fake_env
        src = tmp_path / "myskill"
        src.mkdir()
        (src / "SKILL.md").write_text("---\nname: myskill\n---\n")
        r = writers.add_skill(str(src), backend="claude")
        assert r.ok
        dest = home / ".claude" / "skills" / "myskill" / "SKILL.md"
        assert dest.exists()

    def test_add_refuses_when_dest_exists(self, fake_env, tmp_path):
        home, _ = fake_env
        src = tmp_path / "skill"
        src.mkdir()
        (home / ".claude" / "skills" / "skill").mkdir(parents=True)
        r = writers.add_skill(str(src), backend="claude")
        assert not r.ok

    def test_add_gemini_errors(self, fake_env, tmp_path):
        r = writers.add_skill(str(tmp_path), backend="gemini")
        assert not r.ok

    def test_add_codex_rule_from_file(self, fake_env, tmp_path):
        home, _ = fake_env
        src = tmp_path / "fmt.md"
        src.write_text("rule")
        r = writers.add_skill(str(src), backend="codex")
        assert r.ok
        assert (home / ".codex" / "rules" / "fmt.md").exists()

    def test_remove_claude_skill(self, fake_env):
        home, _ = fake_env
        target = home / ".claude" / "skills" / "gone"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("x")
        r = writers.remove_skill("gone", backend="claude")
        assert r.ok
        assert not target.exists()

    def test_remove_missing(self, fake_env):
        r = writers.remove_skill("ghost", backend="claude")
        assert not r.ok


# ─────────────────────────────── agents ─────────────────────────────────

class TestAgents:
    def test_add_copies_md(self, fake_env, tmp_path):
        home, _ = fake_env
        src = tmp_path / "reviewer.md"
        src.write_text("# Reviewer")
        r = writers.add_agent(str(src))
        assert r.ok
        assert (home / ".claude" / "agents" / "reviewer.md").exists()

    def test_add_rejects_non_md(self, fake_env, tmp_path):
        src = tmp_path / "x.txt"
        src.write_text("hi")
        r = writers.add_agent(str(src))
        assert not r.ok

    def test_remove_agent(self, fake_env):
        home, _ = fake_env
        target = home / ".claude" / "agents" / "deleteme.md"
        target.parent.mkdir(parents=True)
        target.write_text("# Old")
        r = writers.remove_agent("deleteme")
        assert r.ok
        assert not target.exists()


# ─────────────────────────────── atomic write ───────────────────────────

class TestAtomicity:
    def test_tmp_file_cleaned_up_on_success(self, fake_env):
        home, _ = fake_env
        writers.add_mcp("a", backend="claude", command="x")
        # No stray .tmp files should remain
        assert not list(home.glob(".claude.json.*.tmp"))

    def test_preserves_sibling_keys(self, fake_env):
        home, _ = fake_env
        (home / ".claude.json").write_text(json.dumps({
            "unrelated": {"deep": {"value": 42}},
            "mcpServers": {},
        }))
        writers.add_mcp("x", backend="claude", command="y")
        data = json.loads((home / ".claude.json").read_text())
        assert data["unrelated"]["deep"]["value"] == 42

    def test_preserves_insertion_order(self, fake_env):
        """Round-trip must not reorder keys (sort_keys regression guard)."""
        home, _ = fake_env
        original = {"zz": 1, "aa": 2, "mcpServers": {}}
        (home / ".claude.json").write_text(json.dumps(original, indent=2))
        writers.add_mcp("m", backend="claude", command="x")
        writers.remove_mcp("m", backend="claude")
        data = json.loads((home / ".claude.json").read_text())
        assert list(data.keys()) == ["zz", "aa", "mcpServers"]

    def test_preserves_file_mode(self, fake_env):
        home, _ = fake_env
        target = home / ".claude.json"
        target.write_text(json.dumps({"mcpServers": {}}))
        os.chmod(target, 0o600)
        writers.add_mcp("x", backend="claude", command="y")
        assert (target.stat().st_mode & 0o777) == 0o600

    def test_rejects_tmp_symlink(self, fake_env):
        """Pre-planted symlink at tmp path must be refused (S4)."""
        home, _ = fake_env
        target = home / ".claude.json"
        target.write_text(json.dumps({"mcpServers": {}}))
        # Plant a symlink at the exact tmp path the writer will try to use
        tmp = target.with_suffix(target.suffix + f".cohrint.{os.getpid()}.tmp")
        decoy = home / "decoy"
        decoy.write_text("safe")
        try:
            os.symlink(str(decoy), str(tmp))
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unsupported on this filesystem")
        # Writer should raise rather than follow the symlink into `decoy`.
        with pytest.raises(OSError):
            writers.add_mcp("x", backend="claude", command="y")
        assert decoy.read_text() == "safe"


# ─────────────────────────── security guards ────────────────────────────

class TestSecurityGuards:
    def test_rejects_unsafe_mcp_name_toml_injection(self, fake_env):
        r = writers.add_mcp("x]\n[evil", backend="codex", command="q")
        assert not r.ok
        assert "name" in r.message

    def test_rejects_unsafe_mcp_name_claude(self, fake_env):
        r = writers.add_mcp("has space", backend="claude", command="q")
        assert not r.ok
        assert "name" in r.message

    def test_toml_escapes_quotes_in_command(self, fake_env):
        home, _ = fake_env
        writers.add_mcp("ok", backend="codex", command='say "hi"')
        toml = (home / ".codex" / "config.toml").read_text()
        # The embedded quote must be escaped — not break the TOML string
        assert '\\"hi\\"' in toml

    def test_codex_home_outside_home_rejected(self, fake_env, tmp_path, monkeypatch):
        rogue = tmp_path / "rogue"
        rogue.mkdir()
        monkeypatch.setenv("CODEX_HOME", str(rogue))
        writers.add_mcp("safe", backend="codex", command="q")
        # Write should have landed under the real HOME (~/.codex), not rogue
        assert not (rogue / "config.toml").exists()
        home, _ = fake_env
        assert (home / ".codex" / "config.toml").exists()


# ─────────────────────── nested TOML sub-tables ─────────────────────────

class TestCodexNestedSubtables:
    def test_remove_strips_nested_subtable(self, fake_env):
        home, _ = fake_env
        (home / ".codex").mkdir()
        (home / ".codex" / "config.toml").write_text(
            '[mcp_servers.srv]\ncommand = "x"\n\n'
            '[mcp_servers.srv.env]\nFOO = "bar"\n\n'
            '[mcp_servers.keep]\ncommand = "y"\n'
        )
        r = writers.remove_mcp("srv", backend="codex")
        assert r.ok
        toml = (home / ".codex" / "config.toml").read_text()
        assert "mcp_servers.srv" not in toml
        assert "FOO" not in toml  # sub-table keys must be gone too
        assert "mcp_servers.keep" in toml


# ─────────────────────────── dedup guards ───────────────────────────────

class TestDedup:
    def test_hook_dedup_same_command(self, fake_env):
        writers.add_hook("PreToolUse", "Bash", "log.sh")
        r = writers.add_hook("PreToolUse", "Bash", "log.sh")
        assert not r.ok
        assert "already" in r.message.lower()

    def test_hook_allows_different_command(self, fake_env):
        writers.add_hook("PreToolUse", "Bash", "a.sh")
        r = writers.add_hook("PreToolUse", "Bash", "b.sh")
        assert r.ok

    def test_permission_cross_bucket_rejected(self, fake_env):
        writers.add_permission("allow", "Bash(rm *)")
        r = writers.add_permission("deny", "Bash(rm *)")
        assert not r.ok
        assert "already" in r.message.lower()


# ─────────────────────────────── init --force ───────────────────────────

class TestInitForceIdempotent:
    def test_force_collapses_duplicate_blocks(self, fake_env):
        """A file with two stacked begin/end blocks should collapse to one."""
        _, cwd = fake_env
        md = cwd / "CLAUDE.md"
        md.write_text(
            "# Proj\n\n"
            f"{writers.COHRINT_BEGIN}\nold1\n{writers.COHRINT_END}\n\n"
            f"{writers.COHRINT_BEGIN}\nold2\n{writers.COHRINT_END}\n"
        )
        r = writers.init_project(force=True)
        assert r.ok
        text = md.read_text()
        # Exactly one begin/end pair after force
        assert text.count(writers.COHRINT_BEGIN) == 1
        assert text.count(writers.COHRINT_END) == 1
        assert "old1" not in text and "old2" not in text
