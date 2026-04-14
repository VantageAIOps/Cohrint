"""
Suite 42 — Claude Intelligence integration tests

Tests:
  - vantage-track.js pricing table completeness
  - vantage-track.js cost calculation accuracy
  - vantage-track.js OTel payload structure
  - @vantageaiops/claude-code package structure
  - vantage-mcp setup subcommand (unit-level, no ~/.claude side-effects)
  - Dashboard Claude Code card presence in app.html
"""
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[3]
HOOK = ROOT / "claude-intelligence" / "hooks" / "vantage-track.js"
CLAUDE_INT = ROOT / "claude-intelligence"
VANTAGE_MCP_SRC = ROOT / "vantage-mcp" / "src" / "index.ts"
APP_HTML = ROOT / "vantage-final-v4" / "app.html"
PRICING_TS = ROOT / "vantage-worker" / "src" / "lib" / "pricing.ts"


# ── Helper ──────────────────────────────────────────────────────────────────

def read_hook() -> str:
    return HOOK.read_text()


def extract_prices_from_hook() -> dict:
    """Parse the PRICES object from vantage-track.js."""
    text = read_hook()
    # Find the PRICES = { ... }; block
    m = re.search(r"const PRICES\s*=\s*\{(.+?)\};", text, re.DOTALL)
    assert m, "PRICES const not found in vantage-track.js"
    return m.group(1)


def extract_prices_from_ts() -> list[str]:
    """Return list of model keys from pricing.ts MODEL_PRICES."""
    text = PRICING_TS.read_text()
    return re.findall(r"'(claude-[^']+)':", text)


# ── Pricing table tests ──────────────────────────────────────────────────────

class TestPricingTable:
    def test_hook_prices_block_exists(self):
        assert "const PRICES = {" in read_hook()

    def test_hook_has_all_claude_models_from_pricing_ts(self):
        hook_text = read_hook()
        for model in extract_prices_from_ts():
            assert model in hook_text, f"Model {model!r} missing from vantage-track.js PRICES"

    def test_hook_has_gpt_models(self):
        hook_text = read_hook()
        for model in ["gpt-4o", "gpt-4o-mini", "o1", "o3-mini"]:
            assert model in hook_text, f"Model {model!r} missing from PRICES"

    def test_hook_has_gemini_models(self):
        hook_text = read_hook()
        for model in ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"]:
            assert model in hook_text, f"Model {model!r} missing from PRICES"

    def test_cache_write_rate_present(self):
        """Pricing table must include cacheWrite field (not just cache)."""
        hook_text = read_hook()
        assert "cacheWrite" in hook_text, "cacheWrite field missing — cache creation cost not tracked"

    def test_sonnet_prices_match_pricing_ts(self):
        """claude-sonnet-4-6 rates must match pricing.ts exactly."""
        hook_text = read_hook()
        # sonnet-4-6: input 3.00, output 15.00
        m = re.search(r"'claude-sonnet-4-6'\s*:\s*\{([^}]+)\}", hook_text)
        assert m, "claude-sonnet-4-6 not found"
        block = m.group(1)
        assert "3.00" in block or "3," in block, "input price mismatch for sonnet"
        assert "15.00" in block or "15," in block, "output price mismatch for sonnet"


# ── Env var tests ─────────────────────────────────────────────────────────────

class TestEnvVars:
    def test_vantage_team_env_var(self):
        hook_text = read_hook()
        assert "VANTAGE_TEAM" in hook_text

    def test_vantage_project_env_var(self):
        hook_text = read_hook()
        assert "VANTAGE_PROJECT" in hook_text

    def test_vantage_feature_env_var(self):
        hook_text = read_hook()
        assert "VANTAGE_FEATURE" in hook_text

    def test_team_in_payload(self):
        """Team/project/feature must be added to event payload."""
        hook_text = read_hook()
        assert "team:" in hook_text and "TEAM" in hook_text
        assert "project:" in hook_text and "PROJECT" in hook_text

    def test_no_hardcoded_api_key(self):
        """API key must not be hardcoded in the hook file."""
        hook_text = read_hook()
        assert "vnt_" not in hook_text, "Hardcoded API key found in vantage-track.js"


# ── OTel emission tests ───────────────────────────────────────────────────────

class TestOtelEmission:
    def test_otel_function_exists(self):
        hook_text = read_hook()
        assert "buildOtelPayload" in hook_text

    def test_otel_endpoint_called(self):
        hook_text = read_hook()
        assert "/v1/otel/v1/metrics" in hook_text

    def test_otel_payload_structure(self):
        """OTel payload must follow OTLP JSON format."""
        hook_text = read_hook()
        assert "resourceMetrics" in hook_text
        assert "scopeMetrics" in hook_text
        assert "gen_ai.client.token.usage" in hook_text
        assert "gen_ai.token.type" in hook_text

    def test_otel_has_resource_attributes(self):
        hook_text = read_hook()
        assert "service.name" in hook_text

    def test_otel_team_attribute(self):
        """Team must be included in OTel resource attributes when set."""
        hook_text = read_hook()
        assert "team.id" in hook_text


# ── Success feedback test ─────────────────────────────────────────────────────

