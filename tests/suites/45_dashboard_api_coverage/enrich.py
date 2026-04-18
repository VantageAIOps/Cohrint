#!/usr/bin/env python3
"""
enrich.py — Seeds rich dashboard data into existing DA45 accounts.

Reads tests/artifacts/da45_seed_state.json and injects:
  - 120 events spread over 30 days (admin)
  - 40 events from member key (per-member usage)
  - 30 cross-platform usage rows (otel_events via OTLP)
  - Slack alert config
  - Team budgets for all 6 teams

Usage:
    python tests/suites/45_dashboard_api_coverage/enrich.py
"""
import json
import random
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

TESTS_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(TESTS_ROOT))

from config.settings import API_URL

STATE_FILE = TESTS_ROOT / "artifacts" / "da45_seed_state.json"

MODELS = [
    ("claude-sonnet-4-6", "anthropic", 0.003,  0.015),
    ("claude-opus-4-6",   "anthropic", 0.015,  0.075),
    ("claude-haiku-4-5",  "anthropic", 0.00025, 0.00125),
    ("gpt-4o",            "openai",    0.005,  0.015),
    ("gpt-4o-mini",       "openai",    0.00015, 0.0006),
    ("gemini-2.0-flash",  "google",    0.00035, 0.00105),
    ("gemini-1.5-pro",    "google",    0.00125, 0.005),
]

TEAMS = ["backend", "frontend", "infra", "data", "mobile", "ml"]


def hdrs(key):
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def seed_events_spread(api_key: str, count: int, label: str, days: int = 30):
    """Seed `count` events spread randomly across the last `days` days."""
    print(f"  [{label}] Seeding {count} events over {days} days...")
    now = datetime.now(timezone.utc)
    ok = 0
    for i in range(count):
        model, provider, in_rate, out_rate = random.choice(MODELS)
        team = random.choice(TEAMS)
        prompt_tokens = random.randint(300, 4000)
        completion_tokens = random.randint(80, 1200)
        cache_read = random.randint(0, 500) if random.random() < 0.3 else 0
        cost = round(
            prompt_tokens * in_rate / 1000 + completion_tokens * out_rate / 1000, 6
        )
        # Spread across last `days` days, weighted slightly toward recent
        days_ago = random.betavariate(1.5, 4) * days
        ts = now - timedelta(days=days_ago)

        payload = {
            "event_id":          f"da45-enrich-{uuid.uuid4().hex[:12]}",
            "provider":          provider,
            "model":             model,
            "prompt_tokens":     prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_cost_usd":    cost,
            "latency_ms":        random.randint(150, 5000),
            "streaming":         random.random() < 0.4,
            "team":              team,
            "environment":       random.choice(["production", "staging", "dev"]),
            "agent_name":        random.choice(["code-assistant", "review-bot", "doc-gen", "test-runner", "data-pipeline"]),
            "timestamp":         ts.isoformat(),
        }
        if cache_read:
            payload["cache_read_input_tokens"] = cache_read

        r = requests.post(f"{API_URL}/v1/events", json=payload,
                          headers=hdrs(api_key), timeout=15)
        if r.status_code in (200, 201, 202):
            ok += 1
        else:
            print(f"    WARN event {i}: {r.status_code} {r.text[:80]}")
        if i % 20 == 19:
            time.sleep(0.3)
        else:
            time.sleep(0.04)
    print(f"  ✓ {ok}/{count} events accepted")


def seed_budgets(admin_key: str):
    """Set team budgets for all 6 teams."""
    print("  Seeding team budgets...")
    budgets = {
        "backend":  50.0,
        "frontend": 35.0,
        "infra":    20.0,
        "data":     40.0,
        "mobile":   25.0,
        "ml":       60.0,
    }
    ok = 0
    for team, limit in budgets.items():
        r = requests.put(
            f"{API_URL}/v1/admin/team-budgets/{team}",
            json={"budget_usd": limit},
            headers=hdrs(admin_key),
            timeout=15,
        )
        if r.status_code in (200, 201):
            ok += 1
        else:
            print(f"    WARN budget {team}: {r.status_code} {r.text[:80]}")
    print(f"  ✓ {ok}/{len(budgets)} team budgets set")


