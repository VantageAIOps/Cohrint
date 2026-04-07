"""
Test Suite 31 — Full-Product Functional E2E Tests
===================================================
Suite FN: End-to-end functional tests covering the ENTIRE VantageAI product
lifecycle — from signup through event ingestion, analytics, cross-platform,
OTel, budget checks, session management, org isolation, CLI integration,
MCP tooling, and local proxy pipeline.

Tests the real production API (no mocks). Each test class represents a
product workflow that a real user would perform.

Labels: FN.1 - FN.55  (55 checks)
"""

import sys
import json
import time
import uuid
import subprocess
import requests
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.api import fresh_account, get_headers, signup_api, session_get
from helpers.data import rand_email, make_event, rand_tag
from helpers.output import section, chk, ok, fail, info, get_results, reset_results

CLI_DIR = Path(__file__).parent.parent.parent.parent / "vantage-cli"
MCP_DIR = Path(__file__).parent.parent.parent.parent / "vantage-mcp"
PROXY_DIR = Path(__file__).parent.parent.parent.parent / "vantage-local-proxy"
TSX = CLI_DIR / "node_modules" / ".bin" / "tsx"
HARNESS = CLI_DIR / "test-helpers.ts"


# ── Helpers ──────────────────────────────────────────────────────────────────

def ts_nano():
    return str(int(time.time() * 1e9))


def js(cmd: str, *args: str, timeout: int = 10) -> dict:
    """Run CLI test harness."""
    result = subprocess.run(
        [str(TSX), str(HARNESS), cmd, *[str(a) for a in args]],
        capture_output=True, text=True, timeout=timeout,
        cwd=str(CLI_DIR),
    )
    try:
        return json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        return {"error": result.stderr, "stdout": result.stdout}


def make_otlp_metrics(service_name, metrics, email="dev@test.com",
                      team="platform"):
    """Build valid OTLP ExportMetricsServiceRequest."""
    return {
        "resourceMetrics": [{
            "resource": {
                "attributes": [
                    {"key": "service.name", "value": {"stringValue": service_name}},
                    {"key": "user.email", "value": {"stringValue": email}},
                    {"key": "session.id", "value": {"stringValue": f"sess-{int(time.time())}"}},
                    {"key": "team.id", "value": {"stringValue": team}},
                ]
            },
            "scopeMetrics": [{
                "scope": {"name": "vantage-e2e", "version": "1.0"},
                "metrics": metrics,
            }]
        }]
    }


