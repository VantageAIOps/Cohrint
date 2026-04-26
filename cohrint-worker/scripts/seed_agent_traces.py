#!/usr/bin/env python3
"""
seed_agent_traces.py — Seed rich agent trace data for the Traces dashboard tab.

Creates 20 realistic multi-step traces with 3-level hierarchies:
  depth 0: orchestrator
  depth 1: planner / coder / researcher / reviewer
  depth 2: tool calls (read-file, search, write-file, execute)

Usage:
    cd /path/to/Cohrint
    python cohrint-worker/scripts/seed_agent_traces.py
"""

import random
import time
import uuid
from datetime import datetime, timezone, timedelta

import requests

API_URL   = "https://api.cohrint.com"
ADMIN_KEY = "crt_da45-testorg-9pgmh3_26e4e94d0083612147cd6f20d7d8c5a4"

MODELS = [
    ("claude-sonnet-4-6", "anthropic", 3.0,  15.0),
    ("claude-opus-4-6",   "anthropic", 15.0, 75.0),
    ("claude-haiku-4-5",  "anthropic", 0.8,  4.0),
    ("gpt-4o",            "openai",    2.5,  10.0),
    ("gpt-4o-mini",       "openai",    0.15, 0.6),
]

TEAMS = ["backend", "frontend", "infra", "data", "ml", "product"]

# Realistic agent scenarios — each is a named pipeline with specific sub-agents
SCENARIOS = [
    {
        "name": "code-review-pipeline",
        "team": "backend",
        "root_agent": "code-review-orchestrator",
        "children": [
            {"agent": "syntax-checker",    "feature": "lint"},
            {"agent": "security-scanner",  "feature": "security-scan"},
            {"agent": "test-generator",    "feature": "test"},
            {"agent": "doc-writer",        "feature": "document"},
        ],
        "grandchildren": {
            "test-generator": [
                {"agent": "test-runner",   "feature": "execute"},
                {"agent": "coverage-tool", "feature": "analyze"},
            ]
        },
    },
    {
        "name": "research-agent",
        "team": "data",
        "root_agent": "research-orchestrator",
        "children": [
            {"agent": "web-searcher",      "feature": "search"},
            {"agent": "content-extractor", "feature": "extract"},
            {"agent": "summarizer",        "feature": "summarize"},
        ],
        "grandchildren": {
            "web-searcher": [
                {"agent": "query-builder",  "feature": "query"},
                {"agent": "result-ranker",  "feature": "rank"},
            ]
        },
    },
    {
        "name": "feature-dev-agent",
        "team": "frontend",
        "root_agent": "dev-orchestrator",
        "children": [
            {"agent": "planner",      "feature": "plan"},
            {"agent": "coder",        "feature": "code"},
            {"agent": "tester",       "feature": "test"},
            {"agent": "pr-writer",    "feature": "document"},
        ],
        "grandchildren": {
            "coder": [
                {"agent": "file-reader",  "feature": "read-file"},
                {"agent": "file-writer",  "feature": "write-file"},
                {"agent": "linter",       "feature": "lint"},
            ],
            "tester": [
                {"agent": "test-runner",  "feature": "execute"},
            ],
        },
    },
    {
        "name": "data-pipeline-agent",
        "team": "data",
        "root_agent": "etl-orchestrator",
        "children": [
            {"agent": "schema-analyzer",  "feature": "analyze"},
            {"agent": "transformer",      "feature": "transform"},
            {"agent": "validator",        "feature": "validate"},
            {"agent": "loader",           "feature": "load"},
        ],
        "grandchildren": {
            "transformer": [
                {"agent": "col-mapper",   "feature": "map"},
                {"agent": "deduplicator", "feature": "deduplicate"},
            ]
        },
    },
    {
        "name": "infra-agent",
        "team": "infra",
        "root_agent": "infra-orchestrator",
        "children": [
            {"agent": "tf-planner",   "feature": "plan"},
            {"agent": "cost-scanner", "feature": "analyze"},
            {"agent": "applier",      "feature": "apply"},
        ],
        "grandchildren": {
            "tf-planner": [
                {"agent": "state-reader", "feature": "read-file"},
                {"agent": "diff-checker", "feature": "compare"},
            ]
        },
    },
    {
        "name": "bug-triage-agent",
        "team": "backend",
        "root_agent": "triage-orchestrator",
        "children": [
            {"agent": "log-analyzer",    "feature": "analyze"},
            {"agent": "repro-builder",   "feature": "reproduce"},
            {"agent": "fix-suggester",   "feature": "suggest"},
            {"agent": "pr-creator",      "feature": "create"},
        ],
        "grandchildren": {
            "log-analyzer": [
                {"agent": "pattern-matcher", "feature": "search"},
                {"agent": "timeline-builder","feature": "correlate"},
            ]
        },
    },
    {
        "name": "ml-eval-agent",
        "team": "ml",
        "root_agent": "eval-orchestrator",
        "children": [
            {"agent": "dataset-loader",  "feature": "load"},
            {"agent": "prompt-runner",   "feature": "evaluate"},
            {"agent": "metric-scorer",   "feature": "score"},
            {"agent": "report-writer",   "feature": "summarize"},
        ],
        "grandchildren": {
            "prompt-runner": [
                {"agent": "batch-caller",  "feature": "batch"},
                {"agent": "retry-handler", "feature": "retry"},
            ]
        },
    },
]


def uid() -> str:
    return uuid.uuid4().hex[:16]


def ts_iso(days_ago: float, hour: int, minute: int = 0) -> str:
    days_ago = min(days_ago, 6.9)
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago, hours=12 - hour, minutes=minute)
    return dt.isoformat().replace("+00:00", "Z")