def seed_alert_config(admin_key: str, org_id: str):
    """Store a (dummy) Slack webhook alert config."""
    print("  Seeding alert config (Slack webhook placeholder)...")
    r = requests.post(
        f"{API_URL}/v1/alerts/slack/{org_id}",
        json={
            "webhook_url": "https://hooks.slack.com/services/T00000000/B00000000/PLACEHOLDER",
            "threshold_usd": 10.0,
            "window_minutes": 60,
        },
        headers=hdrs(admin_key),
        timeout=15,
    )
    if r.status_code in (200, 201):
        print("  ✓ Alert config saved")
    else:
        print(f"  WARN alert: {r.status_code} {r.text[:80]}")


def seed_otel_events(admin_key: str, org_id: str, count: int = 30):
    """Seed OTLP log events (tool_result / api_request) via /v1/otel/v1/logs."""
    print(f"  Seeding {count} OTel log events...")
    now_ns = int(time.time() * 1e9)
    log_bodies = []
    for i in range(count):
        offset_ns = random.randint(0, int(30 * 86400 * 1e9))
        ts_ns = now_ns - offset_ns
        model, provider, _, _ = random.choice(MODELS)
        event_type = random.choice(["api_request", "tool_result", "session_start"])
        log_bodies.append({
            "timeUnixNano": str(ts_ns),
            "severityNumber": 9,
            "severityText": "INFO",
            "body": {"stringValue": f"da45-otel-{uuid.uuid4().hex[:8]}"},
            "attributes": [
                {"key": "event.type",     "value": {"stringValue": event_type}},
                {"key": "model",          "value": {"stringValue": model}},
                {"key": "provider",       "value": {"stringValue": provider}},
                {"key": "cost_usd",       "value": {"doubleValue": round(random.uniform(0.001, 0.05), 5)}},
                {"key": "input_tokens",   "value": {"intValue": str(random.randint(100, 2000))}},
                {"key": "output_tokens",  "value": {"intValue": str(random.randint(50, 800))}},
                {"key": "team",           "value": {"stringValue": random.choice(TEAMS)}},
                {"key": "org_id",         "value": {"stringValue": org_id}},
            ],
        })

    payload = {
        "resourceLogs": [{
            "resource": {
                "attributes": [
                    {"key": "service.name",    "value": {"stringValue": "da45-enrich"}},
                    {"key": "cohrint.org_id",  "value": {"stringValue": org_id}},
                    {"key": "cohrint.api_key", "value": {"stringValue": admin_key}},
                ]
            },
            "scopeLogs": [{"logRecords": log_bodies}],
        }]
    }
    r = requests.post(f"{API_URL}/v1/otel/v1/logs", json=payload,
                      headers=hdrs(admin_key), timeout=20)
    if r.status_code in (200, 201, 202, 204):
        print(f"  ✓ {count} OTel log events sent")
    else:
        print(f"  WARN otel logs: {r.status_code} {r.text[:120]}")


AGENT_SCENARIOS = [
    ("code-review-agent",  ["review-coordinator", "lint-checker", "test-runner", "summarizer"]),
    ("data-pipeline-agent",["orchestrator",       "extractor",    "transformer",  "loader"]),
    ("doc-gen-agent",      ["context-reader",     "outline-gen",  "writer",       "formatter"]),
    ("test-writer-agent",  ["code-analyzer",      "case-gen",     "validator"]),
]


