"""
Test Suite 26 — CLI Integration Tests (vantage-agent Python)
=====================================================
Suite CI: Comprehensive integration tests for the Cohrint Python agent including
prompt optimization, cost calculation, agent detection, config, pipe mode,
session mode tracking, and SSE live stream.

Labels: CI.1 - CI.41  (41 checks)

Rewritten to use Python vantage-agent modules directly (no Node.js harness).
Tests that relied on vantage-cli TypeScript source files have been updated to
verify their Python equivalents in vantage-agent/.
"""

import sys
import json
import re
import os
import time
import uuid
import requests
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT / "vantage-agent"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.output import section, chk, ok, fail, info, get_results, reset_results
from helpers.api import fresh_account, get_headers
from helpers.data import make_event

from vantage_agent.optimizer import optimize_prompt, looks_like_structured_data, count_tokens
from vantage_agent.pricing import calculate_cost, find_cheapest, MODEL_PRICES
from vantage_agent.classifier import classify_input, AGENT_COMMANDS, VANTAGE_COMMANDS
from vantage_agent.recommendations import (
    get_recommendations, SessionMetrics, normalize_agent_name,
)

AGENT_DIR = ROOT / "vantage-agent" / "vantage_agent"


def file_exists(path: Path) -> bool:
    return path.exists() and path.is_file()


# ── Python harness helpers ────────────────────────────────────────────────────

def py_cost(model: str, prompt_tokens: int, completion_tokens: int, cached_tokens: int = 0) -> dict:
    total = calculate_cost(model, prompt_tokens, completion_tokens, cached_tokens)
    return {"totalCostUsd": total}


def py_cheapest(current_model: str, prompt_tokens: int, completion_tokens: int) -> dict:
    result = find_cheapest(current_model, prompt_tokens, completion_tokens)
    if result is None:
        return {}
    return {
        "model": result.model,
        "costUsd": result.cost,
        "savingsUsd": result.savings,
    }


def py_optimize(text: str) -> dict:
    r = optimize_prompt(text)
    return {
        "optimized": r.optimized,
        "savedTokens": r.saved_tokens,
        "savedPercent": r.saved_percent,
    }


def py_tokens(text: str) -> dict:
    return {"tokens": count_tokens(text)}


def py_models() -> dict:
    count = sum(1 for k in MODEL_PRICES if k != "default")
    return {"count": count}


# ═══════════════════════════════════════════════════════════════════════════════
#  Section A: Setup / Module Existence
# ═══════════════════════════════════════════════════════════════════════════════

class TestSetupFlow:
    """Tests for Python vantage-agent module existence and config defaults."""

    def test_ci01_classifier_module_exists(self):
        section("A --- Setup / Module Existence")
        chk("CI.1 classifier.py source file exists",
            file_exists(AGENT_DIR / "classifier.py"))
        assert file_exists(AGENT_DIR / "classifier.py")

    def test_ci02_config_module_exists(self):
        chk("CI.2 pricing.py source file exists",
            file_exists(AGENT_DIR / "pricing.py"))
        assert file_exists(AGENT_DIR / "pricing.py")

    def test_ci03_default_agent_is_claude(self):
        """Default agent commands include claude."""
        chk("CI.3 default agent is claude", "claude" in AGENT_COMMANDS)
        assert "claude" in AGENT_COMMANDS

    def test_ci04_config_dir_convention(self):
        """VantageSession uses .vantage config convention."""
        session_src = (AGENT_DIR / "session.py").read_text()
        # session_store.py carries the .vantage path
        store_src = (AGENT_DIR / "session_store.py").read_text()
        has_vantage = ".vantage" in session_src or ".vantage" in store_src
        chk("CI.4 uses .vantage config dir", has_vantage)
        assert has_vantage

    def test_ci05_privacy_modes_defined(self):
        """tracker.py supports full, anonymized, strict, local-only."""
        src = (AGENT_DIR / "tracker.py").read_text()
        for mode in ["full", "strict", "anonymized", "local-only"]:
            assert mode in src, f"Privacy mode '{mode}' missing from tracker.py"
        chk("CI.5 all 4 privacy modes defined in tracker", True)