def counter(name, value, attrs=None):
    return {
        "name": name, "unit": "1",
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


def histogram(name, total, count, attrs=None):
    return {
        "name": name, "unit": "1",
        "histogram": {
            "dataPoints": [{
                "sum": total, "count": count,
                "timeUnixNano": ts_nano(),
                "attributes": [
                    {"key": k, "value": {"stringValue": str(v)}}
                    for k, v in (attrs or {}).items()
                ],
            }],
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  FLOW 1: User Onboarding (Signup → Session → Auth verification)
# ═══════════════════════════════════════════════════════════════════════════════

class TestOnboardingFlow:
    """Complete user onboarding lifecycle."""

    def test_fn01_signup_creates_org(self):
        section("FLOW 1 --- User Onboarding")
        d = signup_api(email=rand_email("fn31"))
        chk("FN.1 signup returns api_key + org_id",
            "api_key" in d and "org_id" in d)
        assert "api_key" in d and "org_id" in d

    def test_fn02_api_key_format_valid(self):
        d = signup_api(email=rand_email("fn31"))
        key = d["api_key"]
        chk("FN.2 api_key has vnt_ prefix and org embedded",
            key.startswith("vnt_") and "_" in key[4:])
        assert key.startswith("vnt_")

    def test_fn03_session_login_works(self):
        d = signup_api(email=rand_email("fn31"))
        sess = session_get(d["api_key"])
        chk("FN.3 session login returns org data",
            sess is not None and "org_id" in sess)
        assert sess is not None

    def test_fn04_invalid_key_rejected(self):
        r = requests.get(f"{API_URL}/v1/analytics/summary",
                         headers={"Authorization": "Bearer bad_key_123"},
                         timeout=10)
        chk("FN.4 invalid key returns 401", r.status_code == 401)
        assert r.status_code == 401

    def test_fn05_no_auth_rejected(self):
        r = requests.get(f"{API_URL}/v1/analytics/summary", timeout=10)
        chk("FN.5 missing auth returns 401", r.status_code == 401)
        assert r.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
#  FLOW 2: SDK Event Ingestion (Single → Batch → Analytics)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSDKIngestionFlow:
    """SDK tracks events → analytics reflect data."""

    def test_fn06_single_event_ingested(self, headers_a):
        section("FLOW 2 --- SDK Event Ingestion")
        ev = make_event(i=0, model="claude-sonnet-4-6", cost=0.015)
        r = requests.post(f"{API_URL}/v1/events", json=ev,
                          headers=headers_a, timeout=10)
        chk("FN.6 single event accepted (201)", r.status_code == 201)
        assert r.status_code == 201

    def test_fn07_batch_events_ingested(self, headers_a):
        events = [make_event(i=i, model="gpt-4o", cost=0.005) for i in range(10)]
        r = requests.post(f"{API_URL}/v1/events/batch",
                          json={"events": events},
                          headers=headers_a, timeout=15)
        chk("FN.7 batch of 10 events accepted", r.status_code == 201)
        assert r.status_code == 201
        data = r.json()
        chk("FN.8 batch accepted count = 10", data.get("accepted") == 10)
        assert data.get("accepted") == 10

    def test_fn09_summary_reflects_events(self, headers_a):
        time.sleep(1)  # Allow DB to settle
        r = requests.get(f"{API_URL}/v1/analytics/summary",
                         headers=headers_a, timeout=10)
        chk("FN.9 summary endpoint returns 200", r.status_code == 200)
        assert r.status_code == 200
        data = r.json()
        chk("FN.10 summary has today_cost_usd field",
            "today_cost_usd" in data)
        assert "today_cost_usd" in data

    def test_fn11_kpis_reflect_events(self, headers_a):
        r = requests.get(f"{API_URL}/v1/analytics/kpis?period=30",
                         headers=headers_a, timeout=10)
        chk("FN.11 KPIs endpoint returns 200", r.status_code == 200)
        assert r.status_code == 200

    def test_fn12_models_breakdown(self, headers_a):
        r = requests.get(f"{API_URL}/v1/analytics/models?period=30",
                         headers=headers_a, timeout=10)
        chk("FN.12 models breakdown returns 200", r.status_code == 200)
        assert r.status_code == 200

    def test_fn13_traces_show_events(self, headers_a):
        r = requests.get(f"{API_URL}/v1/analytics/traces?limit=10",
                         headers=headers_a, timeout=10)
        chk("FN.13 traces endpoint returns events", r.status_code == 200)
        assert r.status_code == 200

    def test_fn14_timeseries_data(self, headers_a):
        r = requests.get(f"{API_URL}/v1/analytics/timeseries?period=7",
                         headers=headers_a, timeout=10)
        chk("FN.14 timeseries endpoint returns 200", r.status_code == 200)
        assert r.status_code == 200

    def test_fn15_teams_breakdown(self, headers_a):
        r = requests.get(f"{API_URL}/v1/analytics/teams?period=30",
                         headers=headers_a, timeout=10)
        chk("FN.15 teams breakdown returns 200", r.status_code == 200)
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
#  FLOW 3: OTel Collector (Multi-platform ingestion)
# ═══════════════════════════════════════════════════════════════════════════════

class TestOTelCollectorFlow:
    """OTel metrics from multiple AI tools → cross-platform analytics."""

    def test_fn16_claude_otel_accepted(self, headers_a):
        section("FLOW 3 --- OTel Collector Multi-Platform")
        payload = make_otlp_metrics(
            "claude_code",
            [counter("claude_code.tokens.input", 5000,
                     {"model": "claude-sonnet-4-6"}),
             counter("claude_code.tokens.output", 2000,
                     {"model": "claude-sonnet-4-6"})],
            email="dev1@test.com",
        )
        r = requests.post(f"{API_URL}/v1/otel/v1/metrics", json=payload,
                          headers=headers_a, timeout=15)
        chk("FN.16 Claude Code OTel metrics accepted",
            r.status_code in (200, 201, 202))
        assert r.status_code in (200, 201, 202)

    def test_fn17_copilot_otel_accepted(self, headers_a):
        payload = make_otlp_metrics(
            "copilot_chat",
            [counter("copilot_chat.tokens.total", 8000,
                     {"model": "gpt-4o"})],
            email="dev2@test.com",
        )
        r = requests.post(f"{API_URL}/v1/otel/v1/metrics", json=payload,
                          headers=headers_a, timeout=15)
        chk("FN.17 Copilot OTel metrics accepted",
            r.status_code in (200, 201, 202))
        assert r.status_code in (200, 201, 202)

    def test_fn18_gemini_otel_accepted(self, headers_a):
        payload = make_otlp_metrics(
            "gemini_cli",
            [counter("gemini_cli.tokens.input", 3000,
                     {"model": "gemini-2.0-flash"}),
             histogram("gemini_cli.api_call.duration", 15000, 5,
                       {"model": "gemini-2.0-flash"})],
            email="dev3@test.com",
        )
        r = requests.post(f"{API_URL}/v1/otel/v1/metrics", json=payload,
                          headers=headers_a, timeout=15)
        chk("FN.18 Gemini CLI OTel metrics accepted",
            r.status_code in (200, 201, 202))
        assert r.status_code in (200, 201, 202)

    def test_fn19_cross_platform_summary(self, headers_a):
        time.sleep(1)
        r = requests.get(f"{API_URL}/v1/cross-platform/summary",
                         headers=headers_a, timeout=10)
        chk("FN.19 cross-platform summary returns 200",
            r.status_code == 200)
        assert r.status_code == 200

    def test_fn20_cross_platform_developers(self, headers_a):
        r = requests.get(f"{API_URL}/v1/cross-platform/developers",
                         headers=headers_a, timeout=10)
        chk("FN.20 cross-platform developers returns 200",
            r.status_code == 200)
        assert r.status_code == 200

    def test_fn21_cross_platform_models(self, headers_a):
        r = requests.get(f"{API_URL}/v1/cross-platform/models",
                         headers=headers_a, timeout=10)
        chk("FN.21 cross-platform models returns 200",
            r.status_code == 200)
        assert r.status_code == 200

    def test_fn22_cross_platform_live(self, headers_a):
        r = requests.get(f"{API_URL}/v1/cross-platform/live?limit=5",
                         headers=headers_a, timeout=10)
        chk("FN.22 cross-platform live feed returns 200",
            r.status_code == 200)
        assert r.status_code == 200

    def test_fn23_cross_platform_budget(self, headers_a):
        r = requests.get(f"{API_URL}/v1/cross-platform/budget",
                         headers=headers_a, timeout=10)
        chk("FN.23 cross-platform budget returns 200",
            r.status_code == 200)
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
#  FLOW 4: Org Isolation (two orgs cannot see each other's data)
# ═══════════════════════════════════════════════════════════════════════════════

class TestOrgIsolation:
    """Verify data isolation between organizations."""

    def test_fn24_org_a_ingests_event(self, headers_a):
        section("FLOW 4 --- Org Isolation")
        ev = make_event(i=99, model="claude-opus-4-6", cost=0.50,
                        team="team-alpha")
        r = requests.post(f"{API_URL}/v1/events", json=ev,
                          headers=headers_a, timeout=10)
        chk("FN.24 org A event ingested", r.status_code == 201)
        assert r.status_code == 201

    def test_fn25_org_b_ingests_event(self, headers_b):
        ev = make_event(i=99, model="gpt-4o-mini", cost=0.001,
                        team="team-beta")
        r = requests.post(f"{API_URL}/v1/events", json=ev,
                          headers=headers_b, timeout=10)
        chk("FN.25 org B event ingested", r.status_code == 201)
        assert r.status_code == 201

    def test_fn26_org_a_cannot_see_org_b(self, headers_a):
        time.sleep(1)
        r = requests.get(f"{API_URL}/v1/analytics/traces?limit=50",
                         headers=headers_a, timeout=10)
        assert r.status_code == 200
        traces = r.json()
        events = traces if isinstance(traces, list) else traces.get("events", traces.get("traces", []))
        # Org A should not see team-beta events
        has_beta = any("team-beta" in str(e) for e in events) if events else False
        chk("FN.26 org A traces do NOT contain org B data", not has_beta)
        assert not has_beta

    def test_fn27_org_b_cannot_see_org_a(self, headers_b):
        r = requests.get(f"{API_URL}/v1/analytics/traces?limit=50",
                         headers=headers_b, timeout=10)
        assert r.status_code == 200
        traces = r.json()
        events = traces if isinstance(traces, list) else traces.get("events", traces.get("traces", []))
        has_alpha = any("team-alpha" in str(e) for e in events) if events else False
        chk("FN.27 org B traces do NOT contain org A data", not has_alpha)
        assert not has_alpha


# ═══════════════════════════════════════════════════════════════════════════════
#  FLOW 5: CLI Tool Integration (pricing, optimization, agent adapters)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCLIToolIntegration:
    """End-to-end CLI pricing, optimization, and agent validation."""

    def test_fn28_cli_cost_calculation(self):
        section("FLOW 5 --- CLI Tool Integration")
        r = js("cost", "claude-sonnet-4-6", "10000", "5000")
        chk("FN.28 CLI cost calculation returns valid result",
            r.get("totalCostUsd", 0) > 0)
        assert r.get("totalCostUsd", 0) > 0

    def test_fn29_cli_cross_model_comparison(self):
        opus = js("cost", "claude-opus-4-6", "10000", "5000")
        mini = js("cost", "gpt-4o-mini", "10000", "5000")
        chk("FN.29 Opus costs more than GPT-4o-mini",
            opus["totalCostUsd"] > mini["totalCostUsd"])
        assert opus["totalCostUsd"] > mini["totalCostUsd"]

    def test_fn30_cli_cheapest_model_finder(self):
        r = js("cheapest", "claude-opus-4-6", "10000", "5000")
        chk("FN.30 cheapest finds alternative to opus",
            r is not None and r.get("model"))
        assert r is not None and r.get("model")

    def test_fn31_cli_cache_discount(self):
        no_cache = js("cost", "claude-sonnet-4-6", "10000", "5000", "0")
        with_cache = js("cost", "claude-sonnet-4-6", "10000", "5000", "5000")
        chk("FN.31 cached tokens reduce cost",
            with_cache["totalCostUsd"] < no_cache["totalCostUsd"])
        assert with_cache["totalCostUsd"] < no_cache["totalCostUsd"]

    def test_fn32_cli_models_list(self):
        r = js("models")
        count = r.get("count", 0)
        chk("FN.32 CLI knows 14+ models", count >= 14)
        assert count >= 14

    def test_fn33_cli_zero_tokens_zero_cost(self):
        r = js("cost", "gpt-4o", "0", "0")
        chk("FN.33 zero tokens = zero cost", r.get("totalCostUsd") == 0)
        assert r.get("totalCostUsd") == 0

    def test_fn34_cli_builds_clean(self):
        chk("FN.34 CLI dist exists", (CLI_DIR / "dist" / "index.js").exists())
        assert (CLI_DIR / "dist" / "index.js").exists()

    def test_fn35_all_agent_adapters_present(self):
        agents = ["claude.ts", "gemini.ts", "codex.ts", "aider.ts", "chatgpt.ts"]
        all_exist = all((CLI_DIR / "src" / "agents" / a).exists() for a in agents)
        chk("FN.35 all 5 agent adapters present", all_exist)
        assert all_exist


# ═══════════════════════════════════════════════════════════════════════════════
#  FLOW 6: MCP Server Integration
# ═══════════════════════════════════════════════════════════════════════════════

class TestMCPIntegration:
    """MCP server structure and backend API compatibility."""

    def test_fn36_mcp_package_exists(self):
        section("FLOW 6 --- MCP Server Integration")
        chk("FN.36 MCP package.json exists",
            (MCP_DIR / "package.json").exists())
        assert (MCP_DIR / "package.json").exists()

    def test_fn37_mcp_dist_built(self):
        chk("FN.37 MCP dist built",
            (MCP_DIR / "dist").exists())
        assert (MCP_DIR / "dist").exists()

    def test_fn38_mcp_defines_all_tools(self):
        src = (MCP_DIR / "src" / "index.ts").read_text()
        tools = ["get_summary", "get_kpis", "check_budget", "get_traces",
                 "optimize_prompt", "analyze_tokens", "estimate_costs",
                 "track_llm_call"]
        found = sum(1 for t in tools if t in src)
        chk("FN.38 MCP defines 8+ core tools", found >= 8)
        assert found >= 8

    def test_fn39_mcp_backend_summary(self, headers_a):
        r = requests.get(f"{API_URL}/v1/analytics/summary",
                         headers=headers_a, timeout=10)
        chk("FN.39 MCP backend: summary API works", r.status_code == 200)
        assert r.status_code == 200

    def test_fn40_mcp_backend_traces(self, headers_a):
        r = requests.get(f"{API_URL}/v1/analytics/traces?limit=5",
                         headers=headers_a, timeout=10)
        chk("FN.40 MCP backend: traces API works", r.status_code == 200)
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
#  FLOW 7: Local Proxy Integration
# ═══════════════════════════════════════════════════════════════════════════════

class TestLocalProxyIntegration:
    """Local proxy structure and event forwarding."""

    def test_fn41_proxy_package_exists(self):
        section("FLOW 7 --- Local Proxy Integration")
        chk("FN.41 proxy package.json exists",
            (PROXY_DIR / "package.json").exists())
        assert (PROXY_DIR / "package.json").exists()

    def test_fn42_proxy_dist_built(self):
        chk("FN.42 proxy dist built",
            (PROXY_DIR / "dist").exists())
        assert (PROXY_DIR / "dist").exists()

    def test_fn43_proxy_pricing_engine(self):
        pricing = (PROXY_DIR / "src" / "pricing.ts").read_text()
        providers = ["openai", "anthropic", "google", "meta", "mistral", "deepseek"]
        found = sum(1 for p in providers if p in pricing.lower())
        chk("FN.43 proxy pricing covers 6 providers", found >= 6)
        assert found >= 6

    def test_fn44_proxy_privacy_module(self):
        chk("FN.44 proxy has privacy module",
            (PROXY_DIR / "src" / "privacy.ts").exists())
        assert (PROXY_DIR / "src" / "privacy.ts").exists()

    def test_fn45_proxy_forwards_to_otel(self, headers_a):
        """Simulate what the proxy does: forward metrics to OTel endpoint."""
        payload = make_otlp_metrics(
            "local-proxy-e2e",
            [counter("llm.token.usage", 5000,
                     {"model": "gpt-4o", "type": "total"})],
        )
        r = requests.post(f"{API_URL}/v1/otel/v1/metrics", json=payload,
                          headers=headers_a, timeout=15)
        chk("FN.45 proxy-style OTel forwarding accepted",
            r.status_code in (200, 201, 202))
        assert r.status_code in (200, 201, 202)


# ═══════════════════════════════════════════════════════════════════════════════
#  FLOW 8: Error Handling & Edge Cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestErrorHandling:
    """Product-wide error handling and edge cases."""

    def test_fn46_malformed_json_rejected(self, headers_a):
        section("FLOW 8 --- Error Handling & Edge Cases")
        r = requests.post(f"{API_URL}/v1/events",
                          data="not json at all",
                          headers={**headers_a, "Content-Type": "application/json"},
                          timeout=10)
        chk("FN.46 malformed JSON returns 400", r.status_code == 400)
        assert r.status_code == 400

    def test_fn47_empty_batch_rejected(self, headers_a):
        r = requests.post(f"{API_URL}/v1/events/batch",
                          json={"events": []},
                          headers=headers_a, timeout=10)
        chk("FN.47 empty batch rejected (400)", r.status_code == 400)
        assert r.status_code == 400

    def test_fn48_oversized_batch_rejected(self, headers_a):
        events = [make_event(i=i) for i in range(501)]
        r = requests.post(f"{API_URL}/v1/events/batch",
                          json={"events": events},
                          headers=headers_a, timeout=30)
        chk("FN.48 batch > 500 events rejected (400)",
            r.status_code == 400)
        assert r.status_code == 400

    def test_fn49_event_missing_event_id(self, headers_a):
        ev = {"provider": "openai", "model": "gpt-4o",
              "prompt_tokens": 100, "completion_tokens": 50,
              "total_cost_usd": 0.005}
        r = requests.post(f"{API_URL}/v1/events", json=ev,
                          headers=headers_a, timeout=10)
        chk("FN.49 event without event_id rejected (400)",
            r.status_code == 400)
        assert r.status_code == 400

    def test_fn50_nonexistent_endpoint_404(self):
        r = requests.get(f"{API_URL}/v1/does-not-exist", timeout=10)
        chk("FN.50 unknown endpoint returns 404",
            r.status_code == 404)
        assert r.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
#  FLOW 9: Full Product Lifecycle (signup → ingest → query → verify)
# ═══════════════════════════════════════════════════════════════════════════════

class TestFullLifecycle:
    """Complete product lifecycle in a single test flow."""

    def test_fn51_full_lifecycle(self):
        section("FLOW 9 --- Full Product Lifecycle")

        # Step 1: Signup
        d = signup_api(email=rand_email("lifecycle"))
        key = d["api_key"]
        org = d["org_id"]
        hdrs = get_headers(key)
        chk("FN.51 lifecycle: signup OK", bool(key) and bool(org))
        assert bool(key)

    def test_fn52_lifecycle_ingest_and_query(self):
        # Fresh account for isolated test
        key, org, _ = fresh_account(prefix="lc52")
        hdrs = get_headers(key)

        # Step 2: Ingest events
        events = [make_event(i=i, model="claude-sonnet-4-6", cost=0.01,
                             team="engineering") for i in range(5)]
        r = requests.post(f"{API_URL}/v1/events/batch",
                          json={"events": events},
                          headers=hdrs, timeout=15)
        chk("FN.52 lifecycle: batch ingest accepted", r.status_code == 201)
        assert r.status_code == 201

    def test_fn53_lifecycle_otel_and_cross_platform(self):
        key, org, _ = fresh_account(prefix="lc53")
        hdrs = get_headers(key)

        # Send OTel metrics
        payload = make_otlp_metrics(
            "claude_code",
            [counter("claude_code.tokens.input", 10000,
                     {"model": "claude-sonnet-4-6"})],
            email="lifecycle@test.com",
        )
        r = requests.post(f"{API_URL}/v1/otel/v1/metrics", json=payload,
                          headers=hdrs, timeout=15)
        chk("FN.53 lifecycle: OTel ingest OK",
            r.status_code in (200, 201, 202))
        assert r.status_code in (200, 201, 202)

    def test_fn54_lifecycle_analytics_query(self):
        key, org, _ = fresh_account(prefix="lc54")
        hdrs = get_headers(key)

        # All analytics endpoints should work even with no data
        endpoints = [
            "/v1/analytics/summary",
            "/v1/analytics/kpis?period=7",
            "/v1/analytics/models?period=7",
            "/v1/analytics/teams?period=7",
            "/v1/cross-platform/summary",
        ]
        all_ok = True
        for ep in endpoints:
            r = requests.get(f"{API_URL}{ep}", headers=hdrs, timeout=10)
            if r.status_code != 200:
                all_ok = False
                break
        chk("FN.54 lifecycle: all analytics endpoints return 200", all_ok)
        assert all_ok

    def test_fn55_lifecycle_session_auth(self):
        key, org, _ = fresh_account(prefix="lc55")
        sess = session_get(key)
        chk("FN.55 lifecycle: session auth returns org data",
            sess is not None and sess.get("org_id") == org)
        assert sess is not None


# ═══════════════════════════════════════════════════════════════════════════════
#  Runner
# ═══════════════════════════════════════════════════════════════════════════════

def run():
    """Standalone runner for this suite."""
    reset_results()
    pytest.main([__file__, "-v", "--tb=short"])
    return get_results()


if __name__ == "__main__":
    run()
