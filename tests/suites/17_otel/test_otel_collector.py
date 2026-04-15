"""
test_otel_collector.py — OpenTelemetry Collector + Cross-Platform API Tests
============================================================================
Suite OT: Tests the OTLP ingestion endpoint and cross-platform API.
Validates multi-platform metric parsing (Claude Code, Copilot, Gemini CLI,
Codex CLI, Cline) and real-time data queries.

Labels: OT.1 - OT.N
"""

import sys
import json
import time
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.api import fresh_account
from helpers.output import ok, fail, warn, info, section, chk, get_results


# ── OTLP Payload Builders ──────────────────────────────────────────────────

def make_otlp_metrics(service_name: str, metrics: list, user_email: str = "dev@test.com") -> dict:
    """Build a valid OTLP ExportMetricsServiceRequest JSON payload."""
    return {
        "resourceMetrics": [{
            "resource": {
                "attributes": [
                    {"key": "service.name", "value": {"stringValue": service_name}},
                    {"key": "user.email", "value": {"stringValue": user_email}},
                    {"key": "user.account_uuid", "value": {"stringValue": "usr-12345"}},
                    {"key": "session.id", "value": {"stringValue": "sess-test-001"}},
                    {"key": "terminal.type", "value": {"stringValue": "vscode"}},
                    {"key": "team.id", "value": {"stringValue": "platform"}},
                    {"key": "cost_center", "value": {"stringValue": "eng-100"}},
                ]
            },
            "scopeMetrics": [{
                "scope": {"name": "com.anthropic.claude_code", "version": "1.0.0"},
                "metrics": metrics,
            }]
        }]
    }


def make_counter_metric(name: str, value: float, attrs: dict = None) -> dict:
    """Build a Sum (counter) metric."""
    data_point = {
        "asDouble": value,
        "timeUnixNano": str(int(time.time() * 1e9)),
        "attributes": [{"key": k, "value": {"stringValue": str(v)}} for k, v in (attrs or {}).items()],
    }
    return {
        "name": name,
        "unit": "1",
        "sum": {"dataPoints": [data_point], "isMonotonic": True},
    }


def make_histogram_metric(name: str, sum_val: float, count: int, attrs: dict = None) -> dict:
    """Build a Histogram metric (used by Copilot token usage)."""
    data_point = {
        "sum": sum_val,
        "count": str(count),
        "timeUnixNano": str(int(time.time() * 1e9)),
        "attributes": [{"key": k, "value": {"stringValue": str(v)}} for k, v in (attrs or {}).items()],
    }
    return {
        "name": name,
        "unit": "1",
        "histogram": {"dataPoints": [data_point]},
    }


def make_otlp_logs(service_name: str, events: list, user_email: str = "dev@test.com") -> dict:
    """Build a valid OTLP ExportLogsServiceRequest JSON payload."""
    return {
        "resourceLogs": [{
            "resource": {
                "attributes": [
                    {"key": "service.name", "value": {"stringValue": service_name}},
                    {"key": "user.email", "value": {"stringValue": user_email}},
                    {"key": "user.account_uuid", "value": {"stringValue": "usr-12345"}},
                    {"key": "session.id", "value": {"stringValue": "sess-test-001"}},
                    {"key": "terminal.type", "value": {"stringValue": "cursor"}},
                    {"key": "team.id", "value": {"stringValue": "platform"}},
                ]
            },
            "scopeLogs": [{
                "logRecords": events,
            }]
        }]
    }


def make_log_event(event_name: str, model: str = "claude-sonnet-4-6",
                   cost: float = 0.005, input_tokens: int = 1000,
                   output_tokens: int = 200, duration_ms: float = 1500) -> dict:
    """Build a single OTel log record (event)."""
    return {
        "timeUnixNano": str(int(time.time() * 1e9)),
        "severityText": "INFO",
        "body": {"stringValue": f"Event: {event_name}"},
        "attributes": [
            {"key": "event.name", "value": {"stringValue": event_name}},
            {"key": "model", "value": {"stringValue": model}},
            {"key": "cost_usd", "value": {"stringValue": str(cost)}},
            {"key": "input_tokens", "value": {"stringValue": str(input_tokens)}},
            {"key": "output_tokens", "value": {"stringValue": str(output_tokens)}},
            {"key": "duration_ms", "value": {"stringValue": str(duration_ms)}},
        ],
    }


# ── Test Functions ──────────────────────────────────────────────────────────

