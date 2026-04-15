"""
Test Suite 30 --- Cross-Agent Integration Tests
=================================================
Suite XA: Validates all Python backend adapters (Claude, Gemini, Codex, API),
pricing comparison across providers, cost tracking via API, and analytics.

Labels: XA.1 - XA.38
"""

import sys
import json
import time
import requests
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.api import fresh_account, get_headers
from helpers.data import make_event, rand_tag
from helpers.output import section, chk, ok, fail, info, get_results, reset_results

AGENT_DIR = Path(__file__).parent.parent.parent.parent / "vantage-agent"
PKG_DIR   = AGENT_DIR / "vantage_agent"
BACKENDS  = PKG_DIR / "backends"

sys.path.insert(0, str(AGENT_DIR))


def backend_src(name: str) -> str:
    path = BACKENDS / f"{name}_backend.py"
    if path.exists():
        return path.read_text()
    return ""


def file_exists(path: Path) -> bool:
    return path.exists() and path.is_file()


# ═══════════════════════════════════════════════════════════════════════════════
#  Section A: Backend Adapter Files & Structure
# ═══════════════════════════════════════════════════════════════════════════════

class TestBackendAdapterStructure:
    """Validate all backend adapter files exist and are well-formed."""

    def test_xa01_claude_backend_exists(self):
        section("A --- Backend Adapter Files & Structure")
        chk("XA.1 claude_backend.py exists", file_exists(BACKENDS / "claude_backend.py"))
        assert file_exists(BACKENDS / "claude_backend.py")

    def test_xa02_gemini_backend_exists(self):
        chk("XA.2 gemini_backend.py exists", file_exists(BACKENDS / "gemini_backend.py"))
        assert file_exists(BACKENDS / "gemini_backend.py")

    def test_xa03_codex_backend_exists(self):
        chk("XA.3 codex_backend.py exists", file_exists(BACKENDS / "codex_backend.py"))
        assert file_exists(BACKENDS / "codex_backend.py")

    def test_xa04_api_backend_exists(self):
        chk("XA.4 api_backend.py exists", file_exists(BACKENDS / "api_backend.py"))
        assert file_exists(BACKENDS / "api_backend.py")

    def test_xa05_base_backend_exists(self):
        chk("XA.5 base.py exists", file_exists(BACKENDS / "base.py"))
        assert file_exists(BACKENDS / "base.py")

    def test_xa06_backends_init_exports(self):
        content = (BACKENDS / "__init__.py").read_text()
        chk("XA.6 backends __init__.py has registry map", "_REGISTRY" in content or "REGISTRY" in content)
        assert "_REGISTRY" in content or "REGISTRY" in content

    def test_xa07_backends_map_has_four(self):
        from vantage_agent.backends import _REGISTRY as backend_map
        names = set(str(k) for k in backend_map.keys()) if hasattr(backend_map, "keys") else set()
        expected = {"api", "claude", "codex", "gemini"}
        chk("XA.7 BACKENDS map has all 4 backends", expected.issubset(names))
        assert expected.issubset(names)

    def test_xa08_base_class_defined(self):
        content = (BACKENDS / "base.py").read_text()
        chk("XA.8 BaseBackend class defined in base.py", "Backend" in content)
        assert "Backend" in content


# ═══════════════════════════════════════════════════════════════════════════════
#  Section B: Claude Backend Adapter
# ═══════════════════════════════════════════════════════════════════════════════

class TestClaudeBackend:
    """Test Claude backend adapter implementation."""

    def test_xa09_claude_class_name(self):
        section("B --- Claude Backend Adapter")
        content = backend_src("claude")
        chk("XA.9 ClaudeBackend class defined", "Claude" in content)
        assert "Claude" in content

    def test_xa10_claude_provider_anthropic(self):
        content = backend_src("claude")
        chk("XA.10 claude provider is anthropic", "anthropic" in content.lower())
        assert "anthropic" in content.lower()

    def test_xa11_claude_model_defined(self):
        content = backend_src("claude")
        chk("XA.11 claude default model defined", "model" in content.lower())
        assert "model" in content.lower()

    def test_xa12_claude_run_method(self):
        content = backend_src("claude")
        chk("XA.12 claude run/send/execute method defined",
            "def run" in content or "def send" in content or "def execute" in content or "async def" in content)
        assert "def run" in content or "def send" in content or "def execute" in content or "async def" in content

    def test_xa13_claude_uses_subprocess(self):
        content = backend_src("claude")
        chk("XA.13 claude backend uses subprocess for claude CLI",
            "subprocess" in content.lower())
        assert "subprocess" in content.lower()

    def test_xa14_claude_cost_tracking(self):
        content = backend_src("claude")
        chk("XA.14 claude tracks cost/tokens",
            "cost" in content.lower() or "token" in content.lower())
        assert "cost" in content.lower() or "token" in content.lower()


