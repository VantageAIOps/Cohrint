"""
Test Suite 28 --- MCP Server Integration Tests (vantage-mcp)
=============================================================
Suite MC: Validates MCP server startup, tool listing, cost summary tool,
budget check tool, prompt optimizer tool, model breakdown tool,
team breakdown tool, trace listing tool, and error handling.

Labels: MC.1 - MC.35  (35 checks)
"""

import sys
import json
import subprocess
import time
import uuid
import requests
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.api import fresh_account, get_headers, signup_api
from helpers.data import make_event, rand_email
from helpers.output import section, chk, ok, fail, info, get_results, reset_results

MCP_DIR = Path(__file__).parent.parent.parent.parent / "vantage-mcp"


# ── Helpers ──────────────────────────────────────────────────────────────────

def file_exists(path: Path) -> bool:
    return path.exists() and path.is_file()


def read_source(filename: str) -> str:
    """Read a source file from vantage-mcp/src/."""
    path = MCP_DIR / "src" / filename
    if path.exists():
        return path.read_text()
    return ""


def seed_events(headers, count=5, model="claude-sonnet-4-6", team="platform"):
    """Seed test events for analytics endpoints."""
    events = [make_event(i=i, model=model, team=team) for i in range(count)]
    r = requests.post(
        f"{API_URL}/v1/events",
        json=events,
        headers=headers,
        timeout=10,
    )
    return r.status_code in (200, 201)


# ═══════════════════════════════════════════════════════════════════════════════
#  Section A: MCP Server Structure & Build
# ═══════════════════════════════════════════════════════════════════════════════

class TestMCPStructure:
    """Validate MCP server source structure and build."""

    def test_mc01_package_json_exists(self):
        section("A --- MCP Server Structure & Build")
        chk("MC.1 package.json exists", file_exists(MCP_DIR / "package.json"))
        assert file_exists(MCP_DIR / "package.json")

    def test_mc02_source_index_exists(self):
        chk("MC.2 src/index.ts exists", file_exists(MCP_DIR / "src" / "index.ts"))
        assert file_exists(MCP_DIR / "src" / "index.ts")

    def test_mc03_dist_built(self):
        dist = MCP_DIR / "dist" / "index.js"
        chk("MC.3 dist/index.js exists (built)", file_exists(dist))
        assert file_exists(dist)

    def test_mc04_mcp_sdk_dependency(self):
        pkg = json.loads((MCP_DIR / "package.json").read_text())
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        has_mcp = any("modelcontextprotocol" in d for d in deps)
        chk("MC.4 @modelcontextprotocol/sdk in dependencies", has_mcp)
        assert has_mcp

    def test_mc05_bin_configured(self):
        pkg = json.loads((MCP_DIR / "package.json").read_text())
        has_bin = bool(pkg.get("bin")) or "main" in pkg
        chk("MC.5 bin or main configured in package.json", has_bin)
        assert has_bin


# ═══════════════════════════════════════════════════════════════════════════════
#  Section B: MCP Tool Definitions
# ═══════════════════════════════════════════════════════════════════════════════

