"""
Test Suite 26 — CLI Integration Tests (vantage-cli)
=====================================================
Suite CI: Comprehensive integration tests for the VantageAI CLI including
setup flow, slash commands (/summary, /budget, /cost, /compare),
session mode, agent detection, prompt optimization, cost calculation,
config load/save, pipe mode, error handling, and SSE live stream.

Labels: CI.1 - CI.41  (41 checks)
"""

import sys
import json
import shutil
import subprocess
import re
import os
import time
import uuid
import requests
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.output import section, chk, ok, fail, info, get_results, reset_results
from helpers.api import fresh_account, get_headers
from helpers.data import make_event

CLI_DIR = Path(__file__).parent.parent.parent.parent / "vantage-cli"
TSX = CLI_DIR / "node_modules" / ".bin" / "tsx"
HARNESS = CLI_DIR / "test-helpers.ts"


# ── Helpers ──────────────────────────────────────────────────────────────────

def js(cmd: str, *args: str, timeout: int = 10) -> dict:
    """Run test-helpers.ts via tsx and return parsed JSON."""
    result = subprocess.run(
        [str(TSX), str(HARNESS), cmd, *[str(a) for a in args]],
        capture_output=True, text=True, timeout=timeout,
        cwd=str(CLI_DIR),
    )
    try:
        return json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        return {"error": result.stderr, "stdout": result.stdout}


def run_cli(prompt: str, timeout: int = 45) -> tuple:
    """Run vantage CLI in pipe mode."""
    result = subprocess.run(
        ["node", "dist/index.js"],
        input=prompt,
        capture_output=True, text=True, timeout=timeout,
        cwd=str(CLI_DIR),
    )
    return result.stdout, result.stderr, result.returncode


def file_exists(path: Path) -> bool:
    return path.exists() and path.is_file()


# ═══════════════════════════════════════════════════════════════════════════════
#  Section A: Setup Command Flow
# ═══════════════════════════════════════════════════════════════════════════════

class TestSetupFlow:
    """Tests for /setup command and config initialization."""

    def test_ci01_setup_module_exists(self):
        section("A --- Setup Command Flow")
        chk("CI.1 setup.ts source file exists",
            file_exists(CLI_DIR / "src" / "setup.ts"))
        assert file_exists(CLI_DIR / "src" / "setup.ts")

    def test_ci02_config_module_exists(self):
        chk("CI.2 config.ts source file exists",
            file_exists(CLI_DIR / "src" / "config.ts"))
        assert file_exists(CLI_DIR / "src" / "config.ts")

    def test_ci03_default_config_structure(self):
        """Verify the built dist has proper config defaults baked in."""
        dist = CLI_DIR / "dist" / "index.js"
        if not dist.exists():
            pytest.skip("dist not built")
        content = dist.read_text()
        chk("CI.3 default agent is claude", "claude" in content.lower())
        assert "claude" in content.lower()

    def test_ci04_config_dir_convention(self):
        """Config should use ~/.vantage/ convention."""
        dist = CLI_DIR / "dist" / "index.js"
        if not dist.exists():
            pytest.skip("dist not built")
        content = dist.read_text()
        chk("CI.4 uses .vantage config dir", ".vantage" in content)
        assert ".vantage" in content

    def test_ci05_privacy_modes_defined(self):
        """Config should support full, anonymized, strict, local-only."""
        src = (CLI_DIR / "src" / "config.ts").read_text()
        for mode in ["full", "strict", "anonymized", "local-only"]:
            assert mode in src, f"Privacy mode '{mode}' missing from config.ts"
        chk("CI.5 all 4 privacy modes defined in config", True)


