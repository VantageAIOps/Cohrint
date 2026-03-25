"""
Test Suite 30 --- Cross-Agent Integration Tests
=================================================
Suite XA: Validates all agent adapters (Claude, Gemini, Codex, Aider, ChatGPT),
agent detection logic, command building, session mode support, cost tracking
across agents, and /compare mode accuracy.

Labels: XA.1 - XA.38  (38 checks)
"""

import sys
import json
import shutil
import subprocess
import time
import uuid
import requests
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.api import fresh_account, get_headers
from helpers.data import make_event, rand_tag
from helpers.output import section, chk, ok, fail, info, get_results, reset_results

CLI_DIR = Path(__file__).parent.parent.parent.parent / "vantage-cli"
HARNESS = CLI_DIR / "test-helpers.mjs"
AGENTS_DIR = CLI_DIR / "src" / "agents"


# ── Helpers ──────────────────────────────────────────────────────────────────

def js(cmd: str, *args: str, timeout: int = 10) -> dict:
    """Run test-helpers.mjs and return parsed JSON."""
    result = subprocess.run(
        ["node", str(HARNESS), cmd, *[str(a) for a in args]],
        capture_output=True, text=True, timeout=timeout,
        cwd=str(CLI_DIR),
    )
    try:
        return json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        return {"error": result.stderr, "stdout": result.stdout}


def file_exists(path: Path) -> bool:
    return path.exists() and path.is_file()


def read_agent_src(name: str) -> str:
    path = AGENTS_DIR / f"{name}.ts"
    if path.exists():
        return path.read_text()
    return ""


# ═══════════════════════════════════════════════════════════════════════════════
#  Section A: Agent Adapter Files & Structure
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentAdapterStructure:
    """Validate all agent adapter files exist and are well-formed."""

    def test_xa01_claude_adapter_exists(self):
        section("A --- Agent Adapter Files & Structure")
        chk("XA.1 claude.ts exists", file_exists(AGENTS_DIR / "claude.ts"))
        assert file_exists(AGENTS_DIR / "claude.ts")

    def test_xa02_gemini_adapter_exists(self):
        chk("XA.2 gemini.ts exists", file_exists(AGENTS_DIR / "gemini.ts"))
        assert file_exists(AGENTS_DIR / "gemini.ts")

    def test_xa03_codex_adapter_exists(self):
        chk("XA.3 codex.ts exists", file_exists(AGENTS_DIR / "codex.ts"))
        assert file_exists(AGENTS_DIR / "codex.ts")

    def test_xa04_aider_adapter_exists(self):
        chk("XA.4 aider.ts exists", file_exists(AGENTS_DIR / "aider.ts"))
        assert file_exists(AGENTS_DIR / "aider.ts")

    def test_xa05_chatgpt_adapter_exists(self):
        chk("XA.5 chatgpt.ts exists", file_exists(AGENTS_DIR / "chatgpt.ts"))
        assert file_exists(AGENTS_DIR / "chatgpt.ts")

    def test_xa06_types_defines_interface(self):
        src = read_agent_src("types")
        chk("XA.6 AgentAdapter interface defined",
            "AgentAdapter" in src)
        assert "AgentAdapter" in src

    def test_xa07_registry_exports_all_agents(self):
        src = (AGENTS_DIR / "registry.ts").read_text()
        chk("XA.7 ALL_AGENTS array exported", "ALL_AGENTS" in src)
        assert "ALL_AGENTS" in src

    def test_xa08_registry_has_5_agents(self):
        src = (AGENTS_DIR / "registry.ts").read_text()
        agent_names = ["claudeAdapter", "codexAdapter", "geminiAdapter",
                       "aiderAdapter", "chatgptAdapter"]
        all_present = all(a in src for a in agent_names)
        chk("XA.8 registry has all 5 agent adapters", all_present)
        assert all_present