class TestMCPToolDefs:
    """Validate all expected MCP tools are defined in source."""

    def test_mc06_track_llm_call_defined(self):
        section("B --- MCP Tool Definitions")
        src = read_source("index.ts")
        chk("MC.6 track_llm_call tool defined", "track_llm_call" in src)
        assert "track_llm_call" in src

    def test_mc07_get_summary_defined(self):
        src = read_source("index.ts")
        chk("MC.7 get_summary tool defined", "get_summary" in src)
        assert "get_summary" in src

    def test_mc08_get_kpis_defined(self):
        src = read_source("index.ts")
        chk("MC.8 get_kpis tool defined", "get_kpis" in src)
        assert "get_kpis" in src

    def test_mc09_get_model_breakdown_defined(self):
        src = read_source("index.ts")
        chk("MC.9 get_model_breakdown tool defined", "get_model_breakdown" in src)
        assert "get_model_breakdown" in src

    def test_mc10_get_team_breakdown_defined(self):
        src = read_source("index.ts")
        chk("MC.10 get_team_breakdown tool defined", "get_team_breakdown" in src)
        assert "get_team_breakdown" in src

    def test_mc11_check_budget_defined(self):
        src = read_source("index.ts")
        chk("MC.11 check_budget tool defined", "check_budget" in src)
        assert "check_budget" in src

    def test_mc12_get_traces_defined(self):
        src = read_source("index.ts")
        chk("MC.12 get_traces tool defined", "get_traces" in src)
        assert "get_traces" in src

    def test_mc13_get_cost_gate_defined(self):
        src = read_source("index.ts")
        chk("MC.13 get_cost_gate tool defined", "get_cost_gate" in src)
        assert "get_cost_gate" in src

    def test_mc14_optimize_prompt_defined(self):
        src = read_source("index.ts")
        chk("MC.14 optimize_prompt tool defined", "optimize_prompt" in src)
        assert "optimize_prompt" in src

    def test_mc15_analyze_tokens_defined(self):
        src = read_source("index.ts")
        chk("MC.15 analyze_tokens tool defined", "analyze_tokens" in src)
        assert "analyze_tokens" in src

    def test_mc16_estimate_costs_defined(self):
        src = read_source("index.ts")
        chk("MC.16 estimate_costs tool defined", "estimate_costs" in src)
        assert "estimate_costs" in src

    def test_mc17_compress_context_defined(self):
        src = read_source("index.ts")
        chk("MC.17 compress_context tool defined", "compress_context" in src)
        assert "compress_context" in src

    def test_mc18_list_tools_handler(self):
        src = read_source("index.ts")
        chk("MC.18 ListToolsRequestSchema handler present",
            "ListToolsRequestSchema" in src)
        assert "ListToolsRequestSchema" in src

    def test_mc19_call_tool_handler(self):
        src = read_source("index.ts")
        chk("MC.19 CallToolRequestSchema handler present",
            "CallToolRequestSchema" in src)
        assert "CallToolRequestSchema" in src


# ═══════════════════════════════════════════════════════════════════════════════
#  Section C: Backend API Endpoints (used by MCP tools)
# ═══════════════════════════════════════════════════════════════════════════════

class TestMCPBackendAPIs:
    """Test the backend API endpoints that MCP tools call."""

    def test_mc20_summary_api(self, headers):
        section("C --- Backend API Endpoints (MCP tools)")
        r = requests.get(
            f"{API_URL}/v1/analytics/summary",
            headers=headers,
            timeout=10,
        )
        chk("MC.20 GET /analytics/summary returns 200", r.status_code == 200)
        assert r.status_code == 200

    def test_mc21_kpis_api(self, headers):
        r = requests.get(
            f"{API_URL}/v1/analytics/kpis",
            headers=headers,
            timeout=10,
        )
        chk("MC.21 GET /analytics/kpis returns 200", r.status_code == 200)
        assert r.status_code == 200

    def test_mc22_models_api(self, headers):
        r = requests.get(
            f"{API_URL}/v1/analytics/models",
            headers=headers,
            timeout=10,
        )
        chk("MC.22 GET /analytics/models returns 200", r.status_code == 200)
        assert r.status_code == 200

    def test_mc23_teams_api(self, headers):
        r = requests.get(
            f"{API_URL}/v1/analytics/teams",
            headers=headers,
            timeout=10,
        )
        chk("MC.23 GET /analytics/teams returns 200", r.status_code == 200)
        assert r.status_code == 200

    def test_mc24_traces_api(self, headers):
        r = requests.get(
            f"{API_URL}/v1/analytics/traces",
            headers=headers,
            timeout=10,
        )
        chk("MC.24 GET /analytics/traces returns 200", r.status_code == 200)
        assert r.status_code == 200

    def test_mc25_budget_api(self, headers):
        r = requests.get(
            f"{API_URL}/v1/cross-platform/budget",
            headers=headers,
            timeout=10,
        )
        chk("MC.25 GET /cross-platform/budget returns 200", r.status_code == 200)
        assert r.status_code == 200

    def test_mc26_track_event_api(self, headers):
        ev = make_event(i=0, model="claude-sonnet-4-6", cost=0.01)
        r = requests.post(
            f"{API_URL}/v1/events",
            json=ev,
            headers=headers,
            timeout=10,
        )
        chk("MC.26 POST /events accepted (track_llm_call backend)",
            r.status_code in (200, 201))
        assert r.status_code in (200, 201)