# ═══════════════════════════════════════════════════════════════════════════════
#  Section B: Slash Commands (/summary, /budget, /cost, /compare)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSlashCommands:
    """Tests for CLI slash commands."""

    def test_ci06_cost_command_claude(self):
        section("B --- Slash Commands")
        r = js("cost", "claude-sonnet-4-6", "1000", "500")
        chk("CI.6 /cost claude-sonnet-4-6 returns positive cost",
            r.get("totalCostUsd", 0) > 0)
        assert r.get("totalCostUsd", 0) > 0

    def test_ci07_cost_command_gpt4o(self):
        r = js("cost", "gpt-4o", "1000", "500")
        chk("CI.7 /cost gpt-4o returns positive cost",
            r.get("totalCostUsd", 0) > 0)
        assert r.get("totalCostUsd", 0) > 0

    def test_ci08_cost_command_gemini(self):
        r = js("cost", "gemini-2.0-flash", "1000", "500")
        chk("CI.8 /cost gemini-2.0-flash returns positive cost",
            r.get("totalCostUsd", 0) > 0)
        assert r.get("totalCostUsd", 0) > 0

    def test_ci09_cost_command_unknown_model(self):
        r = js("cost", "nonexistent-model-xyz", "1000", "500")
        chk("CI.9 /cost unknown model returns 0",
            r.get("totalCostUsd", 0) == 0)
        assert r.get("totalCostUsd", 0) == 0

    def test_ci10_cost_with_cache_discount(self):
        no_cache = js("cost", "claude-opus-4-6", "10000", "5000", "0")
        with_cache = js("cost", "claude-opus-4-6", "10000", "5000", "5000")
        chk("CI.10 cached tokens reduce total cost",
            with_cache["totalCostUsd"] < no_cache["totalCostUsd"])
        assert with_cache["totalCostUsd"] < no_cache["totalCostUsd"]

    def test_ci11_compare_finds_cheaper(self):
        r = js("cheapest", "claude-opus-4-6", "1000", "500")
        chk("CI.11 /compare finds cheaper model for opus",
            r is not None and r.get("model"))
        assert r is not None and r.get("model")

    def test_ci12_compare_savings_positive(self):
        current = js("cost", "claude-opus-4-6", "1000", "500")
        r = js("cheapest", "claude-opus-4-6", "1000", "500")
        savings = (current.get("totalCostUsd", 0) - r.get("costUsd", 0)) if r else 0
        chk("CI.12 /compare savings > 0 vs opus", savings > 0)
        assert savings > 0

    def test_ci13_models_list(self):
        r = js("models")
        chk("CI.13 models list has 15+ entries", r.get("count", 0) >= 15)
        assert r.get("count", 0) >= 15

    def test_ci14_zero_tokens_zero_cost(self):
        r = js("cost", "gpt-4o", "0", "0")
        chk("CI.14 zero tokens = zero cost", r.get("totalCostUsd", 0) == 0)
        assert r.get("totalCostUsd", 0) == 0

    def test_ci15_cost_proportional_to_tokens(self):
        small = js("cost", "gpt-4o", "100", "50")
        large = js("cost", "gpt-4o", "10000", "5000")
        chk("CI.15 10x tokens ~ 10x cost",
            large["totalCostUsd"] > small["totalCostUsd"] * 5)
        assert large["totalCostUsd"] > small["totalCostUsd"] * 5


# ═══════════════════════════════════════════════════════════════════════════════
#  Section C: Session Mode
# ═══════════════════════════════════════════════════════════════════════════════

class TestSessionMode:
    """Tests for /session mode functionality."""

    def test_ci16_session_module_exists(self):
        section("C --- Session Mode")
        chk("CI.16 session.ts source exists",
            file_exists(CLI_DIR / "src" / "session.ts"))
        assert file_exists(CLI_DIR / "src" / "session.ts")

    def test_ci17_session_mode_module_exists(self):
        chk("CI.17 session-mode.ts source exists",
            file_exists(CLI_DIR / "src" / "session-mode.ts"))
        assert file_exists(CLI_DIR / "src" / "session-mode.ts")

    def test_ci18_session_state_in_source(self):
        src = (CLI_DIR / "src" / "session.ts").read_text()
        chk("CI.18 SessionState interface defined",
            "SessionState" in src)
        assert "SessionState" in src

    def test_ci19_session_tracks_cost(self):
        src = (CLI_DIR / "src" / "session.ts").read_text()
        chk("CI.19 session tracks totalCostUsd",
            "totalCostUsd" in src)
        assert "totalCostUsd" in src

    def test_ci20_session_tracks_tokens(self):
        src = (CLI_DIR / "src" / "session.ts").read_text()
        chk("CI.20 session tracks totalInputTokens",
            "totalInputTokens" in src)
        assert "totalInputTokens" in src


# ═══════════════════════════════════════════════════════════════════════════════
#  Section D: Prompt Optimization
# ═══════════════════════════════════════════════════════════════════════════════