# ═══════════════════════════════════════════════════════════════════════════════
#  Section B: Claude Agent Adapter
# ═══════════════════════════════════════════════════════════════════════════════

class TestClaudeAdapter:
    """Test Claude agent adapter implementation."""

    def test_xa09_claude_name(self):
        section("B --- Claude Agent Adapter")
        src = read_agent_src("claude")
        chk("XA.9 claude adapter has name 'claude'",
            'name:' in src and 'claude' in src.lower())
        assert 'claude' in src.lower()

    def test_xa10_claude_binary(self):
        src = read_agent_src("claude")
        chk("XA.10 claude binary defined", "binary" in src)
        assert "binary" in src

    def test_xa11_claude_default_model(self):
        src = read_agent_src("claude")
        chk("XA.11 claude defaultModel defined",
            "defaultModel" in src)
        assert "defaultModel" in src

    def test_xa12_claude_detect_function(self):
        src = read_agent_src("claude")
        chk("XA.12 claude detect() function defined",
            "detect" in src)
        assert "detect" in src

    def test_xa13_claude_build_command(self):
        src = read_agent_src("claude")
        chk("XA.13 claude buildCommand() defined",
            "buildCommand" in src)
        assert "buildCommand" in src

    def test_xa14_claude_provider_anthropic(self):
        src = read_agent_src("claude")
        chk("XA.14 claude provider is 'anthropic'",
            "anthropic" in src)
        assert "anthropic" in src


# ═══════════════════════════════════════════════════════════════════════════════
#  Section C: Gemini Agent Adapter
# ═══════════════════════════════════════════════════════════════════════════════

class TestGeminiAdapter:
    """Test Gemini agent adapter implementation."""

    def test_xa15_gemini_name(self):
        section("C --- Gemini Agent Adapter")
        src = read_agent_src("gemini")
        chk("XA.15 gemini adapter has name 'gemini'",
            "gemini" in src.lower())
        assert "gemini" in src.lower()

    def test_xa16_gemini_provider_google(self):
        src = read_agent_src("gemini")
        chk("XA.16 gemini provider is 'google'",
            "google" in src.lower())
        assert "google" in src.lower()

    def test_xa17_gemini_detect(self):
        src = read_agent_src("gemini")
        chk("XA.17 gemini detect() defined", "detect" in src)
        assert "detect" in src

    def test_xa18_gemini_build_command(self):
        src = read_agent_src("gemini")
        chk("XA.18 gemini buildCommand() defined",
            "buildCommand" in src)
        assert "buildCommand" in src


# ═══════════════════════════════════════════════════════════════════════════════
#  Section D: Codex, Aider, ChatGPT Adapters
# ═══════════════════════════════════════════════════════════════════════════════

class TestOtherAdapters:
    """Test Codex, Aider, ChatGPT agent adapters."""

    def test_xa19_codex_has_required_fields(self):
        section("D --- Codex, Aider, ChatGPT Adapters")
        src = read_agent_src("codex")
        for field in ["name", "binary", "defaultModel", "provider",
                      "detect", "buildCommand"]:
            assert field in src, f"codex missing {field}"
        chk("XA.19 codex adapter has all required fields", True)

    def test_xa20_codex_provider_openai(self):
        src = read_agent_src("codex")
        chk("XA.20 codex provider is 'openai'",
            "openai" in src.lower())
        assert "openai" in src.lower()

    def test_xa21_aider_has_required_fields(self):
        src = read_agent_src("aider")
        for field in ["name", "binary", "defaultModel", "provider",
                      "detect", "buildCommand"]:
            assert field in src, f"aider missing {field}"
        chk("XA.21 aider adapter has all required fields", True)

    def test_xa22_chatgpt_has_required_fields(self):
        src = read_agent_src("chatgpt")
        for field in ["name", "binary", "defaultModel", "provider",
                      "detect", "buildCommand"]:
            assert field in src, f"chatgpt missing {field}"
        chk("XA.22 chatgpt adapter has all required fields", True)

    def test_xa23_chatgpt_provider_openai(self):
        src = read_agent_src("chatgpt")
        chk("XA.23 chatgpt provider is 'openai'",
            "openai" in src.lower())
        assert "openai" in src.lower()


