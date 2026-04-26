"""
test_agent_trace_e2e.py -- Agent Trace End-to-End Coverage
===========================================================
Suite 50: Validates that events posted with trace_id appear in
/v1/analytics/traces, and that the trace DAG endpoint returns spans.

Labels: TR.1 - TR.8
"""

import sys
import time
import uuid
import pytest
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.output import section, chk, ok, fail, info


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def post_trace_events(headers, trace_id, n=3):
    """Post n events sharing the same trace_id, chaining parent_event_id."""
    parent_id = None
    event_ids = []
    for i in range(n):
        event_id = uuid.uuid4().hex
        payload = {
            "event_id": event_id,
            "provider": "anthropic",
            "model": "claude-sonnet-4-6",
            "prompt_tokens": 100 + i * 20,
            "completion_tokens": 50 + i * 10,
            "total_cost_usd": round(0.001 * (i + 1), 6),
            "latency_ms": 200 + i * 50,
            "environment": "test",
            "trace_id": trace_id,
            "span_depth": i,
        }
        if parent_id:
            payload["parent_event_id"] = parent_id
        r = requests.post(f"{API_URL}/v1/events", json=payload, headers=headers, timeout=10)
        assert r.status_code in (200, 201, 202), f"Event {i} post failed: {r.status_code} {r.text[:200]}"
        parent_id = event_id
        event_ids.append(event_id)
    return event_ids


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAgentTraceE2E:

    def test_tr1_traces_endpoint_reachable(self, admin_headers):
        section("TR.1 — /v1/analytics/traces endpoint reachable")
        r = requests.get(f"{API_URL}/v1/analytics/traces?period=7", headers=admin_headers, timeout=10)
        chk("200 OK", r.status_code == 200)
        data = r.json()
        chk("has traces key", "traces" in data)
        chk("has period_days key", "period_days" in data)
        ok("TR.1 passed")

    def test_tr2_posted_trace_appears(self, admin_headers):
        section("TR.2 — events with trace_id appear in /traces")
        trace_id = uuid.uuid4().hex
        post_trace_events(admin_headers, trace_id, n=3)
        time.sleep(2)

        r = requests.get(f"{API_URL}/v1/analytics/traces?period=1", headers=admin_headers, timeout=10)
        chk("200 OK", r.status_code == 200)
        traces = r.json().get("traces", [])
        found = any(t.get("trace_id") == trace_id for t in traces)
        chk(f"trace {trace_id[:8]}… found in response", found)
        ok("TR.2 passed")

    def test_tr3_trace_span_count(self, admin_headers):
        section("TR.3 — trace reports correct span count")
        trace_id = uuid.uuid4().hex
        post_trace_events(admin_headers, trace_id, n=4)
        time.sleep(2)

        r = requests.get(f"{API_URL}/v1/analytics/traces?period=1", headers=admin_headers, timeout=10)
        traces = r.json().get("traces", [])
        match = next((t for t in traces if t.get("trace_id") == trace_id), None)
        chk("trace found", match is not None)
        if match:
            chk("span count >= 4", int(match.get("spans", 0)) >= 4)
        ok("TR.3 passed")

    def test_tr4_trace_dag_endpoint(self, admin_headers):
        section("TR.4 — /v1/analytics/traces/:id returns spans")
        trace_id = uuid.uuid4().hex
        post_trace_events(admin_headers, trace_id, n=2)
        time.sleep(2)

        r = requests.get(f"{API_URL}/v1/analytics/traces/{trace_id}", headers=admin_headers, timeout=10)
        chk("200 OK", r.status_code == 200)
        data = r.json()
        chk("has spans key", "spans" in data)
        chk("spans is list", isinstance(data.get("spans"), list))
        chk("at least 2 spans", len(data.get("spans", [])) >= 2)
        ok("TR.4 passed")

    def test_tr5_trace_has_cost(self, admin_headers):
        section("TR.5 — trace aggregates cost from spans")
        trace_id = uuid.uuid4().hex
        post_trace_events(admin_headers, trace_id, n=2)
        time.sleep(2)

        r = requests.get(f"{API_URL}/v1/analytics/traces?period=1", headers=admin_headers, timeout=10)
        traces = r.json().get("traces", [])
        match = next((t for t in traces if t.get("trace_id") == trace_id), None)
        chk("trace found", match is not None)
        if match:
            cost = float(match.get("cost", 0))
            chk("cost > 0", cost > 0)
        ok("TR.5 passed")

    def test_tr6_traces_period_filter(self, admin_headers):
        section("TR.6 — period parameter filters correctly")
        r7 = requests.get(f"{API_URL}/v1/analytics/traces?period=7", headers=admin_headers, timeout=10)
        r30 = requests.get(f"{API_URL}/v1/analytics/traces?period=30", headers=admin_headers, timeout=10)
        chk("period=7 OK", r7.status_code == 200)
        chk("period=30 OK", r30.status_code == 200)
        chk("period_days=7", r7.json().get("period_days") == 7)
        chk("period_days=30", r30.json().get("period_days") == 30)
        ok("TR.6 passed")

    def test_tr7_trace_source_field(self, admin_headers):
        section("TR.7 — trace rows include source field")
        trace_id = uuid.uuid4().hex
        post_trace_events(admin_headers, trace_id, n=1)
        time.sleep(2)

        r = requests.get(f"{API_URL}/v1/analytics/traces?period=1", headers=admin_headers, timeout=10)
        traces = r.json().get("traces", [])
        match = next((t for t in traces if t.get("trace_id") == trace_id), None)
        if match:
            chk("source field present", "source" in match)
        ok("TR.7 passed")

    def test_tr8_unauthenticated_rejected(self):
        section("TR.8 — /traces requires auth")
        r = requests.get(f"{API_URL}/v1/analytics/traces", timeout=10)
        chk("401 without auth", r.status_code == 401)
        ok("TR.8 passed")