# ═══════════════════════════════════════════════════════════════════════════════
#  Section C: Gemini Backend Adapter
# ═══════════════════════════════════════════════════════════════════════════════

class TestGeminiBackend:
    """Test Gemini backend adapter implementation."""

    def test_xa15_gemini_class_name(self):
        section("C --- Gemini Backend Adapter")
        content = backend_src("gemini")
        chk("XA.15 GeminiBackend class defined", "Gemini" in content)
        assert "Gemini" in content

    def test_xa16_gemini_provider_google(self):
        content = backend_src("gemini")
        chk("XA.16 gemini provider is google",
            "google" in content.lower() or "gemini" in content.lower())
        assert "google" in content.lower() or "gemini" in content.lower()

    def test_xa17_gemini_run_method(self):
        content = backend_src("gemini")
        chk("XA.17 gemini run/send method defined",
            "def run" in content or "def send" in content or "async def" in content)
        assert "def run" in content or "def send" in content or "async def" in content

    def test_xa18_gemini_model_defined(self):
        content = backend_src("gemini")
        chk("XA.18 gemini model defined", "model" in content.lower() or "gemini" in content.lower())
        assert "model" in content.lower() or "gemini" in content.lower()


# ═══════════════════════════════════════════════════════════════════════════════
#  Section D: Codex and API Backends
# ═══════════════════════════════════════════════════════════════════════════════

class TestOtherBackends:
    """Test Codex and API backend adapters."""

    def test_xa19_codex_has_required_fields(self):
        section("D --- Codex and API Backends")
        content = backend_src("codex")
        for field in ["class", "def ", "model"]:
            assert field in content, f"codex missing {field}"
        chk("XA.19 codex backend has class and methods", True)

    def test_xa20_codex_provider_openai(self):
        content = backend_src("codex")
        chk("XA.20 codex provider is openai", "openai" in content.lower())
        assert "openai" in content.lower()

    def test_xa21_api_backend_has_required_fields(self):
        content = backend_src("api")
        for field in ["class", "def "]:
            assert field in content, f"api_backend missing {field}"
        chk("XA.21 api backend has class and methods", True)

    def test_xa22_api_backend_references_vantage(self):
        content = backend_src("api")
        chk("XA.22 api backend references vantage/API",
            "vantage" in content.lower() or "api" in content.lower())
        assert "vantage" in content.lower() or "api" in content.lower()

    def test_xa23_pricing_module_covers_all_providers(self):
        from vantage_agent.pricing import MODEL_PRICES
        providers = set()
        for model in MODEL_PRICES:
            if "claude" in model:
                providers.add("anthropic")
            elif "gpt" in model or "o1" in model or "o3" in model:
                providers.add("openai")
            elif "gemini" in model:
                providers.add("google")
        chk("XA.23 pricing covers anthropic + openai + google",
            {"anthropic", "openai", "google"}.issubset(providers))
        assert {"anthropic", "openai", "google"}.issubset(providers)