# ═══════════════════════════════════════════════════════════════════════════════
#  Section E: Cost Comparison Across Agents (/compare mode)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCostComparison:
    """Test /compare mode cost accuracy across models/agents."""

    def test_xa24_opus_most_expensive(self):
        section("E --- Cost Comparison Across Agents")
        opus = js("cost", "claude-opus-4-6", "1000", "500")
        sonnet = js("cost", "claude-sonnet-4-6", "1000", "500")
        chk("XA.24 opus more expensive than sonnet",
            opus.get("totalCostUsd", 0) > sonnet.get("totalCostUsd", 0))
        assert opus.get("totalCostUsd", 0) > sonnet.get("totalCostUsd", 0)

    def test_xa25_gpt4o_vs_mini(self):
        gpt4o = js("cost", "gpt-4o", "1000", "500")
        mini = js("cost", "gpt-4o-mini", "1000", "500")
        chk("XA.25 gpt-4o more expensive than gpt-4o-mini",
            gpt4o.get("totalCostUsd", 0) > mini.get("totalCostUsd", 0))
        assert gpt4o.get("totalCostUsd", 0) > mini.get("totalCostUsd", 0)

    def test_xa26_gemini_flash_cheapest_google(self):
        flash = js("cost", "gemini-2.0-flash", "1000", "500")
        pro = js("cost", "gemini-1.5-pro", "1000", "500")
        chk("XA.26 gemini flash cheaper than pro",
            flash.get("totalCostUsd", 0) < pro.get("totalCostUsd", 0))
        assert flash.get("totalCostUsd", 0) < pro.get("totalCostUsd", 0)

    def test_xa27_cheapest_for_opus(self):
        r = js("cheapest", "claude-opus-4-6", "1000", "500")
        chk("XA.27 cheapest alternative found for opus",
            r is not None and r.get("model"))
        assert r is not None and r.get("model")

    def test_xa28_cheapest_not_same_model(self):
        r = js("cheapest", "claude-opus-4-6", "1000", "500")
        chk("XA.28 cheapest is NOT opus itself",
            r.get("model") != "claude-opus-4-6")
        assert r.get("model") != "claude-opus-4-6"

    def test_xa29_cheapest_has_savings(self):
        r = js("cheapest", "o1", "1000", "500")
        chk("XA.29 cheapest for o1 has savings > 0",
            r.get("savingsUsd", 0) > 0)
        assert r.get("savingsUsd", 0) > 0

    def test_xa30_cross_provider_comparison(self):
        """Compare costs across providers for same workload."""
        models = ["claude-sonnet-4-6", "gpt-4o", "gemini-1.5-pro"]
        costs = {}
        for m in models:
            r = js("cost", m, "10000", "5000")
            costs[m] = r.get("totalCostUsd", 0)
        all_positive = all(c > 0 for c in costs.values())
        chk("XA.30 all 3 cross-provider costs > 0", all_positive)
        assert all_positive