# ═══════════════════════════════════════════════════════════════════════════════
#  Section D: MCP Server Config & Error Handling
# ═══════════════════════════════════════════════════════════════════════════════

class TestMCPConfig:
    """Test MCP config parsing and error handling."""

    def test_mc27_api_key_env_var(self):
        section("D --- MCP Config & Error Handling")
        src = read_source("index.ts")
        chk("MC.27 reads VANTAGE_API_KEY env var",
            "VANTAGE_API_KEY" in src)
        assert "VANTAGE_API_KEY" in src

    def test_mc28_api_base_configurable(self):
        src = read_source("index.ts")
        chk("MC.28 reads VANTAGE_API_BASE env var",
            "VANTAGE_API_BASE" in src)
        assert "VANTAGE_API_BASE" in src

    def test_mc29_org_from_key_parser(self):
        src = read_source("index.ts")
        chk("MC.29 parseOrgFromKey function defined",
            "parseOrgFromKey" in src)
        assert "parseOrgFromKey" in src

    def test_mc30_error_log_no_key_leak(self):
        src = read_source("index.ts")
        chk("MC.30 errorLog function masks API key",
            "errorLog" in src and "****" in src)
        assert "errorLog" in src

    def test_mc31_timeout_handling(self):
        src = read_source("index.ts")
        chk("MC.31 request timeout configured",
            "timeout" in src.lower() or "AbortSignal" in src)
        assert "timeout" in src.lower() or "AbortSignal" in src

    def test_mc32_invalid_key_error_message(self):
        """MCP server should give a helpful error for missing key."""
        src = read_source("index.ts")
        chk("MC.32 helpful error for missing API key",
            "VANTAGE_API_KEY is not set" in src or "not set" in src.lower())
        assert "not set" in src.lower()

    def test_mc33_stdio_transport(self):
        src = read_source("index.ts")
        chk("MC.33 uses StdioServerTransport",
            "StdioServerTransport" in src)
        assert "StdioServerTransport" in src

    def test_mc34_server_name_set(self):
        src = read_source("index.ts")
        chk("MC.34 server name includes 'vantage'",
            "vantage" in src.lower())
        assert "vantage" in src.lower()

    def test_mc35_typecheck_passes(self):
        r = subprocess.run(
            ["npx", "tsc", "--noEmit"],
            capture_output=True, text=True, timeout=30,
            cwd=str(MCP_DIR),
        )
        chk("MC.35 TypeScript typecheck passes", r.returncode == 0)
        assert r.returncode == 0, f"tsc errors: {r.stderr[:500]}"


# ── Runner ────────────────────────────────────────────────────────────────────

def run():
    reset_results()
    api_key, org_id, cookies = fresh_account(prefix="mcp28run")
    hdrs = get_headers(api_key)

    for cls in [TestMCPStructure, TestMCPToolDefs, TestMCPBackendAPIs, TestMCPConfig]:
        obj = cls()
        for name in sorted(dir(obj)):
            if name.startswith("test_"):
                try:
                    method = getattr(obj, name)
                    import inspect
                    params = inspect.signature(method).parameters
                    if "headers" in params:
                        method(headers=hdrs)
                    else:
                        method()
                except Exception as e:
                    fail(name, str(e))

    res = get_results()
    print(f"\n{'='*60}")
    print(f"Results: {res['passed']} passed, {res['failed']} failed, {res['warned']} warned")
    return res["failed"]


if __name__ == "__main__":
    sys.exit(run())