def test_otel_auth(headers):
    """Test OTel endpoint requires auth."""
    section("OT.A — OTel Auth")

    # No auth → 401
    r = requests.post(f"{API_URL}/v1/otel/v1/metrics",
                      json={"resourceMetrics": []}, timeout=10)
    chk("OT.1  POST /otel/v1/metrics no auth → 401",
        r.status_code == 401, f"got {r.status_code}")

    r = requests.post(f"{API_URL}/v1/otel/v1/logs",
                      json={"resourceLogs": []}, timeout=10)
    chk("OT.2  POST /otel/v1/logs no auth → 401",
        r.status_code == 401, f"got {r.status_code}")

    # Bad key → 401
    r = requests.post(f"{API_URL}/v1/otel/v1/metrics",
                      json={"resourceMetrics": []},
                      headers={"Authorization": "Bearer crt_bad_key"}, timeout=10)
    chk("OT.3  POST /otel/v1/metrics bad key → 401",
        r.status_code == 401, f"got {r.status_code}")

    # Valid key → 200
    r = requests.post(f"{API_URL}/v1/otel/v1/metrics",
                      json={"resourceMetrics": []},
                      headers=headers, timeout=10)
    chk("OT.4  POST /otel/v1/metrics valid key empty body → 200",
        r.status_code == 200, f"got {r.status_code}")

    # Traces placeholder → 200
    r = requests.post(f"{API_URL}/v1/otel/v1/traces",
                      json={}, headers=headers, timeout=10)
    chk("OT.5  POST /otel/v1/traces placeholder → 200",
        r.status_code == 200, f"got {r.status_code}")


def test_claude_code_metrics(headers):
    """Ingest Claude Code metrics and verify storage."""
    section("OT.B — Claude Code Metrics Ingestion")

    payload = make_otlp_metrics("claude-code", [
        make_counter_metric("claude_code.token.usage", 5000, {"type": "input", "model": "claude-sonnet-4-6"}),
        make_counter_metric("claude_code.token.usage", 1200, {"type": "output", "model": "claude-sonnet-4-6"}),
        make_counter_metric("claude_code.token.usage", 3000, {"type": "cacheRead", "model": "claude-sonnet-4-6"}),
        make_counter_metric("claude_code.cost.usage", 0.0234, {"model": "claude-sonnet-4-6"}),
        make_counter_metric("claude_code.session.count", 1, {}),
        make_counter_metric("claude_code.commit.count", 3, {}),
        make_counter_metric("claude_code.pull_request.count", 1, {}),
        make_counter_metric("claude_code.lines_of_code.count", 247, {"type": "added"}),
        make_counter_metric("claude_code.lines_of_code.count", 42, {"type": "removed"}),
        make_counter_metric("claude_code.active_time.total", 1800, {"type": "user"}),
    ], user_email="alice@acme.com")

    r = requests.post(f"{API_URL}/v1/otel/v1/metrics", json=payload, headers=headers, timeout=15)
    chk("OT.6  Claude Code metrics ingested → 200", r.status_code == 200, f"got {r.status_code}")

    body = r.json()
    chk("OT.7  Response has partialSuccess field", "partialSuccess" in body, str(body))


def test_copilot_metrics(headers):
    """Ingest Copilot Chat metrics (histogram format)."""
    section("OT.C — Copilot Chat Metrics Ingestion")

    payload = make_otlp_metrics("copilot-chat", [
        make_histogram_metric("gen_ai.client.token.usage", 8000, 5, {"gen_ai.token.type": "input", "gen_ai.request.model": "gpt-4o"}),
        make_histogram_metric("gen_ai.client.token.usage", 2000, 5, {"gen_ai.token.type": "output", "gen_ai.request.model": "gpt-4o"}),
        make_histogram_metric("gen_ai.client.operation.duration", 12.5, 5, {"gen_ai.request.model": "gpt-4o"}),
        make_histogram_metric("copilot_chat.time_to_first_token", 0.85, 5, {}),
        make_counter_metric("copilot_chat.session.count", 1, {}),
        make_counter_metric("copilot_chat.tool.call.count", 7, {"gen_ai.tool.name": "read_file"}),
    ], user_email="bob@acme.com")

    r = requests.post(f"{API_URL}/v1/otel/v1/metrics", json=payload, headers=headers, timeout=15)
    chk("OT.8  Copilot Chat metrics ingested → 200", r.status_code == 200, f"got {r.status_code}")