def cost(prompt_tok: int, comp_tok: int, model_tuple: tuple) -> float:
    _, _, in_p, out_p = model_tuple
    return max(0.0001, round((prompt_tok * in_p + comp_tok * out_p) / 1_000_000, 6))


def post_event(payload: dict) -> bool:
    headers = {"Authorization": f"Bearer {ADMIN_KEY}", "Content-Type": "application/json"}
    for attempt in range(3):
        try:
            r = requests.post(f"{API_URL}/v1/events", json=payload, headers=headers, timeout=20)
            if r.status_code in (200, 201, 202):
                return True
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            print(f"  WARN /v1/events → {r.status_code}: {r.text[:120]}")
            return False
        except requests.RequestException as e:
            print(f"  ERR /v1/events: {e}")
            return False
    return False


def seed_trace(scenario: dict, day: float, base_hour: int) -> int:
    """Seed one trace (root + children + grandchildren). Returns span count."""
    trace_id = f"demo-trace-{uid()}"
    spans = 0

    # Pick model for root (prefer sonnet/opus for orchestrators)
    root_model = random.choice(MODELS[:2])
    root_id = f"demo-span-{uid()}"
    root_pt  = random.randint(1200, 5000)
    root_ct  = random.randint(300, 1200)

    ok = post_event({
        "event_id":          root_id,
        "provider":          root_model[1],
        "model":             root_model[0],
        "prompt_tokens":     root_pt,
        "completion_tokens": root_ct,
        "total_cost_usd":    cost(root_pt, root_ct, root_model),
        "latency_ms":        random.randint(2000, 8000),
        "team":              scenario["team"],
        "agent_name":        scenario["root_agent"],
        "trace_id":          trace_id,
        "span_depth":        0,
        "feature":           scenario["name"],
        "environment":       "production",
        "timestamp":         ts_iso(day, base_hour, 0),
    })
    if ok:
        spans += 1

    # Seed children (depth 1)
    child_ids: dict[str, str] = {}
    for i, child_spec in enumerate(scenario["children"]):
        child_model = random.choice(MODELS)
        child_id    = f"demo-span-{uid()}"
        child_ids[child_spec["agent"]] = child_id
        pt = random.randint(300, 2000)
        ct = random.randint(80, 600)

        ok = post_event({
            "event_id":          child_id,
            "provider":          child_model[1],
            "model":             child_model[0],
            "prompt_tokens":     pt,
            "completion_tokens": ct,
            "total_cost_usd":    cost(pt, ct, child_model),
            "latency_ms":        random.randint(400, 3000),
            "team":              scenario["team"],
            "agent_name":        child_spec["agent"],
            "trace_id":          trace_id,
            "parent_event_id":   root_id,
            "span_depth":        1,
            "feature":           child_spec["feature"],
            "environment":       "production",
            "timestamp":         ts_iso(day, base_hour, (i + 1) * 2),
        })
        if ok:
            spans += 1

    # Seed grandchildren (depth 2)
    grandchildren = scenario.get("grandchildren", {})
    minute_offset = len(scenario["children"]) * 2 + 2
    for parent_agent, gc_specs in grandchildren.items():
        parent_id = child_ids.get(parent_agent)
        if not parent_id:
            continue
        for j, gc_spec in enumerate(gc_specs):
            gc_model = random.choice(MODELS[2:])  # haiku / gpt-mini for tool calls
            gc_id    = f"demo-span-{uid()}"
            pt = random.randint(50, 500)
            ct = random.randint(20, 200)

            ok = post_event({
                "event_id":          gc_id,
                "provider":          gc_model[1],
                "model":             gc_model[0],
                "prompt_tokens":     pt,
                "completion_tokens": ct,
                "total_cost_usd":    cost(pt, ct, gc_model),
                "latency_ms":        random.randint(80, 800),
                "team":              scenario["team"],
                "agent_name":        gc_spec["agent"],
                "trace_id":          trace_id,
                "parent_event_id":   parent_id,
                "span_depth":        2,
                "feature":           gc_spec["feature"],
                "environment":       "production",
                "timestamp":         ts_iso(day, base_hour, minute_offset + j),
            })
            if ok:
                spans += 1

    return spans


def main():
    random.seed(99)
    print("=" * 60)
    print("  Cohrint Agent Trace Seeder")
    print("=" * 60)
    print(f"  API : {API_URL}")
    print(f"  Key : {ADMIN_KEY[:28]}…")
    print()

    total_spans  = 0
    total_traces = 0

    # Seed 3 traces per scenario, spread across last 7 days
    for scenario in SCENARIOS:
        days_used = random.sample([0, 0, 1, 1, 2, 3, 4, 5, 6], k=3)
        print(f"  Scenario: {scenario['name']} ({scenario['team']})")
        for day in days_used:
            hour  = random.randint(8, 18)
            spans = seed_trace(scenario, day, hour)
            total_spans  += spans
            total_traces += 1
            print(f"    day-{day} h{hour}: {spans} spans seeded")
            time.sleep(0.5)

    print()
    print(f"  ✓ {total_traces} traces, {total_spans} spans seeded")
    print()
    print("  Verify:")
    url = f"{API_URL}/v1/analytics/traces?period=7"
    r = requests.get(url, headers={"Authorization": f"Bearer {ADMIN_KEY}"}, timeout=15)
    if r.status_code == 200:
        traces = r.json().get("traces", [])
        print(f"  GET /v1/analytics/traces?period=7 → {len(traces)} traces visible")
    else:
        print(f"  GET /v1/analytics/traces?period=7 → {r.status_code}")

    print()
    print("=" * 60)
    print("  Done. Open the Traces tab on:")
    print(f"  Admin      → https://cohrint.com/?api_key={ADMIN_KEY}")
    print("=" * 60)


if __name__ == "__main__":
    main()