class TestPromptOptimization:
    """Tests for prompt optimization engine."""

    def test_ci21_optimize_empty(self):
        section("D --- Prompt Optimization")
        r = js("optimize", "")
        chk("CI.21 empty prompt returns empty", r.get("optimized", "") == "")
        assert r.get("optimized", "") == ""

    def test_ci22_optimize_removes_filler(self):
        r = js("optimize", "Could you please explain what kubernetes is")
        chk("CI.22 'could you please' removed",
            "could you please" not in r.get("optimized", "").lower())
        assert "could you please" not in r.get("optimized", "").lower()

    def test_ci23_optimize_in_order_to(self):
        r = js("optimize", "In order to deploy we need to configure the cluster")
        chk("CI.23 'in order to' -> 'to'",
            "in order to" not in r.get("optimized", "").lower())
        assert "in order to" not in r.get("optimized", "").lower()

    def test_ci24_optimize_due_to_fact(self):
        r = js("optimize", "Due to the fact that the system is slow we need to fix it")
        chk("CI.24 'due to the fact that' -> 'because'",
            "due to the fact that" not in r.get("optimized", "").lower())
        assert "due to the fact that" not in r.get("optimized", "").lower()

    def test_ci25_optimize_dedup(self):
        r = js("optimize", "The system is fast. The code is clean. The system is fast.")
        chk("CI.25 duplicate sentence removed",
            r.get("optimized", "").lower().count("the system is fast") == 1)
        assert r.get("optimized", "").lower().count("the system is fast") == 1

    def test_ci26_optimize_verbose_savings(self):
        verbose = (
            "I would like you to please analyze the quarterly revenue data. "
            "It is important to note that we need year-over-year growth. "
            "Could you please take into consideration the market trends. "
            "In order to make a decision about our strategy we need patterns."
        )
        r = js("optimize", verbose)
        chk("CI.26 verbose prompt saves 20%+", r.get("savedPercent", 0) >= 20)
        assert r.get("savedPercent", 0) >= 20

    def test_ci27_token_count_short(self):
        r = js("tokens", "hello world")
        chk("CI.27 'hello world' = 2-4 tokens", 1 <= r.get("tokens", 0) <= 4)
        assert 1 <= r.get("tokens", 0) <= 4

    def test_ci28_token_count_paragraph(self):
        text = " ".join(["word"] * 100)
        r = js("tokens", text)
        chk("CI.28 100 words ~ 100 tokens", 90 <= r.get("tokens", 0) <= 120)
        assert 90 <= r.get("tokens", 0) <= 120


# ═══════════════════════════════════════════════════════════════════════════════
#  Section E: Agent Detection
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentDetection:
    """Tests for agent adapter detection and registration."""

    def test_ci29_all_agent_files_exist(self):
        section("E --- Agent Detection")
        agents = ["claude.ts", "codex.ts", "gemini.ts", "aider.ts", "chatgpt.ts"]
        for f in agents:
            assert file_exists(CLI_DIR / "src" / "agents" / f), f"Missing {f}"
        chk("CI.29 all 5 agent adapter files exist", True)

    def test_ci30_registry_exists(self):
        chk("CI.30 registry.ts exists",
            file_exists(CLI_DIR / "src" / "agents" / "registry.ts"))
        assert file_exists(CLI_DIR / "src" / "agents" / "registry.ts")

    def test_ci31_types_exists(self):
        chk("CI.31 types.ts exists",
            file_exists(CLI_DIR / "src" / "agents" / "types.ts"))
        assert file_exists(CLI_DIR / "src" / "agents" / "types.ts")

    def test_ci32_registry_imports_all_agents(self):
        src = (CLI_DIR / "src" / "agents" / "registry.ts").read_text()
        for agent in ["claude", "codex", "gemini", "aider", "chatgpt"]:
            assert f"{agent}Adapter" in src, f"{agent}Adapter missing from registry"
        chk("CI.32 registry imports all 5 agent adapters", True)

    def test_ci33_agent_interface_complete(self):
        src = (CLI_DIR / "src" / "agents" / "types.ts").read_text()
        required = ["name", "displayName", "binary", "defaultModel",
                     "provider", "detect", "buildCommand"]
        for field in required:
            assert field in src, f"AgentAdapter missing '{field}'"
        chk("CI.33 AgentAdapter interface has all required fields", True)