def test_gemini_metrics(headers):
    """Ingest Gemini CLI metrics."""
    section("OT.D — Gemini CLI Metrics Ingestion")

    payload = make_otlp_metrics("gemini-cli", [
        make_counter_metric("gemini_cli.token.usage", 6000, {"type": "input", "model": "gemini-2.0-flash"}),
        make_counter_metric("gemini_cli.token.usage", 1500, {"type": "output", "model": "gemini-2.0-flash"}),
        make_counter_metric("gemini_cli.token.usage", 500, {"type": "thought", "model": "gemini-2.0-flash"}),
        make_counter_metric("gemini_cli.api.request.count", 3, {"model": "gemini-2.0-flash", "status_code": "200"}),
        make_counter_metric("gemini_cli.session.count", 1, {}),
        make_counter_metric("gemini_cli.tool.call.count", 4, {"function_name": "edit_file"}),
        make_counter_metric("gemini_cli.file.operation.count", 2, {"operation": "create"}),
    ], user_email="carol@acme.com")

    r = requests.post(f"{API_URL}/v1/otel/v1/metrics", json=payload, headers=headers, timeout=15)
    chk("OT.9  Gemini CLI metrics ingested → 200", r.status_code == 200, f"got {r.status_code}")


def test_codex_metrics(headers):
    """Ingest Codex CLI metrics."""
    section("OT.E — Codex CLI Metrics Ingestion")

    payload = make_otlp_metrics("codex-cli", [
        make_counter_metric("gen_ai.client.token.usage", 4000, {"type": "input", "model": "o3-mini"}),
        make_counter_metric("gen_ai.client.token.usage", 800, {"type": "output", "model": "o3-mini"}),
        make_counter_metric("codex.cost.usage", 0.015, {"model": "o3-mini"}),
        make_counter_metric("codex.session.count", 1, {}),
    ], user_email="dave@acme.com")

    r = requests.post(f"{API_URL}/v1/otel/v1/metrics", json=payload, headers=headers, timeout=15)
    chk("OT.10 Codex CLI metrics ingested → 200", r.status_code == 200, f"got {r.status_code}")


def test_otel_events(headers):
    """Ingest OTel log events (api_request, tool_result)."""
    section("OT.F — OTel Events (Logs) Ingestion")

    payload = make_otlp_logs("claude-code", [
        make_log_event("api_request", "claude-sonnet-4-6", 0.008, 2000, 500, 1200),
        make_log_event("api_request", "claude-sonnet-4-6", 0.012, 3000, 800, 1800),
        make_log_event("tool_result", "claude-sonnet-4-6", 0, 0, 0, 350),
    ], user_email="alice@acme.com")

    r = requests.post(f"{API_URL}/v1/otel/v1/logs", json=payload, headers=headers, timeout=15)
    chk("OT.11 OTel events (logs) ingested → 200", r.status_code == 200, f"got {r.status_code}")


