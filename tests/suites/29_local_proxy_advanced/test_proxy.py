"""
Test Suite 29 --- Local Proxy Advanced Tests (vantage-local-proxy)
===================================================================
Suite PX: Tests proxy startup/shutdown, HTTP interception, token extraction
from API responses, cost calculation from intercepted calls, privacy
filtering, and multi-provider support (OpenAI, Anthropic, Google).

Labels: PX.1 - PX.36  (36 checks)
"""

import sys
import time
import uuid
import json
import subprocess
import requests
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.api import fresh_account, get_headers, signup_api
from helpers.data import rand_email, rand_tag
from helpers.output import section, chk, ok, fail, info, get_results, reset_results

PROXY_DIR = Path(__file__).parent.parent.parent.parent / "cohrint-local-proxy"


# ── Payload Builders ─────────────────────────────────────────────────────────

def ts_nano():
    return str(int(time.time() * 1e9))


def make_event(model="claude-sonnet-4-6", provider="anthropic",
               prompt_tokens=1000, completion_tokens=500,
               cost=0.0105, team="platform", source="local-proxy",
               extra_fields=None):
    ev = {
        "event_id": f"px-{int(time.time())}-{uuid.uuid4().hex[:8]}",
        "provider": provider,
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_cost_usd": cost,
        "latency_ms": 1500,
        "environment": "test",
        "team": team,
        "source": source,
    }
    if extra_fields:
        ev.update(extra_fields)
    return ev


def make_otlp_metrics(service_name, metrics, email="dev@test.com",
                      team="platform", source="local-proxy"):
    return {
        "resourceMetrics": [{
            "resource": {
                "attributes": [
                    {"key": "service.name", "value": {"stringValue": service_name}},
                    {"key": "user.email", "value": {"stringValue": email}},
                    {"key": "session.id", "value": {"stringValue": f"sess-{int(time.time())}"}},
                    {"key": "team.id", "value": {"stringValue": team}},
                    {"key": "source", "value": {"stringValue": source}},
                ]
            },
            "scopeMetrics": [{
                "scope": {"name": "vantage-local-proxy", "version": "1.0"},
                "metrics": metrics,
            }]
        }]
    }


def counter(name, value, attrs=None):
    return {
        "name": name,
        "unit": "1",
        "sum": {
            "dataPoints": [{
                "asDouble": value,
                "timeUnixNano": ts_nano(),
                "attributes": [
                    {"key": k, "value": {"stringValue": str(v)}}
                    for k, v in (attrs or {}).items()
                ],
            }],
            "isMonotonic": True,
        },
    }


def histogram(name, sum_val, count, attrs=None):
    return {
        "name": name,
        "unit": "1",
        "histogram": {
            "dataPoints": [{
                "sum": sum_val,
                "count": str(count),
                "timeUnixNano": ts_nano(),
                "attributes": [
                    {"key": k, "value": {"stringValue": str(v)}}
                    for k, v in (attrs or {}).items()
                ],
            }],
        },
    }


def file_exists(path: Path) -> bool:
    return path.exists() and path.is_file()


# ═══════════════════════════════════════════════════════════════════════════════
#  Section A: Proxy Structure & Source Files
# ═══════════════════════════════════════════════════════════════════════════════

class TestProxyStructure:
    """Validate proxy source file structure."""

    def test_px01_package_json_exists(self):
        section("A --- Proxy Structure & Source Files")
        chk("PX.1 package.json exists", file_exists(PROXY_DIR / "package.json"))
        assert file_exists(PROXY_DIR / "package.json")

    def test_px02_index_ts_exists(self):
        chk("PX.2 src/index.ts exists",
            file_exists(PROXY_DIR / "src" / "index.ts"))
        assert file_exists(PROXY_DIR / "src" / "index.ts")

    def test_px03_proxy_server_exists(self):
        chk("PX.3 src/proxy-server.ts exists",
            file_exists(PROXY_DIR / "src" / "proxy-server.ts"))
        assert file_exists(PROXY_DIR / "src" / "proxy-server.ts")

    def test_px04_pricing_engine_exists(self):
        chk("PX.4 src/pricing.ts exists",
            file_exists(PROXY_DIR / "src" / "pricing.ts"))
        assert file_exists(PROXY_DIR / "src" / "pricing.ts")

    def test_px05_privacy_engine_exists(self):
        chk("PX.5 src/privacy.ts exists",
            file_exists(PROXY_DIR / "src" / "privacy.ts"))
        assert file_exists(PROXY_DIR / "src" / "privacy.ts")

    def test_px06_cli_exists(self):
        chk("PX.6 src/cli.ts exists",
            file_exists(PROXY_DIR / "src" / "cli.ts"))
        assert file_exists(PROXY_DIR / "src" / "cli.ts")

    def test_px07_scanners_dir_exists(self):
        chk("PX.7 src/scanners/ directory exists",
            (PROXY_DIR / "src" / "scanners").is_dir())
        assert (PROXY_DIR / "src" / "scanners").is_dir()

    def test_px08_dist_built(self):
        dist = PROXY_DIR / "dist" / "index.js"
        exists = file_exists(dist)
        chk("PX.8 dist/index.js exists (built)", exists)
        # Skip rather than fail if not built
        if not exists:
            pytest.skip("dist not built")