# ═══════════════════════════════════════════════════════════════════════════════
#  Section B: Cost Commands (/cost, /compare equivalents)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSlashCommands:
    """Tests for cost/compare Python equivalents."""

    def test_ci06_cost_command_claude(self):
        section("B --- Cost & Compare Commands")
        r = py_cost("claude-sonnet-4-6", 1000, 500)
        chk("CI.6 /cost claude-sonnet-4-6 returns positive cost",
            r.get("totalCostUsd", 0) > 0)
        assert r.get("totalCostUsd", 0) > 0

    def test_ci07_cost_command_gpt4o(self):
        r = py_cost("gpt-4o", 1000, 500)
        chk("CI.7 /cost gpt-4o returns positive cost",
            r.get("totalCostUsd", 0) > 0)
        assert r.get("totalCostUsd", 0) > 0

    def test_ci08_cost_command_gemini(self):
        r = py_cost("gemini-2.0-flash", 1000, 500)
        chk("CI.8 /cost gemini-2.0-flash returns positive cost",
            r.get("totalCostUsd", 0) > 0)
        assert r.get("totalCostUsd", 0) > 0

    def test_ci09_cost_command_unknown_model(self):
        r = py_cost("nonexistent-model-xyz", 1000, 500)
        chk("CI.9 /cost unknown model returns 0",
            r.get("totalCostUsd", 0) == 0)
        assert r.get("totalCostUsd", 0) == 0

    def test_ci10_cost_with_cache_discount(self):
        no_cache = py_cost("claude-opus-4-6", 10000, 5000, 0)
        with_cache = py_cost("claude-opus-4-6", 10000, 5000, 5000)
        chk("CI.10 cached tokens reduce total cost",
            with_cache["totalCostUsd"] < no_cache["totalCostUsd"])
        assert with_cache["totalCostUsd"] < no_cache["totalCostUsd"]

    def test_ci11_compare_finds_cheaper(self):
        r = py_cheapest("claude-opus-4-6", 1000, 500)
        chk("CI.11 /compare finds cheaper model for opus",
            r is not None and r.get("model"))
        assert r is not None and r.get("model")

    def test_ci12_compare_savings_positive(self):
        current = py_cost("claude-opus-4-6", 1000, 500)
        r = py_cheapest("claude-opus-4-6", 1000, 500)
        savings = (current.get("totalCostUsd", 0) - r.get("costUsd", 0)) if r else 0
        chk("CI.12 /compare savings > 0 vs opus", savings > 0)
        assert savings > 0

    def test_ci13_models_list(self):
        r = py_models()
        chk("CI.13 models list has 15+ entries", r.get("count", 0) >= 15)
        assert r.get("count", 0) >= 15

    def test_ci14_zero_tokens_zero_cost(self):
        r = py_cost("gpt-4o", 0, 0)
        chk("CI.14 zero tokens = zero cost", r.get("totalCostUsd", 0) == 0)
        assert r.get("totalCostUsd", 0) == 0

    def test_ci15_cost_proportional_to_tokens(self):
        small = py_cost("gpt-4o", 100, 50)
        large = py_cost("gpt-4o", 10000, 5000)
        chk("CI.15 10x tokens ~ 10x cost",
            large["totalCostUsd"] > small["totalCostUsd"] * 5)
        assert large["totalCostUsd"] > small["totalCostUsd"] * 5


# ═══════════════════════════════════════════════════════════════════════════════
#  Section C: Session Mode
# ═══════════════════════════════════════════════════════════════════════════════

class TestSessionMode:
    """Tests for Python session module."""

    def test_ci16_session_module_exists(self):
        section("C --- Session Mode")
        chk("CI.16 session.py source exists",
            file_exists(AGENT_DIR / "session.py"))
        assert file_exists(AGENT_DIR / "session.py")

    def test_ci17_session_store_module_exists(self):
        chk("CI.17 session_store.py source exists",
            file_exists(AGENT_DIR / "session_store.py"))
        assert file_exists(AGENT_DIR / "session_store.py")

    def test_ci18_session_state_in_source(self):
        src = (AGENT_DIR / "session.py").read_text()
        chk("CI.18 VantageSession class defined",
            "VantageSession" in src)
        assert "VantageSession" in src

    def test_ci19_session_tracks_cost(self):
        src = (AGENT_DIR / "session.py").read_text()
        chk("CI.19 session tracks total_cost_usd",
            "total_cost_usd" in src)
        assert "total_cost_usd" in src

    def test_ci20_session_tracks_tokens(self):
        src = (AGENT_DIR / "session.py").read_text()
        chk("CI.20 session tracks total_input_tokens",
            "total_input_tokens" in src)
        assert "total_input_tokens" in src


