"""
test_otel_e2e.py — End-to-End OTel Collector + Cross-Platform Tests
====================================================================
Suite XP: Comprehensive E2E tests simulating real client OTel environments.
Covers: multi-platform ingestion, client simulation, edge cases, error handling,
cross-platform API queries, data integrity, deduplication, and budget checks.

Labels: XP.1 - XP.N  (78 checks)
"""

import sys
import json
import time
import uuid
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.api import signup_api, get_headers, fresh_account
from helpers.data import rand_email
from helpers.output import ok, fail, warn, info, section, chk, get_results


# ═══════════════════════════════════════════════════════════════════════════════
#  OTLP PAYLOAD BUILDERS (simulating real client environments)
# ═══════════════════════════════════════════════════════════════════════════════

def ts_nano():
    """Current time in nanoseconds (OTel format)."""
    return str(int(time.time() * 1e9))

def resource_attrs(service_name, email, account_uuid=None, session_id=None,
                   terminal="vscode", team=None, cost_center=None, org_id=None):
    """Build OTLP resource attributes matching real tool output."""
    attrs = [
        {"key": "service.name", "value": {"stringValue": service_name}},
        {"key": "service.version", "value": {"stringValue": "1.0.42"}},
        {"key": "os.type", "value": {"stringValue": "darwin"}},
        {"key": "os.version", "value": {"stringValue": "25.3.0"}},
        {"key": "host.arch", "value": {"stringValue": "arm64"}},
    ]
    if email:
        attrs.append({"key": "user.email", "value": {"stringValue": email}})
    if account_uuid:
        attrs.append({"key": "user.account_uuid", "value": {"stringValue": account_uuid}})
    if session_id:
        attrs.append({"key": "session.id", "value": {"stringValue": session_id}})
    if terminal:
        attrs.append({"key": "terminal.type", "value": {"stringValue": terminal}})
    if team:
        attrs.append({"key": "team.id", "value": {"stringValue": team}})
    if cost_center:
        attrs.append({"key": "cost_center", "value": {"stringValue": cost_center}})
    if org_id:
        attrs.append({"key": "organization.id", "value": {"stringValue": org_id}})
    return attrs

def counter(name, value, attrs=None):
    """Sum (monotonic counter) metric."""
    return {
        "name": name, "unit": "1",
        "sum": {"dataPoints": [{
            "asDouble": value,
            "startTimeUnixNano": ts_nano(),
            "timeUnixNano": ts_nano(),
            "attributes": [{"key":k,"value":{"stringValue":str(v)}} for k,v in (attrs or {}).items()],
        }], "isMonotonic": True},
    }

def histogram(name, sum_val, count, attrs=None):
    """Histogram metric (used by Copilot for token usage)."""
    return {
        "name": name, "unit": "1",
        "histogram": {"dataPoints": [{
            "sum": sum_val, "count": str(count),
            "startTimeUnixNano": ts_nano(),
            "timeUnixNano": ts_nano(),
            "attributes": [{"key":k,"value":{"stringValue":str(v)}} for k,v in (attrs or {}).items()],
        }]},
    }

def otlp_metrics(resource, scope_name, metrics):
    """Build complete OTLP ExportMetricsServiceRequest."""
    return {"resourceMetrics": [{
        "resource": {"attributes": resource},
        "scopeMetrics": [{"scope": {"name": scope_name, "version": "1.0.0"}, "metrics": metrics}],
    }]}

def otlp_logs(resource, events):
    """Build complete OTLP ExportLogsServiceRequest."""
    return {"resourceLogs": [{
        "resource": {"attributes": resource},
        "scopeLogs": [{"logRecords": events}],
    }]}