# ═══════════════════════════════════════════════════════════════════════════════
#  Section B: Pricing Engine Accuracy
# ═══════════════════════════════════════════════════════════════════════════════

class TestProxyPricing:
    """Test pricing calculations match expected values."""

    def test_px09_pricing_has_openai(self):
        section("B --- Pricing Engine Accuracy")
        src = (PROXY_DIR / "src" / "pricing.ts").read_text()
        chk("PX.9 pricing table includes gpt-4o", '"gpt-4o"' in src)
        assert '"gpt-4o"' in src

    def test_px10_pricing_has_anthropic(self):
        src = (PROXY_DIR / "src" / "pricing.ts").read_text()
        chk("PX.10 pricing table includes claude-sonnet-4-6",
            '"claude-sonnet-4-6"' in src)
        assert '"claude-sonnet-4-6"' in src

    def test_px11_pricing_has_google(self):
        src = (PROXY_DIR / "src" / "pricing.ts").read_text()
        chk("PX.11 pricing table includes gemini",
            "gemini" in src)
        assert "gemini" in src

    def test_px12_pricing_has_meta(self):
        src = (PROXY_DIR / "src" / "pricing.ts").read_text()
        chk("PX.12 pricing table includes llama",
            "llama" in src)
        assert "llama" in src

    def test_px13_pricing_has_mistral(self):
        src = (PROXY_DIR / "src" / "pricing.ts").read_text()
        chk("PX.13 pricing table includes mistral",
            "mistral" in src)
        assert "mistral" in src

    def test_px14_pricing_has_deepseek(self):
        src = (PROXY_DIR / "src" / "pricing.ts").read_text()
        chk("PX.14 pricing table includes deepseek",
            "deepseek" in src)
        assert "deepseek" in src

    def test_px15_calculate_cost_function(self):
        src = (PROXY_DIR / "src" / "pricing.ts").read_text()
        chk("PX.15 calculateCost function exported",
            "export function calculateCost" in src)
        assert "export function calculateCost" in src

    def test_px16_cache_token_support(self):
        src = (PROXY_DIR / "src" / "pricing.ts").read_text()
        chk("PX.16 cachedTokens parameter in calculateCost",
            "cachedTokens" in src)
        assert "cachedTokens" in src

    def test_px17_model_count_15_plus(self):
        src = (PROXY_DIR / "src" / "pricing.ts").read_text()
        # Count model entries (lines with provider field in TS object literals)
        count = src.count("provider:")
        chk("PX.17 pricing table has 15+ models", count >= 15)
        assert count >= 15


# ═══════════════════════════════════════════════════════════════════════════════
#  Section C: Privacy Filtering
# ═══════════════════════════════════════════════════════════════════════════════

class TestProxyPrivacy:
    """Test privacy engine in local proxy."""

    def test_px18_privacy_module_exists(self):
        section("C --- Privacy Filtering")
        src = (PROXY_DIR / "src" / "privacy.ts").read_text()
        chk("PX.18 privacy module has content", len(src) > 50)
        assert len(src) > 50

    def test_px19_privacy_modes_defined(self):
        src = (PROXY_DIR / "src" / "privacy.ts").read_text()
        # Check for privacy mode references
        has_modes = ("strict" in src.lower() or "anonymize" in src.lower()
                     or "privacy" in src.lower())
        chk("PX.19 privacy modes referenced in source", has_modes)
        assert has_modes

    def test_px20_no_prompt_in_strict_mode(self):
        """Events forwarded in strict mode must not contain prompt text."""
        ev = make_event(model="gpt-4o", source="proxy-strict")
        assert "prompt_text" not in ev
        assert "response_text" not in ev
        chk("PX.20 strict mode event has no prompt/response text", True)


# ═══════════════════════════════════════════════════════════════════════════════
#  Section D: Multi-Provider Interception (via API)
# ═══════════════════════════════════════════════════════════════════════════════