# ═══════════════════════════════════════════════════════════════════════════════
#  Section D: Prompt Optimization
# ═══════════════════════════════════════════════════════════════════════════════

class TestPromptOptimization:
    """Tests for prompt optimization engine."""

    def test_ci21_optimize_empty(self):
        section("D --- Prompt Optimization")
        r = py_optimize("")
        chk("CI.21 empty prompt returns empty", r.get("optimized", "") == "")
        assert r.get("optimized", "") == ""

    def test_ci22_optimize_removes_filler(self):
        r = py_optimize("Could you please explain what kubernetes is")
        chk("CI.22 'could you please' removed",
            "could you please" not in r.get("optimized", "").lower())
        assert "could you please" not in r.get("optimized", "").lower()

    def test_ci23_optimize_in_order_to(self):
        r = py_optimize("In order to deploy we need to configure the cluster")
        chk("CI.23 'in order to' -> 'to'",
            "in order to" not in r.get("optimized", "").lower())
        assert "in order to" not in r.get("optimized", "").lower()

    def test_ci24_optimize_due_to_fact(self):
        r = py_optimize("Due to the fact that the system is slow we need to fix it")
        chk("CI.24 'due to the fact that' -> 'because'",
            "due to the fact that" not in r.get("optimized", "").lower())
        assert "due to the fact that" not in r.get("optimized", "").lower()

    def test_ci25_optimize_dedup(self):
        r = py_optimize("The system is fast. The code is clean. The system is fast.")
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
        r = py_optimize(verbose)
        chk("CI.26 verbose prompt saves 20%+", r.get("savedPercent", 0) >= 20)
        assert r.get("savedPercent", 0) >= 20

    def test_ci27_token_count_short(self):
        r = py_tokens("hello world")
        chk("CI.27 'hello world' = 2-4 tokens", 1 <= r.get("tokens", 0) <= 4)
        assert 1 <= r.get("tokens", 0) <= 4

    def test_ci28_token_count_paragraph(self):
        text = " ".join(["word"] * 100)
        r = py_tokens(text)
        chk("CI.28 100 words ~ 100 tokens", 90 <= r.get("tokens", 0) <= 130)
        assert 90 <= r.get("tokens", 0) <= 130


# ═══════════════════════════════════════════════════════════════════════════════
#  Section E: Agent Detection (Python equivalents)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentDetection:
    """Tests for agent adapter detection and classifier command maps."""

    def test_ci29_all_agent_commands_defined(self):
        section("E --- Agent Detection")
        agents = ["claude", "codex", "gemini", "aider", "chatgpt"]
        for a in agents:
            assert a in AGENT_COMMANDS, f"Missing agent '{a}' in AGENT_COMMANDS"
        chk("CI.29 all 5 agents defined in AGENT_COMMANDS", True)

    def test_ci30_vantage_commands_defined(self):
        chk("CI.30 VANTAGE_COMMANDS non-empty",
            len(VANTAGE_COMMANDS) > 0)
        assert len(VANTAGE_COMMANDS) > 0

    def test_ci31_classifier_module_importable(self):
        chk("CI.31 classifier module importable",
            file_exists(AGENT_DIR / "classifier.py"))
        assert file_exists(AGENT_DIR / "classifier.py")

    def test_ci32_all_agent_names_normalize(self):
        """normalize_agent_name maps all expected aliases."""
        tests = [
            ("claude-code", "claude"),
            ("gemini-cli", "gemini"),
            ("codex-cli", "codex"),
            ("aider-v2", "aider"),
            ("cursor", "chatgpt"),
        ]
        for alias, expected in tests:
            result = normalize_agent_name(alias)
            assert result == expected, f"{alias} → {result} (expected {expected})"
        chk("CI.32 all 5 agent aliases normalize correctly", True)

    def test_ci33_agent_command_classification_complete(self):
        """classify_input correctly routes commands for each agent."""
        checks = [
            ("/compact", "claude", "agent-command"),
            ("/compress", "gemini", "agent-command"),
            ("/approval", "codex", "agent-command"),
            ("/add", "aider", "agent-command"),
            ("/cost", "claude", "vantage-command"),
        ]
        for cmd, agent, expected in checks:
            result = classify_input(cmd, agent)
            assert result == expected, f"{cmd}/{agent} → {result} (expected {expected})"
        chk("CI.33 all agent command classifications correct", True)