# ═══════════════════════════════════════════════════════════════════════════════
#  Section F: Config & Error Handling
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfigAndErrors:
    """Tests for config load/save and error handling."""

    def test_ci34_package_json_valid(self):
        section("F --- Config & Error Handling")
        pkg = json.loads((CLI_DIR / "package.json").read_text())
        chk("CI.34 package.json is valid JSON", isinstance(pkg, dict))
        assert isinstance(pkg, dict)

    def test_ci35_zero_runtime_deps(self):
        pkg = json.loads((CLI_DIR / "package.json").read_text())
        deps = pkg.get("dependencies", {})
        chk("CI.35 zero runtime dependencies", len(deps) == 0)
        assert len(deps) == 0

    def test_ci36_bin_configured(self):
        pkg = json.loads((CLI_DIR / "package.json").read_text())
        chk("CI.36 bin 'vantage' configured", "vantage" in pkg.get("bin", {}))
        assert "vantage" in pkg.get("bin", {})

    def test_ci37_typecheck_passes(self):
        r = subprocess.run(
            ["npx", "tsc", "--noEmit"],
            capture_output=True, text=True, timeout=30,
            cwd=str(CLI_DIR),
        )
        chk("CI.37 TypeScript typecheck passes", r.returncode == 0)
        assert r.returncode == 0, f"tsc errors: {r.stderr[:500]}"

    def test_ci38_dist_built(self):
        chk("CI.38 dist/index.js exists (built)",
            file_exists(CLI_DIR / "dist" / "index.js"))
        assert file_exists(CLI_DIR / "dist" / "index.js")


# ═══════════════════════════════════════════════════════════════════════════════
#  Section G: SSE Live Stream (KV broadcast path)
# ═══════════════════════════════════════════════════════════════════════════════

class TestLiveSSEStream:
    """
    Verify that events the CLI tracks via POST /v1/events reach the SSE
    live stream (GET /v1/stream/{orgId}).

    The CLI calls broadcastEvent() → KV after each ingested event.
    These tests confirm the full pipeline: ingest → KV broadcast → SSE poll.
    Gap existed for OTel path until fix/otel-live-feed-broadcast.
    """

    def test_ci39_sse_stream_accessible(self, account):
        section("G --- SSE Live Stream (KV broadcast path)")
        api_key, org_id, _ = account
        url = f"{API_URL}/v1/stream/{org_id}?token={api_key}"
        try:
            r = requests.get(url, stream=True, timeout=6)
            chk("CI.39 SSE stream endpoint returns 200", r.status_code == 200,
                f"got {r.status_code}")
            assert r.status_code == 200
        finally:
            try:
                r.close()
            except Exception:
                pass

    def test_ci40_sse_stream_after_cli_event_ingest(self, account):
        """
        CI.40-41: Simulate the vantage-cli event tracking call (POST /v1/events),
        which internally calls broadcastEvent() → KV.  Then poll the SSE stream
        and verify the event is delivered within 10 seconds.
        """
        api_key, org_id, _ = account
        hdrs = get_headers(api_key)

        # Simulate what vantage-cli posts after a Claude Code session
        unique_model = f"claude-sonnet-4-6-cli-{uuid.uuid4().hex[:8]}"
        ev = make_event(i=0, model=unique_model, cost=0.023)
        ev["source"] = "vantage-cli"

        r = requests.post(
            f"{API_URL}/v1/events",
            json=ev,
            headers=hdrs,
            timeout=10,
        )
        chk("CI.40 CLI event ingest returns 200/201", r.status_code in (200, 201),
            f"got {r.status_code}")
        assert r.status_code in (200, 201)

        # Allow KV write to propagate
        time.sleep(2)

        # Poll SSE stream for up to 10 seconds
        stream_url = f"{API_URL}/v1/stream/{org_id}?token={api_key}"
        received = None
        try:
            with requests.get(stream_url, stream=True, timeout=10) as sr:
                chk("CI.41 SSE stream opens after CLI ingest", sr.status_code == 200,
                    f"got {sr.status_code}")
                if sr.status_code != 200:
                    return
                for raw in sr.iter_lines():
                    if not raw:
                        continue
                    line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                    if line.startswith("data:"):
                        try:
                            received = json.loads(line[5:].strip())
                            break
                        except json.JSONDecodeError:
                            continue
        except requests.exceptions.Timeout:
            pass  # No event in window — check below

        chk("CI.41 SSE stream delivers event after CLI ingest",
            received is not None,
            "No data: line received within 10s — KV broadcast may be broken")


# ── Runner ────────────────────────────────────────────────────────────────────

def run():
    reset_results()
    api_key, org_id, cookies = fresh_account(prefix="cli26run")
    acct = (api_key, org_id, cookies)

    for cls in [TestSetupFlow, TestSlashCommands, TestSessionMode,
                TestPromptOptimization, TestAgentDetection, TestConfigAndErrors,
                TestLiveSSEStream]:
        obj = cls()
        for name in sorted(dir(obj)):
            if name.startswith("test_"):
                try:
                    method = getattr(obj, name)
                    import inspect
                    params = inspect.signature(method).parameters
                    if "account" in params:
                        method(account=acct)
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