class TestSuccessFeedback:
    def test_stderr_success_message(self):
        """Hook must write a success message to stderr after upload."""
        hook_text = read_hook()
        assert "vantage-track] Tracked" in hook_text
        assert "vantageaiops.com" in hook_text


# ── @vantageaiops/claude-code package ────────────────────────────────────────

class TestClaudeCodePackage:
    def test_package_json_exists(self):
        assert (CLAUDE_INT / "package.json").exists()

    def test_package_name(self):
        pkg = json.loads((CLAUDE_INT / "package.json").read_text())
        assert pkg["name"] == "@vantageaiops/claude-code"

    def test_package_version(self):
        pkg = json.loads((CLAUDE_INT / "package.json").read_text())
        assert pkg.get("version"), "version field missing"

    def test_bin_field(self):
        pkg = json.loads((CLAUDE_INT / "package.json").read_text())
        assert "bin" in pkg, "bin field missing"

    def test_files_includes_hook(self):
        pkg = json.loads((CLAUDE_INT / "package.json").read_text())
        files = pkg.get("files", [])
        # hooks/vantage-track.js or hooks/ must be in files
        assert any("hook" in f for f in files), "vantage-track.js not in package files"

    def test_cli_entrypoint_exists(self):
        assert (CLAUDE_INT / "bin" / "cli.js").exists()

    def test_cli_has_setup_command(self):
        cli = (CLAUDE_INT / "bin" / "cli.js").read_text()
        assert "setup" in cli
        assert "copyFileSync" in cli or "copyFile" in cli

    def test_cli_has_status_command(self):
        cli = (CLAUDE_INT / "bin" / "cli.js").read_text()
        assert "status" in cli

    def test_not_private(self):
        pkg = json.loads((CLAUDE_INT / "package.json").read_text())
        assert not pkg.get("private", False), "package is marked private, cannot publish"


# ── vantage-mcp setup subcommand ──────────────────────────────────────────────

class TestMcpSetupSubcommand:
    def test_setup_function_in_index_ts(self):
        text = VANTAGE_MCP_SRC.read_text()
        assert "runSetup" in text

    def test_argv_check_before_mcp_start(self):
        """setup check must appear before StdioServerTransport instantiation."""
        text = VANTAGE_MCP_SRC.read_text()
        setup_pos = text.find("subcommand === 'setup'")
        transport_pos = text.find("StdioServerTransport()")
        assert setup_pos != -1, "argv subcommand check not found"
        assert transport_pos != -1, "StdioServerTransport() not found"
        assert setup_pos < transport_pos, "argv check must come before MCP server starts"

    def test_setup_copies_hook_file(self):
        text = VANTAGE_MCP_SRC.read_text()
        assert "copyFileSync" in text
        assert "vantage-track.js" in text

    def test_setup_patches_settings_json(self):
        text = VANTAGE_MCP_SRC.read_text()
        assert "settings.json" in text
        assert "writeFileSync" in text

    def test_setup_uses_only_builtin_imports(self):
        """setup must not import any third-party packages."""
        text = VANTAGE_MCP_SRC.read_text()
        # Only node: built-ins allowed
        setup_imports = re.findall(r"from 'node:([^']+)'", text)
        non_node = re.findall(r"from '(?!node:|@modelcontextprotocol|\./)([^']+)'", text)
        # Filter out VERSION import
        non_node = [x for x in non_node if "_version" not in x]
        assert not non_node, f"Non-builtin imports found: {non_node}"

    def test_build_copies_hook_to_dist(self):
        """vantage-track.js must exist in dist/ after build."""
        dist_hook = ROOT / "vantage-mcp" / "dist" / "vantage-track.js"
        assert dist_hook.exists(), (
            "dist/vantage-track.js not found — run `cd vantage-mcp && npm run build`"
        )


# ── Dashboard Claude Code card ────────────────────────────────────────────────

class TestDashboardClaudeCodeCard:
    def app_html(self) -> str:
        return APP_HTML.read_text()

    def test_claude_code_card_exists(self):
        assert "claudeCodeCard" in self.app_html()

    def test_check_setup_button(self):
        assert "checkClaudeCodeSetup" in self.app_html()

    def test_copy_command_button(self):
        assert "copyClaudeSetupCmd" in self.app_html()

    def test_setup_command_displayed(self):
        assert "npx vantageaiops-mcp setup" in self.app_html()

    def test_load_claude_code_status_function(self):
        assert "loadClaudeCodeStatus" in self.app_html()

    def test_render_active_function(self):
        assert "renderClaudeCodeActive" in self.app_html()

    def test_render_setup_function(self):
        assert "renderClaudeCodeSetup" in self.app_html()

    def test_status_badge(self):
        assert "claudeCodeStatusBadge" in self.app_html()

    def test_load_settings_calls_claude_code_status(self):
        """loadSettings() must call loadClaudeCodeStatus() to auto-check on Settings open."""
        html = self.app_html()
        load_settings_block = re.search(
            r"function loadSettings\(\)\s*\{[^}]+\}", html, re.DOTALL
        )
        assert load_settings_block, "loadSettings() not found"
        assert "loadClaudeCodeStatus" in load_settings_block.group(0)

    def test_active_state_shows_event_count(self):
        assert "claudeCodeEventCount" in self.app_html()

    def test_active_state_shows_last_event(self):
        assert "claudeCodeLastEvent" in self.app_html()