def seed_agent_traces(api_key: str, count: int = 5):
    """Seed `count` agent traces with multi-span trees (trace_id + parent_event_id)."""
    print(f"  Seeding {count} agent traces...")
    now = datetime.now(timezone.utc)
    ok_traces = 0

    for _ in range(count):
        scenario_name, spans = random.choice(AGENT_SCENARIOS)
        trace_id = uuid.uuid4().hex
        team = random.choice(TEAMS)
        days_ago = random.uniform(0, 14)
        base_ts = now - timedelta(days=days_ago)

        root_event_id = f"da45-trace-{uuid.uuid4().hex[:12]}"
        model, provider, in_rate, out_rate = random.choice(MODELS)
        prompt_tokens = random.randint(500, 3000)
        completion_tokens = random.randint(100, 800)
        cost = round(prompt_tokens * in_rate / 1000 + completion_tokens * out_rate / 1000, 6)

        root_payload = {
            "event_id":          root_event_id,
            "provider":          provider,
            "model":             model,
            "prompt_tokens":     prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_cost_usd":    cost,
            "latency_ms":        random.randint(500, 8000),
            "team":              team,
            "trace_id":          trace_id,
            "agent_name":        scenario_name,
            "span_depth":        0,
            "timestamp":         base_ts.isoformat(),
        }
        r = requests.post(f"{API_URL}/v1/events", json=root_payload,
                          headers=hdrs(api_key), timeout=15)
        if r.status_code not in (200, 201, 202):
            print(f"    WARN trace root: {r.status_code} {r.text[:80]}")
            continue

        span_ok = 0
        for depth, span_name in enumerate(spans, start=1):
            span_event_id = f"da45-trace-{uuid.uuid4().hex[:12]}"
            m, prov, ir, or_ = random.choice(MODELS)
            pt = random.randint(200, 1500)
            ct = random.randint(50, 500)
            sc = round(pt * ir / 1000 + ct * or_ / 1000, 6)
            span_ts = base_ts + timedelta(seconds=depth * random.uniform(0.5, 3))
            span_payload = {
                "event_id":          span_event_id,
                "provider":          prov,
                "model":             m,
                "prompt_tokens":     pt,
                "completion_tokens": ct,
                "total_cost_usd":    sc,
                "latency_ms":        random.randint(100, 3000),
                "team":              team,
                "trace_id":          trace_id,
                "parent_event_id":   root_event_id,
                "agent_name":        span_name,
                "span_depth":        depth,
                "timestamp":         span_ts.isoformat(),
            }
            r2 = requests.post(f"{API_URL}/v1/events", json=span_payload,
                               headers=hdrs(api_key), timeout=15)
            if r2.status_code in (200, 201, 202):
                span_ok += 1
            time.sleep(0.05)

        ok_traces += 1
        print(f"    trace={trace_id[:8]}… agent={scenario_name} spans={span_ok}/{len(spans)}")
        time.sleep(0.2)

    print(f"  ✓ {ok_traces}/{count} traces seeded")


def main():
    if not STATE_FILE.exists():
        print(f"State file not found: {STATE_FILE}")
        print("Run: python tests/suites/45_dashboard_api_coverage/seed.py --force")
        sys.exit(1)

    state = json.loads(STATE_FILE.read_text())
    org_id     = state["org_id"]
    admin_key  = state["admin"]["api_key"]
    member_key = state["member"]["api_key"]

    print(f"\n[da45-enrich] Enriching org={org_id}\n")

    # ── Events ────────────────────────────────────────────────────────────────
    seed_events_spread(admin_key,  120, "admin",  days=30)
    seed_events_spread(member_key, 40,  "member", days=30)

    # ── Budgets ───────────────────────────────────────────────────────────────
    seed_budgets(admin_key)

    # ── Alert config ──────────────────────────────────────────────────────────
    seed_alert_config(admin_key, org_id)

    # ── OTel events ───────────────────────────────────────────────────────────
    seed_otel_events(admin_key, org_id, count=30)

    # ── Agent traces ──────────────────────────────────────────────────────────
    seed_agent_traces(admin_key, count=5)

    print("\n✓ Enrichment complete")
    print(f"  Dashboard: https://app.vantageaiops.com/?api_key={admin_key}")


if __name__ == "__main__":
    main()