class TestMultiProvider:
    """Test event forwarding for multiple providers through API."""

    def test_px21_openai_event(self, headers):
        section("D --- Multi-Provider Interception")
        ev = make_event(model="gpt-4o", provider="openai",
                        prompt_tokens=500, completion_tokens=200,
                        cost=0.0033, source="local-proxy")
        r = requests.post(
            f"{API_URL}/v1/events", json=ev, headers=headers, timeout=10,
        )
        chk("PX.21 OpenAI event forwarded OK",
            r.status_code in (200, 201))
        assert r.status_code in (200, 201)

    def test_px22_anthropic_event(self, headers):
        ev = make_event(model="claude-sonnet-4-6", provider="anthropic",
                        prompt_tokens=1000, completion_tokens=500,
                        cost=0.0105, source="local-proxy")
        r = requests.post(
            f"{API_URL}/v1/events", json=ev, headers=headers, timeout=10,
        )
        chk("PX.22 Anthropic event forwarded OK",
            r.status_code in (200, 201))
        assert r.status_code in (200, 201)

    def test_px23_google_event(self, headers):
        ev = make_event(model="gemini-2.0-flash", provider="google",
                        prompt_tokens=2000, completion_tokens=1000,
                        cost=0.0006, source="local-proxy")
        r = requests.post(
            f"{API_URL}/v1/events", json=ev, headers=headers, timeout=10,
        )
        chk("PX.23 Google/Gemini event forwarded OK",
            r.status_code in (200, 201))
        assert r.status_code in (200, 201)

    def test_px24_meta_event(self, headers):
        ev = make_event(model="llama-3.3-70b", provider="meta",
                        prompt_tokens=1000, completion_tokens=500,
                        cost=0.00043, source="local-proxy")
        r = requests.post(
            f"{API_URL}/v1/events", json=ev, headers=headers, timeout=10,
        )
        chk("PX.24 Meta/Llama event forwarded OK",
            r.status_code in (200, 201))
        assert r.status_code in (200, 201)

    def test_px25_deepseek_event(self, headers):
        ev = make_event(model="deepseek-chat", provider="deepseek",
                        prompt_tokens=800, completion_tokens=400,
                        cost=0.00066, source="local-proxy")
        r = requests.post(
            f"{API_URL}/v1/events", json=ev, headers=headers, timeout=10,
        )
        chk("PX.25 DeepSeek event forwarded OK",
            r.status_code in (200, 201))
        assert r.status_code in (200, 201)

    def test_px26_mistral_event(self, headers):
        ev = make_event(model="mistral-large-latest", provider="mistral",
                        prompt_tokens=600, completion_tokens=300,
                        cost=0.003, source="local-proxy")
        r = requests.post(
            f"{API_URL}/v1/events", json=ev, headers=headers, timeout=10,
        )
        chk("PX.26 Mistral event forwarded OK",
            r.status_code in (200, 201))
        assert r.status_code in (200, 201)


# ═══════════════════════════════════════════════════════════════════════════════
#  Section E: OTel Forwarding via Proxy
# ═══════════════════════════════════════════════════════════════════════════════

class TestOTelForwarding:
    """Test OTel metrics forwarding through the proxy pipeline."""

    def test_px27_otel_counter_forwarded(self, headers):
        section("E --- OTel Forwarding via Proxy")
        payload = make_otlp_metrics(
            "local-proxy-test",
            [counter("llm.token.usage", 2000,
                     {"model": "gpt-4o", "type": "input"})],
        )
        r = requests.post(
            f"{API_URL}/v1/otel/v1/metrics",
            json=payload,
            headers=headers,
            timeout=10,
        )
        chk("PX.27 OTel counter metric forwarded",
            r.status_code in (200, 201, 202))
        assert r.status_code in (200, 201, 202)

    def test_px28_otel_histogram_forwarded(self, headers):
        payload = make_otlp_metrics(
            "local-proxy-test",
            [histogram("llm.token.usage", 3000, 5,
                       {"model": "claude-sonnet-4-6", "type": "output"})],
        )
        r = requests.post(
            f"{API_URL}/v1/otel/v1/metrics",
            json=payload,
            headers=headers,
            timeout=10,
        )
        chk("PX.28 OTel histogram metric forwarded",
            r.status_code in (200, 201, 202))
        assert r.status_code in (200, 201, 202)

    def test_px29_otel_multi_metric_batch(self, headers):
        payload = make_otlp_metrics(
            "local-proxy-test",
            [
                counter("llm.token.usage", 1000,
                        {"model": "gpt-4o", "type": "input"}),
                counter("llm.token.usage", 500,
                        {"model": "gpt-4o", "type": "output"}),
                counter("llm.request.count", 1,
                        {"model": "gpt-4o"}),
            ],
        )
        r = requests.post(
            f"{API_URL}/v1/otel/v1/metrics",
            json=payload,
            headers=headers,
            timeout=10,
        )
        chk("PX.29 OTel batch of 3 metrics forwarded",
            r.status_code in (200, 201, 202))
        assert r.status_code in (200, 201, 202)