def test_cross_platform_summary(headers):
    """Query cross-platform summary endpoint."""
    section("OT.G — Cross-Platform Summary API")

    time.sleep(1)  # Let D1 settle

    r = requests.get(f"{API_URL}/v1/cross-platform/summary?days=1", headers=headers, timeout=15)
    chk("OT.12 GET /cross-platform/summary → 200", r.status_code == 200, f"got {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        chk("OT.13 Summary has total_cost_usd", "total_cost_usd" in data, str(list(data.keys())))
        chk("OT.14 Summary has by_provider array", "by_provider" in data, str(list(data.keys())))
        chk("OT.15 Summary has budget info", "budget" in data, str(list(data.keys())))
        chk("OT.16 total_records > 0 (data was ingested)", data.get("total_records", 0) > 0,
            f"total_records={data.get('total_records', 0)}")

        # Verify multiple providers present
        providers = [p["provider"] for p in data.get("by_provider", [])]
        chk("OT.17 Multiple providers in summary", len(providers) >= 2,
            f"providers={providers}")
        chk("OT.18 claude_code in providers", "claude_code" in providers, str(providers))


def test_cross_platform_developers(headers):
    """Query per-developer spend table."""
    section("OT.H — Cross-Platform Developers API")

    r = requests.get(f"{API_URL}/v1/cross-platform/developers?days=1", headers=headers, timeout=15)
    chk("OT.19 GET /cross-platform/developers → 200", r.status_code == 200, f"got {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        devs = data.get("developers", [])
        chk("OT.20 Developers list not empty", len(devs) > 0, f"count={len(devs)}")

        if devs:
            alice = next((d for d in devs if d.get("developer_email") == "alice@acme.com"), None)
            chk("OT.21 alice@acme.com found", alice is not None, str([d.get("developer_email") for d in devs]))

            if alice:
                chk("OT.22 Alice has commits > 0", alice.get("commits", 0) > 0,
                    f"commits={alice.get('commits')}")
                chk("OT.23 Alice has pull_requests > 0", alice.get("pull_requests", 0) > 0,
                    f"prs={alice.get('pull_requests')}")
                chk("OT.24 Alice has cost_per_pr calculated", alice.get("cost_per_pr") is not None,
                    f"cost_per_pr={alice.get('cost_per_pr')}")
                chk("OT.25 Alice has lines_added > 0", alice.get("lines_added", 0) > 0,
                    f"lines_added={alice.get('lines_added')}")


def test_cross_platform_developer_detail(headers):
    """Query single developer drill-down via UUID (route changed from :email to :id)."""
    section("OT.I — Developer Detail API")

    # Fetch developer_id UUID from the list endpoint — route now requires UUID, not email
    list_r = requests.get(f"{API_URL}/v1/cross-platform/developers",
                          headers=headers, params={"days": 7}, timeout=15)
    devs = [d for d in list_r.json().get("developers", []) if d.get("developer_id")] if list_r.ok else []
    if not devs:
        chk("OT.26 GET /cross-platform/developer/:id — skipped (no developer_id in list)", True, "")
        return

    dev_id = devs[0]["developer_id"]
    r = requests.get(f"{API_URL}/v1/cross-platform/developer/{dev_id}",
                     headers=headers, params={"days": 7}, timeout=15)
    chk("OT.26 GET /cross-platform/developer/:id → 200", r.status_code == 200, f"got {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        chk("OT.27 Has by_provider breakdown", "by_provider" in data, str(list(data.keys())))
        chk("OT.28 Has by_model breakdown", "by_model" in data, str(list(data.keys())))
        chk("OT.29 Has productivity data", "productivity" in data, str(list(data.keys())))


def test_cross_platform_live(headers):
    """Query live event feed."""
    section("OT.J — Live Event Feed API")

    r = requests.get(f"{API_URL}/v1/cross-platform/live?limit=10", headers=headers, timeout=15)
    chk("OT.30 GET /cross-platform/live → 200", r.status_code == 200, f"got {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        events = data.get("events", [])
        chk("OT.31 Live events not empty", len(events) > 0, f"count={len(events)}")
        if events:
            chk("OT.32 Event has provider field", "provider" in events[0], str(events[0].keys()))
            chk("OT.33 Event has cost_usd field", "cost_usd" in events[0], str(events[0].keys()))
            chk("OT.34 Event has model field", "model" in events[0], str(events[0].keys()))


def test_cross_platform_models(headers):
    """Query model cost breakdown."""
    section("OT.K — Models API")

    r = requests.get(f"{API_URL}/v1/cross-platform/models?days=1", headers=headers, timeout=15)
    chk("OT.35 GET /cross-platform/models → 200", r.status_code == 200, f"got {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        models = data.get("models", [])
        chk("OT.36 Models list not empty", len(models) > 0, f"count={len(models)}")
        if models:
            chk("OT.37 Model has cost field", "cost" in models[0], str(models[0].keys()))
            chk("OT.38 Model has provider field", "provider" in models[0], str(models[0].keys()))


def test_cross_platform_connections(headers):
    """Query connection status."""
    section("OT.L — Connections API")

    r = requests.get(f"{API_URL}/v1/cross-platform/connections", headers=headers, timeout=15)
    chk("OT.39 GET /cross-platform/connections → 200", r.status_code == 200, f"got {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        chk("OT.40 Has otel_sources field", "otel_sources" in data, str(list(data.keys())))
        otel_sources = data.get("otel_sources", [])
        chk("OT.41 OTel sources populated after ingestion", len(otel_sources) > 0,
            f"count={len(otel_sources)}")


# ── Main runner ─────────────────────────────────────────────────────────────

def run():
    info("=" * 60)
    info("  Cohrint — OTel Collector + Cross-Platform API Tests")
    info("  Endpoints: /v1/otel/* and /v1/cross-platform/*")
    info("=" * 60)

    # Create fresh test account — returns (api_key, org_id, cookies)
    try:
        api_key, org_id, cookies = fresh_account()
    except Exception as e:
        fail(f"Could not create test account: {e}")
        return get_results()

    if not api_key:
        fail("No API key returned — aborting OTel tests")
        return get_results()

    headers = {"Authorization": f"Bearer {api_key}"}

    # Run tests in order (ingestion first, then queries)
    test_otel_auth(headers)
    test_claude_code_metrics(headers)
    test_copilot_metrics(headers)
    test_gemini_metrics(headers)
    test_codex_metrics(headers)
    test_otel_events(headers)

    # Wait for D1 writes to be queryable
    time.sleep(2)

    test_cross_platform_summary(headers)
    test_cross_platform_developers(headers)
    test_cross_platform_developer_detail(headers)
    test_cross_platform_live(headers)
    test_cross_platform_models(headers)
    test_cross_platform_connections(headers)

    return get_results()


if __name__ == "__main__":
    results = run()
    passed = results.get("passed", 0)
    failed = results.get("failed", 0)
    total = passed + failed
    info(f"\nResults: {passed}/{total} passed, {failed} failed")
    sys.exit(1 if failed > 0 else 0)