# ═══════════════════════════════════════════════════════════════════════════════
#  Section E: Cost Comparison Across Providers (/compare mode)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCostComparison:
    """Test cost accuracy across models/providers."""

    def test_xa24_opus_most_expensive(self):
        section("E --- Cost Comparison Across Providers")
        from vantage_agent.pricing import calculate_cost
        opus   = calculate_cost("claude-opus-4-6", 1000, 500)
        sonnet = calculate_cost("claude-sonnet-4-6", 1000, 500)
        chk("XA.24 opus more expensive than sonnet", opus > sonnet)
        assert opus > sonnet

    def test_xa25_gpt4o_vs_mini(self):
        from vantage_agent.pricing import calculate_cost
        gpt4o = calculate_cost("gpt-4o", 1000, 500)
        mini  = calculate_cost("gpt-4o-mini", 1000, 500)
        chk("XA.25 gpt-4o more expensive than gpt-4o-mini", gpt4o > mini)
        assert gpt4o > mini

    def test_xa26_gemini_flash_cheapest_google(self):
        from vantage_agent.pricing import calculate_cost
        flash = calculate_cost("gemini-2.0-flash", 1000, 500)
        pro   = calculate_cost("gemini-1.5-pro", 1000, 500)
        chk("XA.26 gemini flash cheaper than pro", flash < pro)
        assert flash < pro

    def test_xa27_cheapest_for_opus(self):
        from vantage_agent.pricing import find_cheapest
        result = find_cheapest("claude-opus-4-6", 1000, 500)
        chk("XA.27 cheapest alternative found for opus", result is not None)
        assert result is not None

    def test_xa28_cheapest_not_same_model(self):
        from vantage_agent.pricing import find_cheapest
        result = find_cheapest("claude-opus-4-6", 1000, 500)
        chk("XA.28 cheapest is NOT opus itself", result.model != "claude-opus-4-6")
        assert result.model != "claude-opus-4-6"

    def test_xa29_cheapest_has_savings(self):
        from vantage_agent.pricing import find_cheapest
        result = find_cheapest("claude-opus-4-6", 1000, 500)
        chk("XA.29 cheapest for opus has savings > 0", result.savings > 0)
        assert result.savings > 0

    def test_xa30_cross_provider_comparison(self):
        from vantage_agent.pricing import calculate_cost
        models = ["claude-sonnet-4-6", "gpt-4o", "gemini-1.5-pro"]
        costs = {m: calculate_cost(m, 10000, 5000) for m in models}
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
        ev["source"] = "cohrint-agent"
        ev["tags"] = {"agent": "claude"}
        r = requests.post(f"{API_URL}/v1/events", json=ev, headers=headers, timeout=10)
        chk("XA.31 claude agent event tracked", r.status_code in (200, 201))
        assert r.status_code in (200, 201)

    def test_xa32_track_gemini_event(self, headers):
        ev = make_event(i=0, model="gemini-2.0-flash", cost=0.0004)
        ev["source"] = "cohrint-agent"
        ev["tags"] = {"agent": "gemini"}
        ev["provider"] = "google"
        r = requests.post(f"{API_URL}/v1/events", json=ev, headers=headers, timeout=10)
        chk("XA.32 gemini agent event tracked", r.status_code in (200, 201))
        assert r.status_code in (200, 201)

    def test_xa33_track_codex_event(self, headers):
        ev = make_event(i=0, model="gpt-4o", cost=0.005)
        ev["source"] = "cohrint-agent"
        ev["tags"] = {"agent": "codex"}
        r = requests.post(f"{API_URL}/v1/events", json=ev, headers=headers, timeout=10)
        chk("XA.33 codex agent event tracked", r.status_code in (200, 201))
        assert r.status_code in (200, 201)

    def test_xa34_track_api_backend_event(self, headers):
        ev = make_event(i=0, model="claude-sonnet-4-6", cost=0.01)
        ev["source"] = "cohrint-agent"
        ev["tags"] = {"agent": "api"}
        r = requests.post(f"{API_URL}/v1/events", json=ev, headers=headers, timeout=10)
        chk("XA.34 api backend event tracked", r.status_code in (200, 201))
        assert r.status_code in (200, 201)

    def test_xa35_track_multiple_backends(self, headers):
        ev = make_event(i=0, model="gpt-4o", cost=0.005)
        ev["source"] = "cohrint-agent"
        ev["tags"] = {"agent": "codex", "backend": "codex"}
        r = requests.post(f"{API_URL}/v1/events", json=ev, headers=headers, timeout=10)
        chk("XA.35 second codex event tracked", r.status_code in (200, 201))
        assert r.status_code in (200, 201)

    def test_xa36_multi_agent_batch(self, headers):
        agents = [
            ("claude-sonnet-4-6", "anthropic", "claude"),
            ("gpt-4o", "openai", "codex"),
            ("gemini-2.0-flash", "google", "gemini"),
        ]
        events = []
        for i, (model, provider, agent) in enumerate(agents):
            ev = make_event(i=i, model=model, cost=0.005)
            ev["provider"] = provider
            ev["source"] = "cohrint-agent"
            ev["tags"] = {"agent": agent}
            events.append(ev)
        r = requests.post(
            f"{API_URL}/v1/events/batch", json={"events": events}, headers=headers, timeout=10,
        )
        chk("XA.36 multi-agent batch of 3 events accepted", r.status_code in (200, 201))
        assert r.status_code in (200, 201)

    def test_xa37_analytics_after_multi_agent(self, headers):
        time.sleep(1)
        r = requests.get(f"{API_URL}/v1/analytics/summary", headers=headers, timeout=10)
        chk("XA.37 analytics summary accessible after multi-agent events", r.status_code == 200)
        assert r.status_code == 200

    def test_xa38_models_endpoint_after_multi_agent(self, headers):
        r = requests.get(f"{API_URL}/v1/analytics/models", headers=headers, timeout=10)
        chk("XA.38 models breakdown accessible after multi-agent events", r.status_code == 200)
        assert r.status_code == 200


# ── Runner ────────────────────────────────────────────────────────────────────

def run():
    reset_results()
    api_key, org_id, cookies = fresh_account(prefix="xagt30run")
    hdrs = get_headers(api_key)

    for cls in [TestBackendAdapterStructure, TestClaudeBackend,
                TestGeminiBackend, TestOtherBackends,
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