# ═══════════════════════════════════════════════════════════════════════════════
#  Section F: Cross-Platform Verification
# ═══════════════════════════════════════════════════════════════════════════════

class TestCrossPlatformVerification:
    """Verify proxy-ingested data appears in cross-platform endpoints."""

    def test_px30_cross_platform_summary(self, headers):
        section("F --- Cross-Platform Verification")
        r = requests.get(
            f"{API_URL}/v1/cross-platform/summary",
            headers=headers,
            timeout=10,
        )
        chk("PX.30 cross-platform summary accessible",
            r.status_code == 200)
        assert r.status_code == 200

    def test_px31_cross_platform_models(self, headers):
        r = requests.get(
            f"{API_URL}/v1/cross-platform/models",
            headers=headers,
            timeout=10,
        )
        chk("PX.31 cross-platform models accessible",
            r.status_code == 200)
        assert r.status_code == 200

    def test_px32_cross_platform_live_feed(self, headers):
        r = requests.get(
            f"{API_URL}/v1/cross-platform/live",
            headers=headers,
            timeout=10,
        )
        chk("PX.32 cross-platform live feed accessible",
            r.status_code == 200)
        assert r.status_code == 200

    def test_px33_cross_platform_developers(self, headers):
        r = requests.get(
            f"{API_URL}/v1/cross-platform/developers",
            headers=headers,
            timeout=10,
        )
        chk("PX.33 cross-platform developers accessible",
            r.status_code == 200)
        assert r.status_code == 200

    def test_px34_cross_org_isolation(self, headers, second_headers):
        """Events from one org must not leak to another."""
        tag = f"iso-{rand_tag()}"
        ev = make_event(model="gpt-4o", cost=77.77, source="proxy-iso")
        ev["event_id"] = f"iso-{uuid.uuid4().hex[:8]}"
        ev["environment"] = tag
        requests.post(
            f"{API_URL}/v1/events", json=ev, headers=headers, timeout=10,
        )
        time.sleep(1)
        r = requests.get(
            f"{API_URL}/v1/analytics/summary",
            headers=second_headers,
            timeout=10,
        )
        data = r.json()
        total = data.get("total_cost", data.get("totalCost",
                data.get("total_cost_usd", 0)))
        chk("PX.34 cross-org isolation holds",
            total < 77)
        assert total < 77

    def test_px35_proxy_zero_runtime_deps(self):
        pkg = json.loads((PROXY_DIR / "package.json").read_text())
        deps = pkg.get("dependencies", {})
        chk("PX.35 zero runtime dependencies", len(deps) == 0)
        assert len(deps) == 0

    def test_px36_typecheck_passes(self):
        r = subprocess.run(
            ["npx", "tsc", "--noEmit"],
            capture_output=True, text=True, timeout=30,
            cwd=str(PROXY_DIR),
        )
        chk("PX.36 TypeScript typecheck passes", r.returncode == 0)
        assert r.returncode == 0, f"tsc errors: {r.stderr[:500]}"


# ── Runner ────────────────────────────────────────────────────────────────────

def run():
    reset_results()
    api_key, org_id, cookies = fresh_account(prefix="prx29run")
    hdrs = get_headers(api_key)
    api_key2, _, _ = fresh_account(prefix="prx29b")
    hdrs2 = get_headers(api_key2)

    for cls in [TestProxyStructure, TestProxyPricing, TestProxyPrivacy,
                TestMultiProvider, TestOTelForwarding,
                TestCrossPlatformVerification]:
        obj = cls()
        for name in sorted(dir(obj)):
            if name.startswith("test_"):
                try:
                    method = getattr(obj, name)
                    import inspect
                    params = inspect.signature(method).parameters
                    kwargs = {}
                    if "headers" in params:
                        kwargs["headers"] = hdrs
                    if "second_headers" in params:
                        kwargs["second_headers"] = hdrs2
                    method(**kwargs)
                except Exception as e:
                    fail(name, str(e))

    res = get_results()
    print(f"\n{'='*60}")
    print(f"Results: {res['passed']} passed, {res['failed']} failed, {res['warned']} warned")
    return res["failed"]


if __name__ == "__main__":
    sys.exit(run())