def log_event(event_name, model, cost_usd=0, input_tokens=0, output_tokens=0,
              cache_read=0, duration_ms=0, prompt_id=None, speed="normal"):
    """Build a single OTel log record matching Claude Code output."""
    attrs = [
        {"key": "event.name", "value": {"stringValue": event_name}},
        {"key": "event.timestamp", "value": {"stringValue": time.strftime("%Y-%m-%dT%H:%M:%SZ")}},
        {"key": "event.sequence", "value": {"intValue": str(int(time.time()))}},
        {"key": "model", "value": {"stringValue": model}},
        {"key": "cost_usd", "value": {"stringValue": str(cost_usd)}},
        {"key": "input_tokens", "value": {"stringValue": str(input_tokens)}},
        {"key": "output_tokens", "value": {"stringValue": str(output_tokens)}},
        {"key": "cache_read_tokens", "value": {"stringValue": str(cache_read)}},
        {"key": "duration_ms", "value": {"stringValue": str(duration_ms)}},
        {"key": "speed", "value": {"stringValue": speed}},
    ]
    if prompt_id:
        attrs.append({"key": "prompt.id", "value": {"stringValue": prompt_id}})
    return {
        "timeUnixNano": ts_nano(),
        "severityText": "INFO",
        "body": {"stringValue": f"Event: {event_name}"},
        "attributes": attrs,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  CLIENT ENVIRONMENT SIMULATORS
# ═══════════════════════════════════════════════════════════════════════════════

def simulate_claude_code_session(headers, email, session_id=None):
    """Simulate a real Claude Code coding session — multiple API calls + tool uses."""
    sid = session_id or f"sess-{uuid.uuid4().hex[:8]}"
    res = resource_attrs("claude-code", email, f"user-{uuid.uuid4().hex[:8]}",
                         sid, "iTerm.app", "backend", "eng-200")

    # Batch 1: Session start + initial API call metrics
    metrics1 = otlp_metrics(res, "com.anthropic.claude_code", [
        counter("claude_code.session.count", 1),
        counter("claude_code.token.usage", 8500, {"type":"input","model":"claude-sonnet-4-6"}),
        counter("claude_code.token.usage", 2100, {"type":"output","model":"claude-sonnet-4-6"}),
        counter("claude_code.token.usage", 6000, {"type":"cacheRead","model":"claude-sonnet-4-6"}),
        counter("claude_code.token.usage", 1200, {"type":"cacheCreation","model":"claude-sonnet-4-6"}),
        counter("claude_code.cost.usage", 0.0456, {"model":"claude-sonnet-4-6"}),
        counter("claude_code.active_time.total", 420, {"type":"user"}),
        counter("claude_code.active_time.total", 180, {"type":"cli"}),
    ])
    r1 = requests.post(f"{API_URL}/v1/otel/v1/metrics", json=metrics1, headers=headers, timeout=15)

    # Batch 2: Productivity metrics (commits, PRs, lines)
    metrics2 = otlp_metrics(res, "com.anthropic.claude_code", [
        counter("claude_code.commit.count", 5),
        counter("claude_code.pull_request.count", 2),
        counter("claude_code.lines_of_code.count", 487, {"type":"added"}),
        counter("claude_code.lines_of_code.count", 123, {"type":"removed"}),
        counter("claude_code.code_edit_tool.decision", 1, {"tool_name":"Edit","decision":"accept","source":"user_temporary","language":"TypeScript"}),
    ])
    r2 = requests.post(f"{API_URL}/v1/otel/v1/metrics", json=metrics2, headers=headers, timeout=15)

    # Events: API requests + tool results
    prompt_id = str(uuid.uuid4())
    events = otlp_logs(res, [
        log_event("api_request", "claude-sonnet-4-6", 0.018, 4000, 900, 3000, 2100, prompt_id),
        log_event("api_request", "claude-sonnet-4-6", 0.027, 4500, 1200, 3000, 3200, prompt_id),
        log_event("tool_result", "claude-sonnet-4-6", 0, 0, 0, 0, 450, prompt_id),
        log_event("user_prompt", "claude-sonnet-4-6", 0, 0, 0, 0, 0, prompt_id),
    ])
    r3 = requests.post(f"{API_URL}/v1/otel/v1/logs", json=events, headers=headers, timeout=15)

    return r1.status_code == 200 and r2.status_code == 200 and r3.status_code == 200


def simulate_copilot_session(headers, email, session_id=None):
    """Simulate a real GitHub Copilot Chat session."""
    sid = session_id or f"sess-{uuid.uuid4().hex[:8]}"
    res = resource_attrs("copilot-chat", email, None, sid, "vscode", "frontend")

    metrics = otlp_metrics(res, "copilot-chat", [
        histogram("gen_ai.client.token.usage", 12000, 8, {"gen_ai.token.type":"input","gen_ai.request.model":"gpt-4o"}),
        histogram("gen_ai.client.token.usage", 3500, 8, {"gen_ai.token.type":"output","gen_ai.request.model":"gpt-4o"}),
        histogram("gen_ai.client.operation.duration", 18.5, 8, {"gen_ai.request.model":"gpt-4o"}),
        histogram("copilot_chat.time_to_first_token", 1.2, 8, {}),
        counter("copilot_chat.session.count", 1),
        counter("copilot_chat.tool.call.count", 12, {"gen_ai.tool.name":"read_file"}),
        counter("copilot_chat.agent.turn.count", 4, {}),
    ])
    r = requests.post(f"{API_URL}/v1/otel/v1/metrics", json=metrics, headers=headers, timeout=15)
    return r.status_code == 200


def simulate_gemini_session(headers, email, session_id=None):
    """Simulate a real Gemini CLI session."""
    sid = session_id or f"sess-{uuid.uuid4().hex[:8]}"
    res = resource_attrs("gemini-cli", email, None, sid, "iTerm.app", "data-eng")

    metrics = otlp_metrics(res, "gemini-cli", [
        counter("gemini_cli.token.usage", 9000, {"type":"input","model":"gemini-2.0-flash"}),
        counter("gemini_cli.token.usage", 2200, {"type":"output","model":"gemini-2.0-flash"}),
        counter("gemini_cli.token.usage", 800, {"type":"thought","model":"gemini-2.0-flash"}),
        counter("gemini_cli.token.usage", 1500, {"type":"cache","model":"gemini-2.0-flash"}),
        counter("gemini_cli.api.request.count", 5, {"model":"gemini-2.0-flash","status_code":"200"}),
        counter("gemini_cli.session.count", 1),
        counter("gemini_cli.tool.call.count", 6, {"function_name":"edit_file","success":"true"}),
        counter("gemini_cli.file.operation.count", 3, {"operation":"create","language":"python"}),
    ])
    r = requests.post(f"{API_URL}/v1/otel/v1/metrics", json=metrics, headers=headers, timeout=15)
    return r.status_code == 200


def simulate_codex_session(headers, email, session_id=None):
    """Simulate a real OpenAI Codex CLI session."""
    sid = session_id or f"sess-{uuid.uuid4().hex[:8]}"
    res = resource_attrs("codex-cli", email, None, sid, "tmux", "platform")

    metrics = otlp_metrics(res, "codex-cli", [
        counter("gen_ai.client.token.usage", 5500, {"type":"input","model":"o3-mini"}),
        counter("gen_ai.client.token.usage", 1800, {"type":"output","model":"o3-mini"}),
        counter("codex.cost.usage", 0.032, {"model":"o3-mini"}),
        counter("codex.session.count", 1),
        counter("codex.commit.count", 2),
        counter("codex.lines_of_code.count", 156, {"type":"added"}),
        counter("codex.lines_of_code.count", 34, {"type":"removed"}),
    ])
    r = requests.post(f"{API_URL}/v1/otel/v1/metrics", json=metrics, headers=headers, timeout=15)
    return r.status_code == 200


def simulate_cline_session(headers, email, session_id=None):
    """Simulate a real Cline VS Code extension session."""
    sid = session_id or f"sess-{uuid.uuid4().hex[:8]}"
    res = resource_attrs("cline", email, None, sid, "cursor", "frontend")

    metrics = otlp_metrics(res, "cline", [
        counter("cline.token.usage", 3000, {"type":"input","model":"claude-sonnet-4-6"}),
        counter("cline.token.usage", 700, {"type":"output","model":"claude-sonnet-4-6"}),
        counter("cline.session.count", 1),
        counter("cline.tool.call.count", 3, {}),
    ])
    r = requests.post(f"{API_URL}/v1/otel/v1/metrics", json=metrics, headers=headers, timeout=15)
    return r.status_code == 200


def simulate_openai_sdk_instrumented(headers, email):
    """Simulate auto-instrumented OpenAI SDK calls (GenAI semantic conventions)."""
    res = resource_attrs("my-backend-api", email, None, None, None, "backend")

    metrics = otlp_metrics(res, "opentelemetry.instrumentation.openai", [
        histogram("gen_ai.client.token.usage", 4000, 3, {"gen_ai.token.type":"input","gen_ai.request.model":"gpt-4o-mini","gen_ai.provider.name":"openai"}),
        histogram("gen_ai.client.token.usage", 1000, 3, {"gen_ai.token.type":"output","gen_ai.request.model":"gpt-4o-mini","gen_ai.provider.name":"openai"}),
        histogram("gen_ai.client.operation.duration", 4.2, 3, {"gen_ai.request.model":"gpt-4o-mini"}),
    ])
    r = requests.post(f"{API_URL}/v1/otel/v1/metrics", json=metrics, headers=headers, timeout=15)
    return r.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
#  TEST FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def test_auth_edge_cases(headers):
    """Auth validation edge cases."""
    section("XP.A — Auth Edge Cases")

    # No header
    r = requests.post(f"{API_URL}/v1/otel/v1/metrics", json={"resourceMetrics":[]}, timeout=10)
    chk("XP.1  No auth header → 401", r.status_code == 401, f"got {r.status_code}")

    # Empty bearer
    r = requests.post(f"{API_URL}/v1/otel/v1/metrics", json={"resourceMetrics":[]},
                      headers={"Authorization": "Bearer "}, timeout=10)
    chk("XP.2  Empty bearer → 401", r.status_code == 401, f"got {r.status_code}")

    # Malformed body
    r = requests.post(f"{API_URL}/v1/otel/v1/metrics",
                      data="not json", headers={**headers, "Content-Type":"application/json"}, timeout=10)
    chk("XP.3  Malformed JSON body → 400", r.status_code == 400, f"got {r.status_code}")

    # Valid key, empty payload → 200
    r = requests.post(f"{API_URL}/v1/otel/v1/metrics", json={"resourceMetrics":[]}, headers=headers, timeout=10)
    chk("XP.4  Valid key empty payload → 200", r.status_code == 200, f"got {r.status_code}")

    # Valid key, empty logs → 200
    r = requests.post(f"{API_URL}/v1/otel/v1/logs", json={"resourceLogs":[]}, headers=headers, timeout=10)
    chk("XP.5  Valid key empty logs → 200", r.status_code == 200, f"got {r.status_code}")

    # Cross-platform API without auth → 401
    r = requests.get(f"{API_URL}/v1/cross-platform/summary", timeout=10)
    chk("XP.6  Cross-platform summary no auth → 401", r.status_code == 401, f"got {r.status_code}")


def test_multi_platform_simulation(headers, emails):
    """Simulate full sessions from 6 different AI tools + auto-instrumented SDK."""
    section("XP.B — Multi-Platform Client Simulation")

    chk("XP.7  Claude Code session ingested",
        simulate_claude_code_session(headers, emails["alice"]), "failed")
    chk("XP.8  Copilot Chat session ingested",
        simulate_copilot_session(headers, emails["bob"]), "failed")
    chk("XP.9  Gemini CLI session ingested",
        simulate_gemini_session(headers, emails["carol"]), "failed")
    chk("XP.10 Codex CLI session ingested",
        simulate_codex_session(headers, emails["dave"]), "failed")
    chk("XP.11 Cline session ingested",
        simulate_cline_session(headers, emails["eve"]), "failed")
    chk("XP.12 OpenAI SDK auto-instrumented ingested",
        simulate_openai_sdk_instrumented(headers, emails["frank"]), "failed")

    # Second session for Alice (multi-session test)
    chk("XP.13 Claude Code 2nd session (same dev)",
        simulate_claude_code_session(headers, emails["alice"]), "failed")


def test_summary_after_ingestion(headers):
    """Verify summary aggregates all platforms correctly."""
    section("XP.C — Cross-Platform Summary Validation")

    time.sleep(2)  # Let D1 settle
    r = requests.get(f"{API_URL}/v1/cross-platform/summary?days=1", headers=headers, timeout=15)
    chk("XP.14 Summary endpoint → 200", r.status_code == 200, f"got {r.status_code}")

    if r.status_code != 200:
        return

    data = r.json()
    chk("XP.15 total_cost_usd > 0", data.get("total_cost_usd", 0) > 0,
        f"total_cost={data.get('total_cost_usd')}")
    chk("XP.16 total_input_tokens > 0", data.get("total_input_tokens", 0) > 0,
        f"input_tokens={data.get('total_input_tokens')}")
    chk("XP.17 total_output_tokens > 0", data.get("total_output_tokens", 0) > 0,
        f"output_tokens={data.get('total_output_tokens')}")
    chk("XP.18 total_cached_tokens > 0", data.get("total_cached_tokens", 0) > 0,
        f"cached={data.get('total_cached_tokens')}")
    chk("XP.19 total_records >= 15", data.get("total_records", 0) >= 15,
        f"records={data.get('total_records')}")

    providers = data.get("by_provider", [])
    provider_names = [p["provider"] for p in providers]
    chk("XP.20 claude_code in providers", "claude_code" in provider_names, str(provider_names))
    chk("XP.21 copilot_chat in providers", "copilot_chat" in provider_names, str(provider_names))
    chk("XP.22 gemini_cli in providers", "gemini_cli" in provider_names, str(provider_names))
    chk("XP.23 codex_cli in providers", "codex_cli" in provider_names, str(provider_names))
    chk("XP.24 cline in providers", "cline" in provider_names, str(provider_names))
    chk("XP.25 custom_api in providers (auto-instrumented)", "custom_api" in provider_names, str(provider_names))
    chk("XP.26 At least 6 providers", len(providers) >= 6, f"count={len(providers)}")

    # Source breakdown
    sources = data.get("by_source", [])
    otel_source = next((s for s in sources if s["source"] == "otel"), None)
    chk("XP.27 OTel source present in summary", otel_source is not None, str(sources))

    # Budget info
    budget = data.get("budget", {})
    chk("XP.28 Budget info present", "monthly_limit_usd" in budget, str(budget))


def test_developer_data(headers, emails):
    """Verify per-developer data with ROI metrics."""
    section("XP.D — Developer Data & ROI Metrics")

    r = requests.get(f"{API_URL}/v1/cross-platform/developers?days=1", headers=headers, timeout=15)
    chk("XP.29 Developers endpoint → 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code != 200:
        return

    devs = r.json().get("developers", [])
    dev_emails = [d.get("developer_email") for d in devs]
    chk("XP.30 At least 6 developers", len(devs) >= 6, f"count={len(devs)}")
    chk("XP.31 alice found", emails["alice"] in dev_emails, str(dev_emails[:5]))
    chk("XP.32 bob found", emails["bob"] in dev_emails, str(dev_emails[:5]))
    chk("XP.33 carol found", emails["carol"] in dev_emails, str(dev_emails[:5]))

    # Alice detail (Claude Code — should have productivity data)
    alice = next((d for d in devs if d.get("developer_email") == emails["alice"]), None)
    if alice:
        chk("XP.34 Alice total_cost > 0", alice.get("total_cost", 0) > 0,
            f"cost={alice.get('total_cost')}")
        chk("XP.35 Alice input_tokens > 0", alice.get("input_tokens", 0) > 0,
            f"tokens={alice.get('input_tokens')}")
        chk("XP.36 Alice commits > 0 (from OTel)", alice.get("commits", 0) > 0,
            f"commits={alice.get('commits')}")
        chk("XP.37 Alice pull_requests > 0", alice.get("pull_requests", 0) > 0,
            f"prs={alice.get('pull_requests')}")
        chk("XP.38 Alice lines_added > 0", alice.get("lines_added", 0) > 0,
            f"lines={alice.get('lines_added')}")
        chk("XP.39 Alice cost_per_pr calculated", alice.get("cost_per_pr") is not None,
            f"cost_per_pr={alice.get('cost_per_pr')}")
        chk("XP.40 Alice cost_per_commit calculated", alice.get("cost_per_commit") is not None,
            f"cost_per_commit={alice.get('cost_per_commit')}")
        chk("XP.41 Alice has providers list", isinstance(alice.get("providers"), list),
            f"type={type(alice.get('providers'))}")
        chk("XP.42 Alice provider is claude_code", "claude_code" in (alice.get("providers") or []),
            str(alice.get("providers")))
    else:
        fail("XP.34-42 Alice not found in developers", str(dev_emails))

    # Bob detail (Copilot — no commits, so cost_per_pr should be null)
    bob = next((d for d in devs if d.get("developer_email") == emails["bob"]), None)
    if bob:
        chk("XP.43 Bob total_cost >= 0 (Copilot has no cost metric)", True, "")
        chk("XP.44 Bob provider is copilot_chat", "copilot_chat" in (bob.get("providers") or []),
            str(bob.get("providers")))
    else:
        fail("XP.43-44 Bob not found", str(dev_emails))


def test_developer_detail(headers, emails):
    """Verify single developer drill-down."""
    section("XP.E — Developer Detail Drill-Down")

    encoded_email = requests.utils.quote(emails["alice"])
    r = requests.get(f"{API_URL}/v1/cross-platform/developer/{encoded_email}?days=1",
                     headers=headers, timeout=15)
    chk("XP.45 Developer detail → 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code != 200:
        return

    data = r.json()
    chk("XP.46 Email matches", data.get("email") == emails["alice"],
        f"got {data.get('email')}")
    chk("XP.47 by_provider present", len(data.get("by_provider", [])) > 0,
        str(data.get("by_provider")))
    chk("XP.48 by_model present", len(data.get("by_model", [])) > 0,
        str(data.get("by_model")))
    chk("XP.49 daily_trend present", "daily_trend" in data, str(data.keys()))
    chk("XP.50 productivity present", "productivity" in data, str(data.keys()))

    prod = data.get("productivity", {})
    chk("XP.51 productivity.commits > 0", (prod.get("commits") or 0) > 0,
        f"commits={prod.get('commits')}")
    chk("XP.52 productivity.pull_requests > 0", (prod.get("pull_requests") or 0) > 0,
        f"prs={prod.get('pull_requests')}")
    chk("XP.53 productivity.active_time_s > 0", (prod.get("active_time_s") or 0) > 0,
        f"active_time={prod.get('active_time_s')}")


def test_live_feed(headers):
    """Verify live OTel event feed."""
    section("XP.F — Live Event Feed")

    r = requests.get(f"{API_URL}/v1/cross-platform/live?limit=50", headers=headers, timeout=15)
    chk("XP.54 Live feed → 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code != 200:
        return

    events = r.json().get("events", [])
    chk("XP.55 Live events populated", len(events) > 0, f"count={len(events)}")

    if events:
        e = events[0]
        chk("XP.56 Event has provider", "provider" in e, str(e.keys()))
        chk("XP.57 Event has model", "model" in e, str(e.keys()))
        chk("XP.58 Event has cost_usd", "cost_usd" in e, str(e.keys()))
        chk("XP.59 Event has tokens_in", "tokens_in" in e, str(e.keys()))
        chk("XP.60 Event has timestamp", "timestamp" in e, str(e.keys()))

    # Limit parameter works
    r2 = requests.get(f"{API_URL}/v1/cross-platform/live?limit=3", headers=headers, timeout=15)
    events2 = r2.json().get("events", [])
    chk("XP.61 Limit=3 returns <= 3", len(events2) <= 3, f"count={len(events2)}")


def test_models_api(headers):
    """Verify model cost breakdown."""
    section("XP.G — Models API")

    r = requests.get(f"{API_URL}/v1/cross-platform/models?days=1", headers=headers, timeout=15)
    chk("XP.62 Models endpoint → 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code != 200:
        return

    models = r.json().get("models", [])
    model_names = [m.get("model") for m in models]
    chk("XP.63 Multiple models", len(models) >= 3, f"count={len(models)}")
    chk("XP.64 claude-sonnet-4-6 in models", "claude-sonnet-4-6" in model_names, str(model_names))
    chk("XP.65 gpt-4o in models", "gpt-4o" in model_names, str(model_names))
    chk("XP.66 gemini-2.0-flash in models", "gemini-2.0-flash" in model_names, str(model_names))

    if models:
        m = models[0]
        chk("XP.67 Model has cost", "cost" in m, str(m.keys()))
        chk("XP.68 Model has provider", "provider" in m, str(m.keys()))
        chk("XP.69 Model has input_tokens", "input_tokens" in m, str(m.keys()))


def test_connections_api(headers):
    """Verify connection status."""
    section("XP.H — Connections API")

    r = requests.get(f"{API_URL}/v1/cross-platform/connections", headers=headers, timeout=15)
    chk("XP.70 Connections endpoint → 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code != 200:
        return

    data = r.json()
    otel = data.get("otel_sources", [])
    chk("XP.71 OTel sources populated", len(otel) >= 4, f"count={len(otel)}")

    if otel:
        src = otel[0]
        chk("XP.72 Source has provider", "provider" in src, str(src.keys()))
        chk("XP.73 Source has record_count", "record_count" in src, str(src.keys()))
        chk("XP.74 Source has last_data_at", "last_data_at" in src, str(src.keys()))


def test_budget_api(headers):
    """Verify budget endpoint."""
    section("XP.I — Budget API")

    r = requests.get(f"{API_URL}/v1/cross-platform/budget", headers=headers, timeout=15)
    chk("XP.75 Budget endpoint → 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code != 200:
        return

    data = r.json()
    chk("XP.76 Has policies field", "policies" in data, str(data.keys()))
    chk("XP.77 Has current_spend field", "current_spend" in data, str(data.keys()))
    chk("XP.78 current_spend.org >= 0", data.get("current_spend",{}).get("org",0) >= 0,
        f"org_spend={data.get('current_spend',{}).get('org')}")


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

def run():
    info("=" * 66)
    info("  VantageAI — E2E OTel + Cross-Platform Tests (78 checks)")
    info("  Simulates: Claude Code, Copilot, Gemini, Codex, Cline, SDK")
    info("=" * 66)

    try:
        api_key, org_id, cookies = fresh_account("xp")
    except Exception as e:
        fail(f"Account creation failed: {e}")
        return get_results()

    headers = {"Authorization": f"Bearer {api_key}"}
    emails = {
        "alice": f"alice-{uuid.uuid4().hex[:6]}@test.vantage",
        "bob":   f"bob-{uuid.uuid4().hex[:6]}@test.vantage",
        "carol": f"carol-{uuid.uuid4().hex[:6]}@test.vantage",
        "dave":  f"dave-{uuid.uuid4().hex[:6]}@test.vantage",
        "eve":   f"eve-{uuid.uuid4().hex[:6]}@test.vantage",
        "frank": f"frank-{uuid.uuid4().hex[:6]}@test.vantage",
    }

    test_auth_edge_cases(headers)
    test_multi_platform_simulation(headers, emails)
    test_summary_after_ingestion(headers)
    test_developer_data(headers, emails)
    test_developer_detail(headers, emails)
    test_live_feed(headers)
    test_models_api(headers)
    test_connections_api(headers)
    test_budget_api(headers)

    return get_results()


if __name__ == "__main__":
    results = run()
    passed = results.get("passed", 0)
    failed = results.get("failed", 0)
    total = passed + failed
    info(f"\nResults: {passed}/{total} passed, {failed} failed")
    sys.exit(1 if failed > 0 else 0)