# ═══════════════════════════════════════════════════════════════════════════════
#  Section F: Cost Tracking via API (multi-agent events)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCostTrackingMultiAgent:
    """Test cost tracking across multiple agents via the API."""

    def test_xa31_track_claude_event(self, headers):
        section("F --- Cost Tracking via API (multi-agent)")
        ev = make_event(i=0, model="claude-sonnet-4-6", cost=0.01)
        ev["source"] = "vantage-cli"
        ev["tags"] = {"agent": "claude"}
        r = requests.post(
            f"{API_URL}/v1/events", json=ev, headers=headers, timeout=10,
        )
        chk("XA.31 claude agent event tracked",
            r.status_code in (200, 201))
        assert r.status_code in (200, 201)

    def test_xa32_track_gemini_event(self, headers):
        ev = make_event(i=0, model="gemini-2.0-flash", cost=0.0004)
        ev["source"] = "vantage-cli"
        ev["tags"] = {"agent": "gemini"}
        ev["provider"] = "google"
        r = requests.post(
            f"{API_URL}/v1/events", json=ev, headers=headers, timeout=10,
        )
        chk("XA.32 gemini agent event tracked",
            r.status_code in (200, 201))
        assert r.status_code in (200, 201)

    def test_xa33_track_codex_event(self, headers):
        ev = make_event(i=0, model="gpt-4o", cost=0.005)
        ev["source"] = "vantage-cli"
        ev["tags"] = {"agent": "codex"}
        r = requests.post(
            f"{API_URL}/v1/events", json=ev, headers=headers, timeout=10,
        )
        chk("XA.33 codex agent event tracked",
            r.status_code in (200, 201))
        assert r.status_code in (200, 201)

    def test_xa34_track_aider_event(self, headers):
        ev = make_event(i=0, model="claude-sonnet-4-6", cost=0.01)
        ev["source"] = "vantage-cli"
        ev["tags"] = {"agent": "aider"}
        r = requests.post(
            f"{API_URL}/v1/events", json=ev, headers=headers, timeout=10,
        )
        chk("XA.34 aider agent event tracked",
            r.status_code in (200, 201))
        assert r.status_code in (200, 201)

    def test_xa35_track_chatgpt_event(self, headers):
        ev = make_event(i=0, model="gpt-4o", cost=0.005)
        ev["source"] = "vantage-cli"
        ev["tags"] = {"agent": "chatgpt"}
        r = requests.post(
            f"{API_URL}/v1/events", json=ev, headers=headers, timeout=10,
        )
        chk("XA.35 chatgpt agent event tracked",
            r.status_code in (200, 201))
        assert r.status_code in (200, 201)

    def test_xa36_multi_agent_batch(self, headers):
        """Batch events from multiple agents in a single call."""
        agents = [
            ("claude-sonnet-4-6", "anthropic", "claude"),
            ("gpt-4o", "openai", "codex"),
            ("gemini-2.0-flash", "google", "gemini"),
        ]
        events = []
        for i, (model, provider, agent) in enumerate(agents):
            ev = make_event(i=i, model=model, cost=0.005)
            ev["provider"] = provider
            ev["source"] = "vantage-cli"
            ev["tags"] = {"agent": agent}
            events.append(ev)
        r = requests.post(
            f"{API_URL}/v1/events/batch", json={"events": events}, headers=headers, timeout=10,
        )
        chk("XA.36 multi-agent batch of 3 events accepted",
            r.status_code in (200, 201))
        assert r.status_code in (200, 201)

    def test_xa37_analytics_after_multi_agent(self, headers):
        time.sleep(1)
        r = requests.get(
            f"{API_URL}/v1/analytics/summary",
            headers=headers,
            timeout=10,
        )
        chk("XA.37 analytics summary accessible after multi-agent events",
            r.status_code == 200)
        assert r.status_code == 200

    def test_xa38_models_endpoint_after_multi_agent(self, headers):
        r = requests.get(
            f"{API_URL}/v1/analytics/models",
            headers=headers,
            timeout=10,
        )
        chk("XA.38 models breakdown accessible after multi-agent events",
            r.status_code == 200)
        assert r.status_code == 200


# ── Runner ────────────────────────────────────────────────────────────────────

def run():
    reset_results()
    api_key, org_id, cookies = fresh_account(prefix="xagt30run")
    hdrs = get_headers(api_key)

    for cls in [TestAgentAdapterStructure, TestClaudeAdapter,
                TestGeminiAdapter, TestOtherAdapters,
                TestCostComparison, TestCostTrackingMultiAgent]:
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