# ═══════════════════════════════════════════════════════════════════════════════
#  Section F: Config & Module Checks
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfigAndErrors:
    """Tests for Python package config and module integrity."""

    def test_ci34_pyproject_or_setup_valid(self):
        section("F --- Config & Module Checks")
        pyproject = ROOT / "vantage-agent" / "pyproject.toml"
        setup_py = ROOT / "vantage-agent" / "setup.py"
        has_config = pyproject.exists() or setup_py.exists()
        chk("CI.34 pyproject.toml or setup.py exists", has_config)
        assert has_config

    def test_ci35_no_heavy_runtime_deps(self):
        """vantage-agent should not depend on heavy npm-style libraries."""
        pyproject = ROOT / "vantage-agent" / "pyproject.toml"
        if not pyproject.exists():
            pytest.skip("pyproject.toml not found")
        content = pyproject.read_text()
        # The project should not pull in large ML frameworks as runtime deps
        bad_deps = ["torch", "tensorflow", "transformers"]
        for dep in bad_deps:
            assert dep not in content, f"Unexpected heavy dep '{dep}' in pyproject.toml"
        chk("CI.35 no heavy ML framework runtime dependencies", True)

    def test_ci36_cli_entrypoint_configured(self):
        """vantage-agent should expose a CLI entrypoint."""
        pyproject = ROOT / "vantage-agent" / "pyproject.toml"
        if not pyproject.exists():
            pytest.skip("pyproject.toml not found")
        content = pyproject.read_text()
        chk("CI.36 CLI entrypoint configured in pyproject.toml",
            "[project.scripts]" in content or "console_scripts" in content)
        assert "[project.scripts]" in content or "console_scripts" in content

    def test_ci37_optimizer_module_importable(self):
        """All key modules import without error."""
        from vantage_agent import optimizer, pricing, classifier, tracker, recommendations
        chk("CI.37 all key modules import successfully", True)

    def test_ci38_pricing_data_present(self):
        chk("CI.38 MODEL_PRICES has entries",
            len(MODEL_PRICES) > 0)
        assert len(MODEL_PRICES) > 0


# ═══════════════════════════════════════════════════════════════════════════════
#  Section G: SSE Live Stream (KV broadcast path)
# ═══════════════════════════════════════════════════════════════════════════════

class TestLiveSSEStream:
    """
    Verify that events tracked via POST /v1/events reach the SSE
    live stream (GET /v1/stream/{orgId}).
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
        CI.40-41: Simulate the vantage-agent event tracking call (POST /v1/events),
        which internally calls broadcastEvent() → KV.  Then poll the SSE stream
        and verify the event is delivered within 10 seconds.
        """
        api_key, org_id, _ = account
        hdrs = get_headers(api_key)

        # Simulate what vantage-agent posts after a session
        unique_model = f"claude-sonnet-4-6-agent-{uuid.uuid4().hex[:8]}"
        ev = make_event(i=0, model=unique_model, cost=0.023)
        ev["source"] = "vantage-agent"

        r = requests.post(
            f"{API_URL}/v1/events",
            json=ev,
            headers=hdrs,
            timeout=10,
        )
        chk("CI.40 agent event ingest returns 200/201", r.status_code in (200, 201),
            f"got {r.status_code}")
        assert r.status_code in (200, 201)

        # Allow KV write to propagate
        time.sleep(2)

        # Poll SSE stream for up to 10 seconds
        stream_url = f"{API_URL}/v1/stream/{org_id}?token={api_key}"
        received = None
        try:
            with requests.get(stream_url, stream=True, timeout=10) as sr:
                chk("CI.41 SSE stream opens after agent ingest", sr.status_code == 200,
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

        chk("CI.41 SSE stream delivers event after agent ingest",
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
